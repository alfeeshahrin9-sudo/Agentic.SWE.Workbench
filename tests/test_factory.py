from pathlib import Path

from agentic_swe.config import Settings
from agentic_swe.models import RunStatus, Ticket
from agentic_swe.orchestrator import run_factory

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_repo"


def test_factory_heals_fixture(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs", max_heal_attempts=3)
    ticket = Ticket(
        title="fix add",
        description="fix add so that 2+2 equals 4",
    )
    result = run_factory(ticket=ticket, repo_path=FIXTURE, settings=settings)
    assert result.status == RunStatus.SUCCEEDED
    assert result.test_results
    assert result.test_results[-1].passed
    assert result.reviews
    assert result.reviews[-1].approved
    # Original fixture must remain broken
    original = (FIXTURE / "src" / "calculator.py").read_text(encoding="utf-8")
    assert "a - b" in original


def test_factory_pauses_for_plan_approval(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs")
    ticket = Ticket(title="fix add", description="fix add so that 2+2 equals 4")
    result = run_factory(
        ticket=ticket,
        repo_path=FIXTURE,
        settings=settings,
        auto_approve=False,
    )
    assert result.status == RunStatus.AWAITING_APPROVAL
    assert result.plan is not None
    assert result.plan.approved is False


def test_factory_resumes_with_approval_decision(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs")
    ticket = Ticket(title="fix add", description="fix add so that 2+2 equals 4")
    result = run_factory(
        ticket=ticket,
        repo_path=FIXTURE,
        settings=settings,
        auto_approve=False,
        approval_decision={"approved": True, "feedback": "ship it"},
    )
    assert result.status == RunStatus.SUCCEEDED
    assert any("approved" in m.lower() for m in result.messages)


def test_factory_rejects_plan(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs")
    ticket = Ticket(title="fix add", description="fix add so that 2+2 equals 4")
    result = run_factory(
        ticket=ticket,
        repo_path=FIXTURE,
        settings=settings,
        auto_approve=False,
        approval_decision={"approved": False, "feedback": "too risky"},
    )
    assert result.status == RunStatus.ABORTED
    assert result.error and "too risky" in result.error
