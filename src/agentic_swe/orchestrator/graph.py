from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt

from agentic_swe.config import Settings, get_settings
from agentic_swe.models import RunState, RunStatus, Ticket
from agentic_swe.sandbox import SandboxManager

from .agents import (
    approve_plan,
    diagnostic_heal,
    manager_ingest,
    persist_run,
    planner_plan,
    programmer_apply,
    reviewer_review,
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
        if run.work_dir is None:
            sandbox = manager.create(Path(run.repo_path), run_id=run.run_id)
            run.work_dir = str(sandbox.work_dir)
        run = manager_ingest(run)
        return _dump(run)

    def node_planner(data: FactoryState) -> FactoryState:
        run, sandbox = _load(data)
        assert sandbox is not None
        run = planner_plan(run, sandbox, settings)
        return _dump(run)

    def node_approve(data: FactoryState) -> FactoryState:
        run, _ = _load(data)
        assert run.plan is not None

        if run.auto_approve or run.plan.approved:
            run = approve_plan(run, {"approved": True})
            return _dump(run)

        # Pause for human decision; resume value is the decision dict.
        decision = interrupt(
            {
                "type": "plan_approval",
                "run_id": run.run_id,
                "summary": run.plan.summary,
                "steps": [s.model_dump() for s in run.plan.steps],
                "risks": run.plan.risks,
                "test_command": run.plan.test_command,
            }
        )
        if not isinstance(decision, dict):
            decision = {"approved": bool(decision)}
        run = approve_plan(run, decision)
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

    def node_reviewer(data: FactoryState) -> FactoryState:
        run, sandbox = _load(data)
        assert sandbox is not None
        run = reviewer_review(run, sandbox, settings)
        return _dump(run)

    def route_after_approve(data: FactoryState) -> str:
        run = RunState.model_validate(data["run"])
        if run.status == RunStatus.ABORTED:
            return "done"
        return "code"

    def route_after_programmer(data: FactoryState) -> str:
        run = RunState.model_validate(data["run"])
        if run.status == RunStatus.REVIEWING:
            return "review"
        if run.status in {RunStatus.HEALING, RunStatus.TESTING, RunStatus.CODING}:
            return "heal"
        if run.status == RunStatus.SUCCEEDED:
            return "done"
        return "done"

    def route_after_heal(data: FactoryState) -> str:
        run = RunState.model_validate(data["run"])
        if run.status == RunStatus.REVIEWING:
            return "review"
        if run.status == RunStatus.FAILED:
            return "done"
        if len(run.heal_attempts) >= settings.max_heal_attempts:
            run.status = RunStatus.FAILED
            run.error = "Heal attempts exhausted"
            data["run"] = run.model_dump(mode="json")
            persist_run(run, settings.runs_dir)
            return "done"
        if run.status == RunStatus.HEALING and run.test_results and not run.test_results[-1].passed:
            return "heal"
        return "done"

    def route_after_review(data: FactoryState) -> str:
        run = RunState.model_validate(data["run"])
        if run.status == RunStatus.SUCCEEDED:
            return "done"
        if run.status == RunStatus.FAILED or run.status == RunStatus.ABORTED:
            return "done"
        if run.status == RunStatus.CODING:
            return "code"
        return "done"

    graph = StateGraph(FactoryState)
    graph.add_node("manager", node_manager)
    graph.add_node("planner", node_planner)
    graph.add_node("approve", node_approve)
    graph.add_node("programmer", node_programmer)
    graph.add_node("diagnostic", node_diagnostic)
    graph.add_node("reviewer", node_reviewer)

    graph.set_entry_point("manager")
    graph.add_edge("manager", "planner")
    graph.add_edge("planner", "approve")
    graph.add_conditional_edges(
        "approve",
        route_after_approve,
        {"code": "programmer", "done": END},
    )
    graph.add_conditional_edges(
        "programmer",
        route_after_programmer,
        {"heal": "diagnostic", "review": "reviewer", "done": END},
    )
    graph.add_conditional_edges(
        "diagnostic",
        route_after_heal,
        {"heal": "diagnostic", "review": "reviewer", "done": END},
    )
    graph.add_conditional_edges(
        "reviewer",
        route_after_review,
        {"code": "programmer", "done": END},
    )

    checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)


def run_factory(
    ticket: Ticket,
    repo_path: Path,
    settings: Settings | None = None,
    auto_approve: bool = True,
    approval_decision: dict[str, Any] | None = None,
    interactive: bool = False,
) -> RunState:
    """Execute the factory graph.

    When ``auto_approve`` is False, the graph interrupts after planning.
    Pass ``approval_decision`` to resume non-interactively, or set
    ``interactive=True`` to prompt on stdin.
    """
    settings = settings or get_settings()
    settings.runs_dir.mkdir(parents=True, exist_ok=True)

    initial = RunState(
        ticket=ticket,
        repo_path=str(repo_path.resolve()),
        status=RunStatus.PENDING,
        auto_approve=auto_approve,
    )
    if auto_approve:
        initial.note("Local mode: plan auto-approved")

    app = build_factory_graph(settings)
    thread = {"configurable": {"thread_id": initial.run_id}}
    payload: FactoryState = {"run": initial.model_dump(mode="json")}

    result = app.invoke(payload, config=thread)

    # HITL interrupt path
    interrupted = _interrupt_payload(result)
    if interrupted is not None:
        decision = approval_decision
        if decision is None and interactive:
            decision = _prompt_plan_approval(interrupted)
        if decision is None:
            # Persist awaiting state and return without coding
            run = RunState.model_validate(result.get("run") or payload["run"])
            run.status = RunStatus.AWAITING_APPROVAL
            run.note("Paused for plan approval (no decision provided)")
            persist_run(run, settings.runs_dir)
            return run

        result = app.invoke(Command(resume=decision), config=thread)

    final = RunState.model_validate(result["run"])
    persist_run(final, settings.runs_dir)
    return final


def _interrupt_payload(result: Any) -> dict[str, Any] | None:
    if not isinstance(result, dict):
        return None
    # LangGraph may surface interrupts via __interrupt__
    interrupts = result.get("__interrupt__")
    if interrupts:
        first = interrupts[0]
        value = getattr(first, "value", first)
        if isinstance(value, dict):
            return value
    return None


def _prompt_plan_approval(plan_payload: dict[str, Any]) -> dict[str, Any]:
    print("\n=== Plan approval required ===")
    print(f"Summary: {plan_payload.get('summary')}")
    steps = plan_payload.get("steps") or []
    for idx, step in enumerate(steps, 1):
        files = ", ".join(step.get("target_files") or []) or "(none)"
        print(f"  {idx}. {step.get('description')} [{files}]")
    risks = plan_payload.get("risks") or []
    if risks:
        print("Risks:")
        for risk in risks:
            print(f"  - {risk}")
    print(f"Test command: {plan_payload.get('test_command')}")
    answer = input("Approve plan? [y/N]: ").strip().lower()
    feedback = input("Optional feedback: ").strip()
    return {"approved": answer in {"y", "yes"}, "feedback": feedback}
