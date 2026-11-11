from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from agentic_swe.config import Settings, get_settings
from agentic_swe.models import RunState, RunStatus, Ticket
from agentic_swe.sandbox import SandboxManager

from .agents import (
    diagnostic_heal,
    manager_ingest,
    persist_run,
    planner_plan,
    programmer_apply,
)


class FactoryState(TypedDict, total=False):
    run: dict[str, Any]


def build_factory_graph(settings: Settings | None = None):
    settings = settings or get_settings()
    manager = SandboxManager(settings)

    def _load(data: FactoryState) -> tuple[RunState, Any]:
        run = RunState.model_validate(data["run"])
        sandbox = manager.get(run.run_id)
        if sandbox is None and run.work_dir:
            from agentic_swe.sandbox.local import LocalSandbox

            sandbox = LocalSandbox(
                Path(run.work_dir),
                timeout_sec=settings.command_timeout_sec,
            )
            manager._sandboxes[run.run_id] = sandbox
        return run, sandbox

    def _dump(run: RunState) -> FactoryState:
        persist_run(run, settings.runs_dir)
        return {"run": run.model_dump(mode="json")}

    def node_manager(data: FactoryState) -> FactoryState:
        run, _ = _load(data)
        # Create sandbox on first entry
        if run.work_dir is None:
            sandbox = manager.create(Path(run.repo_path), run_id=run.run_id)
            run.work_dir = str(sandbox.work_dir)
        run = manager_ingest(run)
        return _dump(run)

    def node_planner(data: FactoryState) -> FactoryState:
        run, sandbox = _load(data)
        assert sandbox is not None
        run = planner_plan(run, sandbox)
        return _dump(run)

    def node_programmer(data: FactoryState) -> FactoryState:
        run, sandbox = _load(data)
        assert sandbox is not None
        run = programmer_apply(run, sandbox, settings)
        return _dump(run)

    def node_diagnostic(data: FactoryState) -> FactoryState:
        run, sandbox = _load(data)
        assert sandbox is not None
        run = diagnostic_heal(run, sandbox, settings)
        return _dump(run)

    def route_after_programmer(data: FactoryState) -> str:
        run = RunState.model_validate(data["run"])
        if run.status == RunStatus.SUCCEEDED:
            return "done"
        if run.status in {RunStatus.HEALING, RunStatus.TESTING, RunStatus.CODING}:
            return "heal"
        return "done"

    def route_after_heal(data: FactoryState) -> str:
        run = RunState.model_validate(data["run"])
        if run.status == RunStatus.SUCCEEDED:
            return "done"
        if run.status == RunStatus.FAILED:
            return "done"
        if len(run.heal_attempts) >= settings.max_heal_attempts:
            run.status = RunStatus.FAILED
            run.error = "Heal attempts exhausted"
            data["run"] = run.model_dump(mode="json")
            persist_run(run, settings.runs_dir)
            return "done"
        if run.status == RunStatus.HEALING and run.test_results and not run.test_results[-1].passed:
            # diagnostic_heal already applied+tested; if still failing, loop
            return "heal"
        return "done"

    graph = StateGraph(FactoryState)
    graph.add_node("manager", node_manager)
    graph.add_node("planner", node_planner)
    graph.add_node("programmer", node_programmer)
    graph.add_node("diagnostic", node_diagnostic)

    graph.set_entry_point("manager")
    graph.add_edge("manager", "planner")
    graph.add_edge("planner", "programmer")
    graph.add_conditional_edges(
        "programmer",
        route_after_programmer,
        {"heal": "diagnostic", "done": END},
    )
    graph.add_conditional_edges(
        "diagnostic",
        route_after_heal,
        {"heal": "diagnostic", "done": END},
    )

    return graph.compile()


def run_factory(
    ticket: Ticket,
    repo_path: Path,
    settings: Settings | None = None,
    auto_approve: bool = True,
) -> RunState:
    settings = settings or get_settings()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)

    initial = RunState(
        ticket=ticket,
        repo_path=str(repo_path.resolve()),
        status=RunStatus.PENDING,
    )
    if auto_approve:
        initial.note("Local mode: plan auto-approved")

    app = build_factory_graph(settings)
    result = app.invoke({"run": initial.model_dump(mode="json")})
    final = RunState.model_validate(result["run"])
    persist_run(final, settings.runs_dir)
    return final
