"""Optional E2B cloud sandbox adapter.

Requires ``pip install -e ".[e2b]"`` and ``E2B_API_KEY``. The local work_dir
mirrors files for code-intel / persistence while commands execute remotely.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from agentic_swe.config import Settings

from .local import LocalSandbox, SandboxError


class E2BSandbox:
    """Cloud execution backend with a local mirror for indexing and diffs."""

    def __init__(
        self,
        work_dir: Path,
        settings: Settings,
        sandbox: object,
    ) -> None:
        self.work_dir = work_dir.resolve()
        self.settings = settings
        self.timeout_sec = settings.command_timeout_sec
        self._sandbox = sandbox
        self._local = LocalSandbox(work_dir=self.work_dir, timeout_sec=self.timeout_sec)

    @classmethod
    def from_repo(
        cls,
        source_repo: Path,
        work_dir: Path,
        settings: Settings,
    ) -> E2BSandbox:
        if not settings.e2b_api_key:
            raise SandboxError(
                "E2B backend selected but E2B_API_KEY is not set. "
                "Use AGENTIC_SWE_SANDBOX_BACKEND=local or set the key."
            )
        try:
            from e2b import Sandbox as E2B
        except ImportError as exc:
            raise SandboxError(
                "E2B backend requires the e2b package. Install with: pip install -e '.[e2b]'"
            ) from exc

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

        remote = E2B.create(api_key=settings.e2b_api_key, timeout=settings.command_timeout_sec)
        instance = cls(work_dir=work_dir, settings=settings, sandbox=remote)
        instance._sync_to_remote()
        return instance

    @property
    def read_file(self):
        return self._local.read_file

    @property
    def write_file(self):
        def _write(relative: str, content: str) -> None:
            self._local.write_file(relative, content)
            # Best-effort remote mirror
            try:
                remote_path = f"/home/user/workspace/{relative}"
                self._sandbox.files.write(remote_path, content)  # type: ignore[attr-defined]
            except Exception:
                pass

        return _write

    @property
    def delete_file(self):
        return self._local.delete_file

    @property
    def list_files(self):
        return self._local.list_files

    def _sync_to_remote(self) -> None:
        for rel in self._local.list_files("**/*"):
            content = self._local.read_file(rel)
            remote_path = f"/home/user/workspace/{rel}"
            try:
                self._sandbox.files.write(remote_path, content)  # type: ignore[attr-defined]
            except Exception as exc:
                raise SandboxError(f"Failed to sync {rel} to E2B: {exc}") from exc

    def run(
        self,
        command: str | list[str],
        timeout_sec: int | None = None,
    ) -> tuple[int, str, str, float]:
        timeout = timeout_sec or self.timeout_sec
        if isinstance(command, list):
            cmd = " ".join(command)
        else:
            cmd = command
        started = time.perf_counter()
        try:
            result = self._sandbox.commands.run(  # type: ignore[attr-defined]
                f"cd /home/user/workspace && {cmd}",
                timeout=timeout,
            )
            duration = time.perf_counter() - started
            exit_code = int(getattr(result, "exit_code", 1))
            stdout = str(getattr(result, "stdout", "") or "")
            stderr = str(getattr(result, "stderr", "") or "")
            return exit_code, stdout, stderr, duration
        except Exception as exc:
            duration = time.perf_counter() - started
            return 1, "", str(exc), duration

    def run_tests(self, command: str = "pytest -q") -> tuple[int, str, str, float]:
        return self.run(command)

    def destroy(self) -> None:
        try:
            kill = getattr(self._sandbox, "kill", None)
            if callable(kill):
                kill()
        except Exception:
            pass
        self._local.destroy()
