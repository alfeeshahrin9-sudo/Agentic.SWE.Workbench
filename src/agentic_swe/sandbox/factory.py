from __future__ import annotations

from pathlib import Path

from agentic_swe.config import Settings

from .local import LocalSandbox
from .policy import CommandPolicy
from .protocol import Sandbox, SandboxError


def create_sandbox(
    *,
    source_repo: Path,
    work_dir: Path,
    settings: Settings,
) -> Sandbox:
    """Create a sandbox for ``source_repo`` using the configured backend."""
    backend = (settings.sandbox_backend or "local").lower().strip()
    policy = CommandPolicy.from_mode(
        settings.command_policy_mode,
        extra_allowlist=settings.command_allowlist,
    )
    if backend == "local":
        return LocalSandbox.from_repo(
            source_repo=source_repo,
            work_dir=work_dir,
            timeout_sec=settings.command_timeout_sec,
            policy=policy,
        )
    if backend == "docker":
        from .docker_backend import DockerSandbox

        return DockerSandbox.from_repo(
            source_repo=source_repo,
            work_dir=work_dir,
            settings=settings,
        )
    if backend == "e2b":
        from .e2b_backend import E2BSandbox

        return E2BSandbox.from_repo(
            source_repo=source_repo,
            work_dir=work_dir,
            settings=settings,
        )
    raise SandboxError(
        f"Unknown sandbox backend '{backend}'. Supported: local, docker, e2b"
    )
