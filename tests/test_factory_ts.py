from pathlib import Path

from agentic_swe.config import Settings
from agentic_swe.models import RunStatus, Ticket
from agentic_swe.orchestrator import run_factory

TS_FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_ts"


def test_factory_heals_ts_fixture(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs", max_heal_attempts=3)
    ticket = Ticket(
        title="fix add",
        description="fix add so that 2+2 equals 4",
    )
    result = run_factory(ticket=ticket, repo_path=TS_FIXTURE, settings=settings)
    assert result.status == RunStatus.SUCCEEDED
    assert result.plan is not None
    assert result.plan.test_command == "npm test"
    assert result.test_results[-1].passed
    original = (TS_FIXTURE / "src" / "calculator.js").read_text(encoding="utf-8")
    assert "a - b" in original
