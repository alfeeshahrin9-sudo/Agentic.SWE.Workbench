from __future__ import annotations

"""MCP tool surface over LocalSandbox (MCP Python SDK v2).

Run with: `agentic-swe mcp` (stdio transport).
"""

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from agentic_swe.config import get_settings
from agentic_swe.sandbox.manager import SandboxManager

mcp = MCPServer("agentic-swe-sandbox")
_manager = SandboxManager(get_settings())
_active_run_id: str | None = None


def _require_sandbox():
    if not _active_run_id:
        raise RuntimeError("No active sandbox. Call sandbox_create first.")
    sandbox = _manager.get(_active_run_id)
    if sandbox is None:
        raise RuntimeError(f"Sandbox {_active_run_id} not found.")
    return sandbox


@mcp.tool()
def sandbox_create(repo_path: str, run_id: str | None = None) -> dict[str, Any]:
    """Create an isolated local sandbox by copying a source repository."""
    global _active_run_id
    from agentic_swe.models import new_id

    rid = run_id or new_id("run")
    sandbox = _manager.create(Path(repo_path), run_id=rid)
    _active_run_id = rid
    return {"run_id": rid, "work_dir": str(sandbox.work_dir)}


@mcp.tool()
def sandbox_list_files(pattern: str = "**/*") -> list[str]:
    """List files inside the active sandbox."""
    return _require_sandbox().list_files(pattern)


@mcp.tool()
def sandbox_read_file(path: str) -> str:
    """Read a file from the active sandbox."""
    return _require_sandbox().read_file(path)


@mcp.tool()
def sandbox_write_file(path: str, content: str) -> dict[str, str]:
    """Write a file inside the active sandbox."""
    _require_sandbox().write_file(path, content)
    return {"status": "ok", "path": path}


@mcp.tool()
def sandbox_run(command: str) -> dict[str, Any]:
    """Run a shell command inside the active sandbox."""
    code, stdout, stderr, duration = _require_sandbox().run(command)
    return {
        "exit_code": code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_sec": duration,
    }


@mcp.tool()
def sandbox_run_tests(command: str = "pytest -q") -> dict[str, Any]:
    """Run tests inside the active sandbox."""
    code, stdout, stderr, duration = _require_sandbox().run_tests(command)
    return {
        "exit_code": code,
        "stdout": stdout,
        "stderr": stderr,
        "duration_sec": duration,
        "passed": code == 0,
    }


@mcp.tool()
def sandbox_destroy() -> dict[str, str]:
    """Destroy the active sandbox worktree."""
    global _active_run_id
    if _active_run_id:
        _manager.destroy(_active_run_id)
        _active_run_id = None
    return {"status": "destroyed"}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
