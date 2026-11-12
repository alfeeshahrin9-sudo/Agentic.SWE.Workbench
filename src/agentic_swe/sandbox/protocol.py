from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class Sandbox(Protocol):
    """Pluggable isolated execution environment."""

    work_dir: Path

    def read_file(self, relative: str) -> str: ...

    def write_file(self, relative: str, content: str) -> None: ...

    def delete_file(self, relative: str) -> None: ...

    def list_files(self, pattern: str = "**/*") -> list[str]: ...

    def run(
        self,
        command: str | list[str],
        timeout_sec: int | None = None,
    ) -> tuple[int, str, str, float]: ...

    def run_tests(self, command: str = "pytest -q") -> tuple[int, str, str, float]: ...

    def destroy(self) -> None: ...
