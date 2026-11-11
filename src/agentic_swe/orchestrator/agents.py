from __future__ import annotations

import re
from pathlib import Path

from agentic_swe.code_intel import index_python_repo
from agentic_swe.config import Settings
from agentic_swe.healing import diagnose_failure, refine_repair_brief
from agentic_swe.models import (
    EditPlan,
    FilePatch,
    HealAttempt,
    PlanStep,
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


def planner_plan(state: RunState, sandbox: LocalSandbox) -> RunState:
    graph = index_python_repo(sandbox.work_dir)
    state.graph_summary = graph.summary()

    keywords = _keywords(f"{state.ticket.title} {state.ticket.description}")
    candidates = graph.find_files_for_keywords(keywords) or [
        p for p in sandbox.list_files("**/*.py") if not p.startswith("tests/")
    ]

    # Prefer non-test production modules
    prod = [p for p in candidates if not p.startswith("tests/")]
    target = prod[0] if prod else (candidates[0] if candidates else "src/calculator.py")

    plan = EditPlan(
        summary=f"Address: {state.ticket.title}",
        steps=[
            PlanStep(
                description=f"Inspect and fix logic in {target}",
                target_files=[target],
                rationale="Selected via AST keyword / path heuristics",
            ),
            PlanStep(
                description="Run unit tests and heal if needed",
                target_files=[],
                rationale="Verification gate before success",
            ),
        ],
        risks=["Heuristic planner may miss multi-file interactions"],
        test_command="pytest -q",
        approved=True,  # local groundbase auto-approves
    )
    state.plan = plan
    state.status = RunStatus.CODING
    state.note(f"Planner drafted plan targeting {target}")
    return state


def programmer_apply(state: RunState, sandbox: LocalSandbox, settings: Settings) -> RunState:
    assert state.plan is not None
    state.status = RunStatus.CODING

    # If we already have patches from healing, apply those; else generate initial fix.
    if not state.patches:
        state.patches = _heuristic_patches(state, sandbox)

    touched = 0
    for patch in state.patches:
        if touched >= settings.max_files_touched:
            state.note("Max files touched — skipping remaining patches")
            break
        if patch.action == "delete":
            sandbox.delete_file(patch.path)
        else:
            sandbox.write_file(patch.path, patch.content)
        touched += 1
        state.note(f"Programmer wrote {patch.path}")

    return _run_tests(state, sandbox)


def diagnostic_heal(state: RunState, sandbox: LocalSandbox, settings: Settings) -> RunState:
    if not state.test_results:
        state.status = RunStatus.FAILED
        state.error = "No test results to diagnose"
        return state

    latest = state.test_results[-1]
    if latest.passed:
        state.status = RunStatus.SUCCEEDED
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

    patches = _heuristic_patches(state, sandbox, repair_brief=brief)
    heal = HealAttempt(
        attempt=attempt_no,
        diagnosis=diagnosis,
        repair_brief=brief,
        patches=patches,
    )
    state.heal_attempts.append(heal)
    state.patches = patches
    state.note(f"Diagnostic attempt {attempt_no}: {diagnosis}")

    # Apply and retest
    for patch in patches:
        sandbox.write_file(patch.path, patch.content)
    state = _run_tests(state, sandbox)
    heal.test_result = state.test_results[-1]
    return state


def _run_tests(state: RunState, sandbox: LocalSandbox) -> RunState:
    state.status = RunStatus.TESTING
    command = state.plan.test_command if state.plan else "pytest -q"
    code, stdout, stderr, duration = sandbox.run_tests(command)
    result = TestResult.from_process(command, code, stdout, stderr, duration)
    state.test_results.append(result)
    if result.passed:
        state.status = RunStatus.SUCCEEDED
        state.note("Tests passed")
    else:
        state.status = RunStatus.HEALING
        state.note(f"Tests failed (exit {code})")
    return state


def _keywords(text: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
    stop = {"the", "and", "for", "that", "with", "from", "this", "fix", "make", "sure", "equals"}
    return [t for t in tokens if t not in stop][:12]


def _heuristic_patches(
    state: RunState,
    sandbox: LocalSandbox,
    repair_brief: str | None = None,
) -> list[FilePatch]:
    """Offline programmer: apply known fixture fix or leave a no-op scaffold."""
    brief = (repair_brief or "").lower()
    target = "src/calculator.py"
    if state.plan and state.plan.steps and state.plan.steps[0].target_files:
        target = state.plan.steps[0].target_files[0]

    try:
        current = sandbox.read_file(target)
    except Exception:
        # Create a minimal module if missing
        content = (
            '"""Calculator utilities."""\n\n'
            "def add(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )
        return [FilePatch(path=target, content=content)]

    # Fixture bug: `return a - b` or `return a` instead of sum
    if "calculator" in target or "add" in brief or "a + b" in brief:
        fixed = current
        fixed = re.sub(
            r"def add\(a:\s*int,\s*b:\s*int\)\s*->\s*int:\s*\n\s*return .+",
            "def add(a: int, b: int) -> int:\n    return a + b",
            fixed,
            count=1,
        )
        if fixed == current and "return a + b" not in current:
            # Fallback: rewrite file cleanly
            fixed = (
                '"""Calculator utilities."""\n\n'
                "def add(a: int, b: int) -> int:\n"
                "    return a + b\n"
            )
        if fixed != current:
            return [FilePatch(path=target, content=fixed)]

    # Generic: no change — healing loop will surface failure
    return [FilePatch(path=target, content=current)]


def persist_run(state: RunState, runs_dir: Path) -> Path:
    run_dir = runs_dir / state.run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    out = run_dir / "state.json"
    out.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return out
