from __future__ import annotations

from pathlib import Path

from agentic_swe.config import Settings

from .local import LocalSandbox, SandboxError
from .protocol import Sandbox


def create_sandbox(
    *,
    source_repo: Path,
    work_dir: Path,
    settings: Settings,
) -> Sandbox:
    """Create a sandbox for ``source_repo`` using the configured backend."""
    backend = (settings.sandbox_backend or "local").lower().strip()
    if backend == "local":
        return LocalSandbox.from_repo(
            source_repo=source_repo,
            work_dir=work_dir,
            timeout_sec=settings.command_timeout_sec,
        )
    if backend == "e2b":
        from .e2b_backend import E2BSandbox

        return E2BSandbox.from_repo(
            source_repo=source_repo,
            work_dir=work_dir,
            settings=settings,
        )
    raise SandboxError(
        f"Unknown sandbox backend '{backend}'. Supported: local, e2b"
    )
