from __future__ import annotations

from pathlib import Path

from agentic_swe.config import Settings, get_settings
from agentic_swe.models import new_id

from .factory import create_sandbox
from .protocol import Sandbox


class SandboxManager:
    """Creates and tracks per-run sandboxes via the configured backend."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.runs_dir.mkdir(parents=True, exist_ok=True)
        self._sandboxes: dict[str, Sandbox] = {}

    def create(self, source_repo: Path, run_id: str | None = None) -> Sandbox:
        rid = run_id or new_id("run")
        work_dir = self.settings.runs_dir / rid / "workspace"
        sandbox = create_sandbox(
            source_repo=source_repo,
            work_dir=work_dir,
            settings=self.settings,
        )
        self._sandboxes[rid] = sandbox
        return sandbox

    def get(self, run_id: str) -> Sandbox | None:
        return self._sandboxes.get(run_id)

    def destroy(self, run_id: str) -> None:
        sandbox = self._sandboxes.pop(run_id, None)
        if sandbox:
            sandbox.destroy()
