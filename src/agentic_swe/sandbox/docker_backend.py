"""Hardened Docker sandbox backend for isolated command execution.

Copies the target repository into a local ``work_dir`` (so code-intel, diffs,
and observability work identically to ``LocalSandbox``) and executes every
shell/test command inside an ephemeral container with strict isolation flags:
- ``--rm`` (no leftover containers)
- ``--network=none`` by default (blocks exfiltration / arbitrary egress)
- ``--cap-drop=ALL`` and ``--security-opt=no-new-privileges:true``
- ``--read-only`` rootfs with bounded ``--tmpfs /tmp``
- ``--cpus``, ``--memory``, and ``--pids-limit`` resource caps
- Deterministic ``CommandPolicy`` check prior to container invocation
"""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from agentic_swe.config import Settings

from .local import LocalSandbox
from .policy import CommandPolicy
from .protocol import SandboxError


class DockerSandbox:
    """Container-isolated sandbox backed by a local workspace bind-mount."""

    def __init__(
        self,
        work_dir: Path,
        settings: Settings,
        policy: CommandPolicy | None = None,
    ) -> None:
        self.work_dir = work_dir.resolve()
        self.settings = settings
        self.timeout_sec = settings.command_timeout_sec
        self.policy = policy or CommandPolicy.from_mode(
            settings.command_policy_mode,
            extra_allowlist=settings.command_allowlist,
        )
        self._local = LocalSandbox(
            work_dir=self.work_dir,
            timeout_sec=self.timeout_sec,
            policy=self.policy,
        )

    @classmethod
    def from_repo(
        cls,
        source_repo: Path,
        work_dir: Path,
        settings: Settings,
    ) -> DockerSandbox:
        if not docker_available():
            raise SandboxError(
                "Docker backend selected but the 'docker' CLI was not found on PATH. "
                "Install Docker or set AGENTIC_SWE_SANDBOX_BACKEND=local."
            )

        source = source_repo.resolve()
        if not source.is_dir():
            raise SandboxError(f"Source repo not found: {source}")
        if work_dir.exists():
            shutil.rmtree(work_dir)
        shutil.copytree(
            source,
            work_dir,
            ignore=shutil.ignore_patterns(
                ".git",
                ".venv",
                "venv",
                "__pycache__",
                ".pytest_cache",
                "node_modules",
                "*.egg-info",
            ),
        )
        return cls(work_dir=work_dir, settings=settings)

    def read_file(self, relative: str) -> str:
        return self._local.read_file(relative)

    def write_file(self, relative: str, content: str) -> None:
        self._local.write_file(relative, content)

    def delete_file(self, relative: str) -> None:
        self._local.delete_file(relative)

    def list_files(self, pattern: str = "**/*") -> list[str]:
        return self._local.list_files(pattern)

    def build_docker_command(self, command: str | list[str]) -> list[str]:
        """Construct the hardened ``docker run`` invocation for ``command``."""
        self.policy.check(command)

        if isinstance(command, list):
            inner_cmd = command
        else:
            inner_cmd = ["sh", "-lc", command]

        mount_src = str(self.work_dir)
        args = [
            "docker",
            "run",
            "--rm",
            f"--network={self.settings.docker_network_mode}",
            f"--cpus={self.settings.docker_cpus}",
            f"--memory={self.settings.docker_memory}",
            f"--pids-limit={self.settings.docker_pids_limit}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=128m",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "HOME=/tmp",
            "-v",
            f"{mount_src}:/workspace:rw",
            "-w",
            "/workspace",
            self.settings.docker_image,
            *inner_cmd,
        ]
        return args

    def run(
        self,
        command: str | list[str],
        timeout_sec: int | None = None,
    ) -> tuple[int, str, str, float]:
        docker_cmd = self.build_docker_command(command)
        timeout = timeout_sec or self.timeout_sec
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                docker_cmd,
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            raise SandboxError(
                "Docker CLI executable not found while running sandbox command."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            duration = time.perf_counter() - started
            stdout = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, str) else "command timed out"
            return 124, stdout, stderr, duration
        duration = time.perf_counter() - started
        return proc.returncode, proc.stdout or "", proc.stderr or "", duration

    def run_tests(self, command: str = "pytest -q") -> tuple[int, str, str, float]:
        return self.run(command)

    def destroy(self) -> None:
        self._local.destroy()


def docker_available() -> bool:
    """Return True if the ``docker`` binary is available on PATH."""
    return shutil.which("docker") is not None
