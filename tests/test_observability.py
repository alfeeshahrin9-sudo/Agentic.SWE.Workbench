from pathlib import Path

from agentic_swe.config import Settings
from agentic_swe.models import Ticket
from agentic_swe.observability import changed_files, list_runs, load_run
from agentic_swe.orchestrator import run_factory

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_repo"


def test_list_and_load_runs(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs")
    ticket = Ticket(title="fix add", description="fix add so that 2+2 equals 4")
    result = run_factory(ticket=ticket, repo_path=FIXTURE, settings=settings)
    rows = list_runs(settings=settings)
    assert any(r.run_id == result.run_id for r in rows)
    loaded = load_run(result.run_id, settings=settings)
    assert loaded.status == result.status
    assert changed_files(loaded)
