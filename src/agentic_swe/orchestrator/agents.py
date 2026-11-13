from __future__ import annotations

import re
from pathlib import Path

from agentic_swe.code_intel import detect_test_command, index_repo
from agentic_swe.config import Settings
from agentic_swe.healing import diagnose_failure, refine_repair_brief
from agentic_swe.llm import llm_available, run_tool_calling_agent, structured_generate
from agentic_swe.mcp_client import build_sandbox_langchain_tools
from agentic_swe.models import (
    EditPlan,
    FilePatch,
    HealAttempt,
    PatchSet,
    PlanStep,
    ReviewResult,
    RunState,
    RunStatus,
    TestResult,
)
from agentic_swe.sandbox import LocalSandbox


def manager_ingest(state: RunState) -> RunState:
    state.status = RunStatus.PLANNING
    criteria = state.ticket.acceptance_criteria or [
        "Relevant unit tests pass",
        "Minimal focused change set",
    ]
    state.ticket.acceptance_criteria = criteria
    state.note(f"Manager accepted ticket: {state.ticket.title}")
    return state


def planner_plan(state: RunState, sandbox: LocalSandbox, settings: Settings) -> RunState:
    graph = index_repo(sandbox.work_dir)
    state.graph_summary = graph.summary()
    test_command = detect_test_command(sandbox.work_dir)

    keywords = _keywords(f"{state.ticket.title} {state.ticket.description}")
    source_files = [
        p
        for p in sandbox.list_files("**/*")
        if p.endswith((".py", ".ts", ".tsx", ".js", ".jsx"))
        and "/test" not in f"/{p}"
        and not p.startswith("tests/")
        and not p.endswith(".test.ts")
        and not p.endswith(".test.js")
        and not p.endswith(".test.tsx")
        and not p.endswith(".spec.ts")
        and not p.endswith(".spec.js")
    ]
    candidates = graph.find_files_for_keywords(keywords) or source_files
    prod = [
        p
        for p in candidates
        if not p.startswith("tests/")
        and not p.endswith((".test.ts", ".test.js", ".test.tsx", ".spec.ts", ".spec.js"))
    ]
    target = prod[0] if prod else (candidates[0] if candidates else "src/calculator.py")

    plan = _llm_plan(state, settings, target, candidates) or EditPlan(
        summary=f"Address: {state.ticket.title}",
        steps=[
            PlanStep(
                description=f"Inspect and fix logic in {target}",
                target_files=[target],
                rationale="Selected via multi-language keyword / path heuristics",
            ),
            PlanStep(
                description="Run unit tests and heal if needed",
                target_files=[],
                rationale="Verification gate before success",
            ),
        ],
        risks=["Heuristic planner may miss multi-file interactions"],
        test_command=test_command,
        approved=False,
    )

    state.plan = plan
    if state.auto_approve:
        plan.approved = True
        state.status = RunStatus.CODING
        state.note(f"Planner drafted plan targeting {target} (auto-approved)")
    else:
        state.status = RunStatus.AWAITING_APPROVAL
        state.note(f"Planner drafted plan targeting {target} (awaiting approval)")
    return state


def approve_plan(state: RunState, decision: dict | None = None) -> RunState:
    """Apply a human (or auto) approval decision to the drafted plan."""
    assert state.plan is not None
    decision = decision or {}
    approved = bool(decision.get("approved", state.auto_approve or state.plan.approved))
    feedback = str(decision.get("feedback") or "").strip()

    if not approved:
        state.plan.approved = False
        state.status = RunStatus.ABORTED
        state.error = feedback or "Plan rejected by human reviewer"
        state.note(state.error)
        return state

    state.plan.approved = True
    if feedback:
        state.note(f"Plan approved with feedback: {feedback}")
    else:
        state.note("Plan approved")
    state.status = RunStatus.CODING
    return state


def programmer_apply(state: RunState, sandbox: LocalSandbox, settings: Settings) -> RunState:
    assert state.plan is not None
    if not state.plan.approved:
        state.status = RunStatus.ABORTED
        state.error = "Refusing to code without an approved plan"
        return state

    state.status = RunStatus.CODING

    if not state.patches:
        revision = ""
        if state.reviews and not state.reviews[-1].approved:
            revision = state.reviews[-1].revision_brief
        state.patches = (
            _llm_patches(state, sandbox, settings, revision_brief=revision)
            or _heuristic_patches(state, sandbox, repair_brief=revision or None)
        )

    _apply_patches(state, sandbox, settings)
    return _run_tests(state, sandbox)


def diagnostic_heal(state: RunState, sandbox: LocalSandbox, settings: Settings) -> RunState:
    if not state.test_results:
        state.status = RunStatus.FAILED
        state.error = "No test results to diagnose"
        return state

    latest = state.test_results[-1]
    if latest.passed:
        state.status = RunStatus.REVIEWING
        return state

    attempt_no = len(state.heal_attempts) + 1
    if attempt_no > settings.max_heal_attempts:
        state.status = RunStatus.FAILED
        state.error = f"Exceeded max heal attempts ({settings.max_heal_attempts})"
        state.note(state.error)
        return state

    state.status = RunStatus.HEALING
    diagnosis, brief = diagnose_failure(latest)
    brief = refine_repair_brief(diagnosis, brief, prior_attempts=attempt_no - 1)

    patches = (
        _llm_patches(state, sandbox, settings, repair_brief=brief)
        or _heuristic_patches(state, sandbox, repair_brief=brief)
    )
    heal = HealAttempt(
        attempt=attempt_no,
        diagnosis=diagnosis,
        repair_brief=brief,
        patches=patches,
    )
    state.heal_attempts.append(heal)
    state.patches = patches
    state.note(f"Diagnostic attempt {attempt_no}: {diagnosis}")

    _apply_patches(state, sandbox, settings)
    state = _run_tests(state, sandbox)
    heal.test_result = state.test_results[-1]
    if state.test_results[-1].passed:
        state.status = RunStatus.REVIEWING
    return state


def reviewer_review(state: RunState, sandbox: LocalSandbox, settings: Settings) -> RunState:
    """Gate success behind a reviewer pass after green tests."""
    state.status = RunStatus.REVIEWING
    if not state.test_results or not state.test_results[-1].passed:
        state.status = RunStatus.FAILED
        state.error = "Reviewer invoked without passing tests"
        return state

    review = _llm_review(state, sandbox, settings) or _heuristic_review(state, sandbox)
    state.reviews.append(review)

    if review.approved:
        state.status = RunStatus.SUCCEEDED
        state.note(f"Reviewer approved: {review.summary}")
        return state

    if len(state.reviews) >= settings.max_heal_attempts:
        state.status = RunStatus.FAILED
        state.error = "Reviewer rejected changes too many times"
        state.note(state.error)
        return state

    state.patches = []
    state.status = RunStatus.CODING
    state.note(f"Reviewer requested changes: {review.revision_brief or review.summary}")
    return state


def _apply_patches(state: RunState, sandbox: LocalSandbox, settings: Settings) -> None:
    touched = 0
    for patch in state.patches:
        if touched >= settings.max_files_touched:
            state.note("Max files touched - skipping remaining patches")
            break
        if patch.action == "delete":
            sandbox.delete_file(patch.path)
        else:
            sandbox.write_file(patch.path, patch.content)
        touched += 1
        state.note(f"Programmer wrote {patch.path}")


def _run_tests(state: RunState, sandbox: LocalSandbox) -> RunState:
    state.status = RunStatus.TESTING
    command = state.plan.test_command if state.plan else "pytest -q"
    code, stdout, stderr, duration = sandbox.run_tests(command)
    result = TestResult.from_process(command, code, stdout, stderr, duration)
    state.test_results.append(result)
    if result.passed:
        state.status = RunStatus.REVIEWING
        state.note("Tests passed - sending to reviewer")
    else:
        state.status = RunStatus.HEALING
        state.note(f"Tests failed (exit {code})")
    return state


def _llm_plan(
    state: RunState,
    settings: Settings,
    default_target: str,
    candidates: list[str],
) -> EditPlan | None:
    if not llm_available(settings):
        return None
    system = (
        "You are the Planner agent in a software engineering factory. "
        "Produce a minimal, concrete edit plan for the ticket."
    )
    user = (
        f"Ticket title: {state.ticket.title}\n"
        f"Description: {state.ticket.description}\n"
        f"Acceptance: {state.ticket.acceptance_criteria}\n"
        f"Candidate files: {candidates[:20]}\n"
        f"Default target hint: {default_target}\n"
        f"Graph summary: {state.graph_summary}\n"
        "Prefer pytest -q as test_command for Python repos."
    )
    plan = structured_generate(settings, system=system, user=user, schema=EditPlan)
    if plan is None:
        return None
    plan.approved = False
    if not plan.test_command:
        plan.test_command = detect_test_command(Path(state.work_dir or state.repo_path))
    state.note("Planner used LLM structured plan")
    return plan


def _llm_patches(
    state: RunState,
    sandbox: LocalSandbox,
    settings: Settings,
    repair_brief: str | None = None,
    revision_brief: str | None = None,
) -> list[FilePatch] | None:
    if not llm_available(settings):
        return None
    assert state.plan is not None

    if settings.use_mcp_tools:
        mcp_patches = _mcp_tool_patches(
            state,
            sandbox,
            settings,
            repair_brief=repair_brief,
            revision_brief=revision_brief,
        )
        if mcp_patches:
            return mcp_patches

    targets: list[str] = []
    for step in state.plan.steps:
        targets.extend(step.target_files)
    if not targets:
        targets = ["src/calculator.py"]

    file_blobs: list[str] = []
    for path in targets[: settings.max_files_touched]:
        try:
            file_blobs.append(f"### {path}\n{sandbox.read_file(path)}")
        except Exception:
            file_blobs.append(f"### {path}\n<missing>")

    system = (
        "You are the Programmer agent. Return full file contents for each changed file. "
        "Do not weaken or delete tests. Prefer minimal edits."
    )
    user = (
        f"Ticket: {state.ticket.title}\n{state.ticket.description}\n"
        f"Plan summary: {state.plan.summary}\n"
        f"Repair brief: {repair_brief or ''}\n"
        f"Reviewer revision brief: {revision_brief or ''}\n"
        f"Files:\n\n" + "\n\n".join(file_blobs)
    )
    patch_set = structured_generate(settings, system=system, user=user, schema=PatchSet)
    if patch_set is None or not patch_set.patches:
        return None
    state.note("Programmer used LLM patch proposal")
    return patch_set.patches


def _mcp_tool_patches(
    state: RunState,
    sandbox: LocalSandbox,
    settings: Settings,
    repair_brief: str | None = None,
    revision_brief: str | None = None,
) -> list[FilePatch] | None:
    """Let the LLM Programmer explore and edit the sandbox via MCP tool calls."""
    tools = build_sandbox_langchain_tools(sandbox, settings)
    system = (
        "You are an autonomous SWE Programmer agent connected to MCP sandbox and code-intel tools. "
        "Inspect the target files, write minimal fixes using mcp_sandbox_write_file, and verify "
        "with mcp_sandbox_run_tests. Do not weaken or delete tests."
    )
    user = (
        f"Ticket: {state.ticket.title}\n{state.ticket.description}\n"
        f"Plan summary: {state.plan.summary if state.plan else ''}\n"
        f"Repair brief: {repair_brief or ''}\n"
        f"Reviewer revision brief: {revision_brief or ''}\n"
    )
    executed = run_tool_calling_agent(settings, system=system, user=user, tools=tools)
    if not executed:
        return None

    patches: list[FilePatch] = []
    for call in executed:
        if call.get("tool") == "mcp_sandbox_write_file":
            args = call.get("args") or {}
            path = args.get("path")
            content = args.get("content")
            if path and isinstance(content, str):
                patches.append(FilePatch(path=str(path), content=content))
    if patches:
        state.note(f"Programmer executed {len(executed)} MCP tool call(s)")
        return patches
    return None


def _llm_review(
    state: RunState,
    sandbox: LocalSandbox,
    settings: Settings,
) -> ReviewResult | None:
    if not llm_available(settings):
        return None
    changed = "\n".join(f"- {p.path}" for p in state.patches) or "(no recorded patches)"
    system = (
        "You are the Reviewer agent. Approve only if the change is minimal, "
        "tests were not weakened, and the ticket appears addressed."
    )
    user = (
        f"Ticket: {state.ticket.title}\n{state.ticket.description}\n"
        f"Changed files:\n{changed}\n"
        f"Last test exit: {state.test_results[-1].exit_code}\n"
        f"Last test stdout (tail):\n{state.test_results[-1].stdout[-1500:]}\n"
    )
    review = structured_generate(settings, system=system, user=user, schema=ReviewResult)
    if review is None:
        return None
    state.note("Reviewer used LLM judgment")
    return review


def _heuristic_review(state: RunState, sandbox: LocalSandbox) -> ReviewResult:
    issues: list[str] = []
    for patch in state.patches:
        if patch.path.startswith("tests/") and patch.action == "delete":
            issues.append(f"Deleted test file {patch.path}")
        if patch.path.startswith("tests/") and "assert" not in patch.content:
            issues.append(f"Test file {patch.path} may have been hollowed out")

    # Ensure production code still exists for planned targets
    if state.plan:
        for step in state.plan.steps:
            for path in step.target_files:
                try:
                    sandbox.read_file(path)
                except Exception:
                    issues.append(f"Missing planned target file {path}")

    if issues:
        return ReviewResult(
            approved=False,
            summary="Heuristic reviewer found issues",
            issues=issues,
            revision_brief="; ".join(issues),
        )
    return ReviewResult(
        approved=True,
        summary="Heuristic reviewer: tests green and no obvious test weakening",
        issues=[],
    )


def _keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
    stop = {
        "the",
        "and",
        "for",
        "that",
        "with",
        "from",
        "this",
        "fix",
        "make",
        "sure",
        "equals",
    }
    return [t for t in tokens if t not in stop][:12]


def _heuristic_patches(
    state: RunState,
    sandbox: LocalSandbox,
    repair_brief: str | None = None,
) -> list[FilePatch]:
    """Offline programmer: apply known fixture fixes or leave a no-op scaffold."""
    brief = (repair_brief or "").lower()
    target = "src/calculator.py"
    if state.plan and state.plan.steps and state.plan.steps[0].target_files:
        target = state.plan.steps[0].target_files[0]

    try:
        current = sandbox.read_file(target)
    except Exception:
        if target.endswith((".ts", ".tsx", ".js", ".jsx")):
            content = (
                "export function add(a, b) {\n"
                "  return a + b;\n"
                "}\n"
            )
        else:
            content = (
                '"""Calculator utilities."""\n\n'
                "def add(a: int, b: int) -> int:\n"
                "    return a + b\n"
            )
        return [FilePatch(path=target, content=content)]

    if "calculator" in target or "add" in brief or "a + b" in brief or not brief:
        fixed = current
        if target.endswith((".ts", ".tsx", ".js", ".jsx")):
            fixed = re.sub(
                r"function\s+add\s*\([^)]*\)\s*\{[\s\S]*?return\s+[^;]+;",
                "function add(a, b) {\n  return a + b;",
                fixed,
                count=1,
            )
            if fixed == current and "return a + b" not in current:
                fixed = "export function add(a, b) {\n  return a + b;\n}\n"
        else:
            fixed = re.sub(
                r"def add\(a:\s*int,\s*b:\s*int\)\s*->\s*int:\s*\n\s*return .+",
                "def add(a: int, b: int) -> int:\n    return a + b",
                fixed,
                count=1,
            )
            if fixed == current and "return a + b" not in current:
                fixed = (
                    '"""Calculator utilities."""\n\n'
                    "def add(a: int, b: int) -> int:\n"
                    "    return a + b\n"
                )
        if fixed != current:
            return [FilePatch(path=target, content=fixed)]

    return [FilePatch(path=target, content=current)]


def persist_run(state: RunState, runs_dir: Path) -> Path:
    run_dir = runs_dir / state.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "state.json"
    out.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return out
