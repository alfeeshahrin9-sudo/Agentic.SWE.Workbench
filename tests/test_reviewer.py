from pathlib import Path

from agentic_swe.config import Settings
from agentic_swe.models import EditPlan, FilePatch, PlanStep, RunState, RunStatus, Ticket
from agentic_swe.orchestrator.agents import reviewer_review
from agentic_swe.sandbox import LocalSandbox

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_repo"


def test_heuristic_reviewer_approves_green_run(tmp_path: Path):
    work = tmp_path / "ws"
    sandbox = LocalSandbox.from_repo(FIXTURE, work)
    sandbox.write_file(
        "src/calculator.py",
        '"""Calculator utilities."""\n\ndef add(a: int, b: int) -> int:\n    return a + b\n',
    )
    from agentic_swe.models import TestResult

    state = RunState(
        ticket=Ticket(title="fix add", description="fix add"),
        repo_path=str(FIXTURE),
        work_dir=str(work),
        status=RunStatus.REVIEWING,
        plan=EditPlan(
            summary="fix add",
            steps=[PlanStep(description="fix", target_files=["src/calculator.py"])],
            approved=True,
        ),
        patches=[
            FilePatch(
                path="src/calculator.py",
                content='def add(a: int, b: int) -> int:\n    return a + b\n',
            )
        ],
        test_results=[
            TestResult(command="pytest -q", exit_code=0, stdout="ok", passed=True)
        ],
    )
    settings = Settings(runs_dir=tmp_path / "runs")
    out = reviewer_review(state, sandbox, settings)
    assert out.status == RunStatus.SUCCEEDED
    assert out.reviews[-1].approved
