from __future__ import annotations

from pathlib import Path

from agentic_swe.config import Settings, get_settings
from agentic_swe.models import new_id

from .local import LocalSandbox


class SandboxManager:
    """Creates and tracks per-run local sandboxes."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.settings.runs_dir.mkdir(parents=True, exist_ok=True)
        self._sandboxes: dict[str, LocalSandbox] = {}

    def create(self, source_repo: Path, run_id: str | None = None) -> LocalSandbox:
        rid = run_id or new_id("run")
        work_dir = self.settings.runs_dir / rid / "workspace"
        sandbox = LocalSandbox.from_repo(
            source_repo=source_repo,
            work_dir=work_dir,
            timeout_sec=self.settings.command_timeout_sec,
        )
        self._sandboxes[rid] = sandbox
        return sandbox

    def get(self, run_id: str) -> LocalSandbox | None:
        return self._sandboxes.get(run_id)

    def destroy(self, run_id: str) -> None:
        sandbox = self._sandboxes.pop(run_id, None)
        if sandbox:
            sandbox.destroy()
