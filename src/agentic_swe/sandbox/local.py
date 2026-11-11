from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path


class SandboxError(RuntimeError):
    pass


class LocalSandbox:
    """Isolated worktree under a run directory. Commands are cwd-bound to work_dir."""

    def __init__(self, work_dir: Path, timeout_sec: int = 120) -> None:
        self.work_dir = work_dir.resolve()
        self.timeout_sec = timeout_sec
        self.work_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_repo(
        cls,
        source_repo: Path,
        work_dir: Path,
        timeout_sec: int = 120,
    ) -> LocalSandbox:
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
                "*.egg-info",
            ),
        )
        return cls(work_dir=work_dir, timeout_sec=timeout_sec)

    def resolve(self, relative: str) -> Path:
        target = (self.work_dir / relative).resolve()
        if not str(target).startswith(str(self.work_dir)):
            raise SandboxError(f"Path escapes sandbox: {relative}")
        return target

    def read_file(self, relative: str) -> str:
        path = self.resolve(relative)
        if not path.is_file():
            raise SandboxError(f"File not found: {relative}")
        return path.read_text(encoding="utf-8")

    def write_file(self, relative: str, content: str) -> None:
        path = self.resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def delete_file(self, relative: str) -> None:
        path = self.resolve(relative)
        if path.is_file():
            path.unlink()

    def list_files(self, pattern: str = "**/*") -> list[str]:
        files: list[str] = []
        for path in self.work_dir.glob(pattern):
            if path.is_file():
                files.append(str(path.relative_to(self.work_dir)))
        return sorted(files)

    def run(
        self,
        command: str | list[str],
        timeout_sec: int | None = None,
    ) -> tuple[int, str, str, float]:
        timeout = timeout_sec or self.timeout_sec
        cmd = command if isinstance(command, list) else ["bash", "-lc", command]
        started = time.perf_counter()
        try:
            proc = subprocess.run(
                cmd,
                cwd=self.work_dir,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
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
        if self.work_dir.exists():
            shutil.rmtree(self.work_dir)
