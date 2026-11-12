from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agentic_swe.config import Settings, get_settings
from agentic_swe.models import RunState


@dataclass
class RunSummary:
    run_id: str
    status: str
    title: str
    work_dir: str | None
    heal_attempts: int
    reviews: int
    path: Path


def list_runs(settings: Settings | None = None, limit: int = 50) -> list[RunSummary]:
    settings = settings or get_settings()
    runs_dir = settings.runs_dir
    if not runs_dir.exists():
        return []

    summaries: list[RunSummary] = []
    for state_path in sorted(runs_dir.glob("*/state.json"), reverse=True):
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            run = RunState.model_validate(data)
        except Exception:
            continue
        summaries.append(
            RunSummary(
                run_id=run.run_id,
                status=run.status.value,
                title=run.ticket.title,
                work_dir=run.work_dir,
                heal_attempts=len(run.heal_attempts),
                reviews=len(run.reviews),
                path=state_path,
            )
        )
        if len(summaries) >= limit:
            break
    return summaries


def load_run(run_id: str, settings: Settings | None = None) -> RunState:
    settings = settings or get_settings()
    path = settings.runs_dir / run_id / "state.json"
    if not path.is_file():
        raise FileNotFoundError(f"No run state for {run_id} at {path}")
    return RunState.model_validate_json(path.read_text(encoding="utf-8"))


def changed_files(run: RunState) -> list[str]:
    return sorted({patch.path for patch in run.patches})
