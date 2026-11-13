from __future__ import annotations

"""MCP tool surface exposing both the isolated Sandbox and the Multi-Agent SWE Factory.

Supports stdio (default for IDE agents like Antigravity, Claude Code, Cursor)
as well as SSE and Streamable-HTTP transports for remote/networked agents.
"""

from pathlib import Path
from typing import Any, Literal

from mcp.server.mcpserver import MCPServer

from agentic_swe.code_intel import detect_languages, detect_test_command, index_repo
from agentic_swe.config import Settings, get_settings
from agentic_swe.healing import diagnose_failure, refine_repair_brief
from agentic_swe.models import RunState, RunStatus, TestResult, Ticket, new_id
from agentic_swe.observability import changed_files, list_runs, load_run
from agentic_swe.orchestrator import run_factory
from agentic_swe.orchestrator.agents import planner_plan
from agentic_swe.sandbox.local import LocalSandbox
from agentic_swe.sandbox.manager import SandboxManager

mcp = MCPServer(
    "agentic-swe",
    instructions=(
        "Agentic SWE Workbench MCP Server. Provides both low-level isolated sandbox tools "
        "(sandbox_*) and high-level multi-agent SWE factory tools (factory_*, agent_*, "
        "code_intel_*, runs_*)."
    ),
)
_settings: Settings = get_settings()
_manager = SandboxManager(_settings)
_active_run_id: str | None = None


def configure_server(settings: Settings) -> None:
    """Rebind the module-level settings and SandboxManager (useful for tests & CLI)."""
    global _settings, _manager, _active_run_id
    _settings = settings
    _manager = SandboxManager(settings)
    _active_run_id = None


def _require_sandbox():
    if not _active_run_id:
        raise RuntimeError("No active sandbox. Call sandbox_create first.")
    sandbox = _manager.get(_active_run_id)
    if sandbox is None:
        raise RuntimeError(f"Sandbox {_active_run_id} not found.")
    return sandbox


# ---------------------------------------------------------------------------
# Low-level Sandbox Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def sandbox_create(repo_path: str, run_id: str | None = None) -> dict[str, Any]:
    """Create an isolated local sandbox by copying a source repository."""
    global _active_run_id
    rid = run_id or new_id("run")
    sandbox = _manager.create(Path(repo_path), run_id=rid)
    _active_run_id = rid
    return {"run_id": rid, "work_dir": str(sandbox.work_dir)}


@mcp.tool()
def sandbox_list_files(pattern: str = "**/*") -> list[str]:
    """List files inside the active sandbox."""
    return _require_sandbox().list_files(pattern)


@mcp.tool()
def sandbox_read_file(path: str) -> str:
    """Read a file from the active sandbox."""
    return _require_sandbox().read_file(path)


@mcp.tool()
def sandbox_write_file(path: str, content: str) -> dict[str, str]:
    """Write a file inside the active sandbox."""
    _require_sandbox().write_file(path, content)
    return {"status": "ok", "path": path}


@mcp.tool()
def sandbox_run(command: str) -> dict[str, Any]:
    """Run a shell command inside the active sandbox."""
    code, stdout, stderr, duration = _require_sandbox().run(command)
    return {
        "exit_code": code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_sec": duration,
    }


@mcp.tool()
def sandbox_run_tests(command: str = "pytest -q") -> dict[str, Any]:
    """Run tests inside the active sandbox."""
    code, stdout, stderr, duration = _require_sandbox().run_tests(command)
    return {
        "exit_code": code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_sec": duration,
        "passed": code == 0,
    }


@mcp.tool()
def sandbox_destroy() -> dict[str, str]:
    """Destroy the active sandbox worktree."""
    global _active_run_id
    if _active_run_id:
        _manager.destroy(_active_run_id)
        _active_run_id = None
    return {"status": "destroyed"}


# ---------------------------------------------------------------------------
# High-level Multi-Agent Factory & Code Intelligence Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def code_intel_graph(
    repo_path: str,
    keyword: str | None = None,
    symbol: str | None = None,
) -> dict[str, Any]:
    """Index a repository (Python + TS/JS) and query its dependency graph, symbols, and test command."""
    root = Path(repo_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository not found: {repo_path}")

    graph = index_repo(root)
    result: dict[str, Any] = {
        "summary": graph.summary(),
        "languages": detect_languages(root),
        "test_command": detect_test_command(root),
    }
    if symbol:
        matches = graph.find_by_name(symbol)
        result["matching_symbols"] = [
            {"name": s.name, "kind": s.kind, "path": s.path, "lineno": s.lineno}
            for s in matches[:30]
        ]
    else:
        result["sample_symbols"] = [
            {"name": s.name, "kind": s.kind, "path": s.path, "lineno": s.lineno}
            for s in list(graph.symbols.values())[:25]
        ]
    if keyword:
        keywords = [k.strip() for k in keyword.replace(",", " ").split() if k.strip()]
        result["candidate_files"] = graph.find_files_for_keywords(keywords)
    return result


@mcp.tool()
def agent_plan(
    repo_path: str,
    ticket: str,
    title: str | None = None,
) -> dict[str, Any]:
    """Run the Planner agent on a repository to produce a structured EditPlan without mutating source files."""
    root = Path(repo_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository not found: {repo_path}")

    issue = Ticket(
        title=title or ticket[:72],
        description=ticket,
        acceptance_criteria=["Unit tests pass", "Minimal diff"],
    )
    state = RunState(
        ticket=issue,
        repo_path=str(root),
        work_dir=str(root),
        status=RunStatus.PLANNING,
        auto_approve=False,
    )
    readonly_sb = LocalSandbox(root, timeout_sec=_settings.command_timeout_sec)
    planned = planner_plan(state, readonly_sb, _settings)
    return {
        "ticket": issue.model_dump(mode="json"),
        "plan": planned.plan.model_dump(mode="json") if planned.plan else None,
        "graph_summary": planned.graph_summary,
    }


@mcp.tool()
def agent_diagnose(
    command: str,
    exit_code: int,
    stdout: str,
    stderr: str = "",
    prior_attempts: int = 0,
) -> dict[str, str]:
    """Run the Diagnostic & PatchRefiner agent on failing test output to produce a repair brief."""
    tr = TestResult(
        command=command,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        passed=(exit_code == 0),
    )
    diagnosis, brief = diagnose_failure(tr)
    refined = refine_repair_brief(diagnosis, brief, prior_attempts=prior_attempts)
    return {
        "diagnosis": diagnosis,
        "repair_brief": brief,
        "refined_repair_brief": refined,
    }


@mcp.tool()
def factory_run(
    repo_path: str,
    ticket: str,
    title: str | None = None,
    auto_approve: bool = True,
) -> dict[str, Any]:
    """Execute the full multi-agent SWE factory (Manager -> Planner -> Programmer -> Diagnostic -> Reviewer)."""
    root = Path(repo_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository not found: {repo_path}")

    issue = Ticket(
        title=title or ticket[:72],
        description=ticket,
        acceptance_criteria=["Unit tests pass", "Minimal diff"],
    )
    result = run_factory(
        ticket=issue,
        repo_path=root,
        settings=_settings,
        auto_approve=auto_approve,
    )
    return _format_run_state(result)


@mcp.tool()
def factory_approve(
    repo_path: str,
    ticket: str,
    approved: bool = True,
    feedback: str = "",
    title: str | None = None,
) -> dict[str, Any]:
    """Execute the factory with an explicit human-in-the-loop plan approval or rejection decision."""
    root = Path(repo_path).resolve()
    if not root.is_dir():
        raise ValueError(f"Repository not found: {repo_path}")

    issue = Ticket(
        title=title or ticket[:72],
        description=ticket,
        acceptance_criteria=["Unit tests pass", "Minimal diff"],
    )
    result = run_factory(
        ticket=issue,
        repo_path=root,
        settings=_settings,
        auto_approve=False,
        approval_decision={"approved": approved, "feedback": feedback},
    )
    return _format_run_state(result)


@mcp.tool()
def runs_list(limit: int = 20) -> list[dict[str, Any]]:
    """List recent local factory runs persisted under .runs/."""
    rows = list_runs(settings=_settings, limit=limit)
    return [
        {
            "run_id": r.run_id,
            "status": r.status,
            "title": r.title,
            "work_dir": r.work_dir,
            "heal_attempts": r.heal_attempts,
            "reviews": r.reviews,
            "path": str(r.path),
        }
        for r in rows
    ]


@mcp.tool()
def runs_show(run_id: str) -> dict[str, Any]:
    """Load and return full details for a persisted run by run_id."""
    run = load_run(run_id, settings=_settings)
    return _format_run_state(run)


def _format_run_state(run: RunState) -> dict[str, Any]:
    last_test = run.test_results[-1].model_dump(mode="json") if run.test_results else None
    last_review = run.reviews[-1].model_dump(mode="json") if run.reviews else None
    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "ticket": run.ticket.model_dump(mode="json"),
        "repo_path": run.repo_path,
        "work_dir": run.work_dir,
        "plan": run.plan.model_dump(mode="json") if run.plan else None,
        "changed_files": changed_files(run),
        "heal_attempts": len(run.heal_attempts),
        "reviews": len(run.reviews),
        "last_test": last_test,
        "last_review": last_review,
        "messages": run.messages[-15:],
        "error": run.error,
    }


def main(
    transport: Literal["stdio", "sse", "streamable-http"] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    if transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=transport, host=host, port=port)


if __name__ == "__main__":
    main()
