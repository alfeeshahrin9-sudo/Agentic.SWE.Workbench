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
    # Original fixture must remain broken
    original = (FIXTURE / "src" / "calculator.py").read_text(encoding="utf-8")
    assert "a - b" in original
