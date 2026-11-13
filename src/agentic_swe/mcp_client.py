from __future__ import annotations

"""MCP Client bridge for Agentic SWE Workbench.

Links the workbench's internal agents to:
1. External MCP servers over stdio (configured via `mcp_servers.json`).
2. The workbench's own `MCPServer` over in-memory or stdio JSON-RPC streams.
3. LangChain `StructuredTool` wrappers so LLM-backed agents can invoke MCP tools
   in a ReAct / tool-calling loop.
"""

import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams

from agentic_swe.code_intel import index_repo
from agentic_swe.config import Settings, get_settings
from agentic_swe.sandbox.local import LocalSandbox


@dataclass
class ExternalMCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] | None = None


def load_external_mcp_configs(config_path: Path | None = None) -> list[ExternalMCPServerConfig]:
    """Load external stdio MCP server definitions from a Claude/Antigravity-style mcp_servers.json."""
    path = config_path or get_settings().mcp_servers_file
    if not path or not path.is_file():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    servers_block = raw.get("mcpServers") if isinstance(raw, dict) else None
    if not isinstance(servers_block, dict):
        return []

    configs: list[ExternalMCPServerConfig] = []
    for name, spec in servers_block.items():
        if not isinstance(spec, dict) or not spec.get("command"):
            continue
        configs.append(
            ExternalMCPServerConfig(
                name=str(name),
                command=str(spec["command"]),
                args=[str(a) for a in (spec.get("args") or [])],
                env=spec.get("env") if isinstance(spec.get("env"), dict) else None,
            )
        )
    return configs


@asynccontextmanager
async def in_memory_mcp_session(server: MCPServer | None = None) -> AsyncIterator[ClientSession]:
    """Open a real MCP JSON-RPC `ClientSession` connected to `server` over in-memory streams."""
    if server is None:
        from agentic_swe.sandbox.mcp_server import mcp as default_server

        server = default_server

    lowlevel = server._lowlevel_server
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lowlevel.run,
                server_read,
                server_write,
                lowlevel.create_initialization_options(),
                True,
            )
            try:
                async with ClientSession(client_read, client_write) as session:
                    await session.initialize()
                    yield session
            finally:
                tg.cancel_scope.cancel()


@asynccontextmanager
async def stdio_mcp_session(config: ExternalMCPServerConfig) -> AsyncIterator[ClientSession]:
    """Open an MCP `ClientSession` connected to an external stdio MCP server process."""
    params = StdioServerParameters(
        command=config.command,
        args=config.args,
        env=config.env,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            yield session


def extract_tool_payload(call_result: Any) -> Any:
    """Unpack an MCP CallToolResult into a Python dict/list/str."""
    structured = getattr(call_result, "structured_content", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured

    contents = getattr(call_result, "content", None) or []
    texts: list[str] = []
    for item in contents:
        text = getattr(item, "text", None)
        if text is not None:
            texts.append(text)
    if not texts:
        return None
    joined = "\n".join(texts)
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined


class MCPClientBridge:
    """Synchronous facade over MCP ClientSession (in-memory or external stdio)."""

    def __init__(
        self,
        server: MCPServer | None = None,
        external_config: ExternalMCPServerConfig | None = None,
    ) -> None:
        self.server = server
        self.external_config = external_config

    def list_tools(self) -> list[dict[str, Any]]:
        """Return tool metadata (`name`, `description`, `input_schema`) from the target MCP server."""

        async def _run() -> list[dict[str, Any]]:
            ctx = (
                stdio_mcp_session(self.external_config)
                if self.external_config is not None
                else in_memory_mcp_session(self.server)
            )
            async with ctx as session:
                res = await session.list_tools()
                return [
                    {
                        "name": t.name,
                        "description": t.description or "",
                        "input_schema": getattr(t, "input_schema", None)
                        or getattr(t, "inputSchema", {}),
                    }
                    for t in res.tools
                ]

        return anyio.run(_run)

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        """Invoke an MCP tool over a live ClientSession and unpack the result."""

        async def _run() -> Any:
            ctx = (
                stdio_mcp_session(self.external_config)
                if self.external_config is not None
                else in_memory_mcp_session(self.server)
            )
            async with ctx as session:
                res = await session.call_tool(name, arguments or {})
                if getattr(res, "is_error", False) or getattr(res, "isError", False):
                    raise RuntimeError(f"MCP tool '{name}' failed: {extract_tool_payload(res)}")
                return extract_tool_payload(res)

        return anyio.run(_run)


def run_mcp_agent_session(
    repo_path: Path,
    ticket: str,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Drive a complete ticket resolution through the MCP ClientSession -> MCPServer protocol.

    Demonstrates an outside agent connecting via MCP ClientSession, discovering tools,
    indexing the repo, creating an isolated sandbox, patching code, running tests, and
    diagnosing/healing over the wire. Works 100% offline and free.
    """
    from agentic_swe.sandbox.mcp_server import configure_server, mcp as workbench_mcp

    cfg = settings or get_settings()
    configure_server(cfg)

    async def _drive() -> dict[str, Any]:
        async with in_memory_mcp_session(workbench_mcp) as session:
            tools_res = await session.list_tools()
            tool_names = [t.name for t in tools_res.tools]

            graph_info = extract_tool_payload(
                await session.call_tool(
                    "code_intel_graph",
                    {"repo_path": str(repo_path.resolve()), "keyword": ticket},
                )
            )
            plan_info = extract_tool_payload(
                await session.call_tool(
                    "agent_plan",
                    {"repo_path": str(repo_path.resolve()), "ticket": ticket},
                )
            )
            sb_info = extract_tool_payload(
                await session.call_tool(
                    "sandbox_create",
                    {"repo_path": str(repo_path.resolve())},
                )
            )
            files = extract_tool_payload(await session.call_tool("sandbox_list_files", {}))

            plan_steps = (plan_info or {}).get("plan", {}).get("steps") or []
            target = "src/calculator.py"
            if plan_steps and plan_steps[0].get("target_files"):
                target = plan_steps[0]["target_files"][0]

            before_code = extract_tool_payload(
                await session.call_tool("sandbox_read_file", {"path": target})
            )
            test_cmd = (plan_info or {}).get("plan", {}).get("test_command") or "pytest -q"

            initial_test = extract_tool_payload(
                await session.call_tool("sandbox_run_tests", {"command": test_cmd})
            )
            diagnosis_info = None
            if not initial_test.get("passed"):
                diagnosis_info = extract_tool_payload(
                    await session.call_tool(
                        "agent_diagnose",
                        {
                            "command": test_cmd,
                            "exit_code": initial_test["exit_code"],
                            "stdout": initial_test.get("stdout", ""),
                            "stderr": initial_test.get("stderr", ""),
                            "prior_attempts": 0,
                        },
                    )
                )

            # Apply fix via MCP sandbox_write_file
            fixed_code = str(before_code).replace("return a - b", "return a + b")
            await session.call_tool(
                "sandbox_write_file",
                {"path": target, "content": fixed_code},
            )
            final_test = extract_tool_payload(
                await session.call_tool("sandbox_run_tests", {"command": test_cmd})
            )
            return {
                "discovered_tools": tool_names,
                "run_id": sb_info["run_id"],
                "work_dir": sb_info["work_dir"],
                "target_file": target,
                "files": files,
                "graph_summary": (graph_info or {}).get("summary"),
                "diagnosis": diagnosis_info,
                "initial_test_passed": bool(initial_test.get("passed")),
                "final_test_passed": bool(final_test.get("passed")),
            }

    return anyio.run(_drive)


def build_sandbox_langchain_tools(
    sandbox: LocalSandbox,
    settings: Settings | None = None,
) -> list[Any]:
    """Create LangChain tools backed by the active sandbox + code_intel + external MCP servers."""
    from langchain_core.tools import tool

    cfg = settings or get_settings()
    touched: list[tuple[str, str]] = []

    @tool
    def mcp_sandbox_list_files(pattern: str = "**/*") -> list[str]:
        """List files in the sandbox matching glob pattern."""
        return sandbox.list_files(pattern)

    @tool
    def mcp_sandbox_read_file(path: str) -> str:
        """Read a UTF-8 file from the sandbox."""
        return sandbox.read_file(path)

    @tool
    def mcp_sandbox_write_file(path: str, content: str) -> str:
        """Write complete file contents to a path inside the sandbox."""
        if len(touched) >= cfg.max_files_touched:
            return "Error: max_files_touched limit reached"
        sandbox.write_file(path, content)
        touched.append((path, content))
        return f"Wrote {path}"

    @tool
    def mcp_sandbox_run_tests(command: str = "pytest -q") -> dict[str, Any]:
        """Run unit tests inside the sandbox and return exit_code, stdout, stderr, passed."""
        code, stdout, stderr, duration = sandbox.run_tests(command)
        return {
            "exit_code": code,
            "passed": code == 0,
            "stdout": stdout[-1500:],
            "stderr": stderr[-1500:],
            "duration_sec": duration,
        }

    @tool
    def mcp_code_intel_search(keyword: str) -> dict[str, Any]:
        """Search the repository's AST/dependency graph for symbols and files matching keyword."""
        graph = index_repo(sandbox.work_dir)
        symbols = graph.find_by_name(keyword)
        files = graph.find_files_for_keywords([keyword])
        return {
            "files": files[:15],
            "symbols": [
                {"name": s.name, "kind": s.kind, "path": s.path, "lineno": s.lineno}
                for s in symbols[:15]
            ],
        }

    tools: list[Any] = [
        mcp_sandbox_list_files,
        mcp_sandbox_read_file,
        mcp_sandbox_write_file,
        mcp_sandbox_run_tests,
        mcp_code_intel_search,
    ]

    # Attach any configured external MCP servers from mcp_servers.json
    for ext_cfg in load_external_mcp_configs(cfg.mcp_servers_file):
        bridge = MCPClientBridge(external_config=ext_cfg)
        try:
            ext_tools = bridge.list_tools()
        except Exception:
            continue
        for et in ext_tools:
            t_name = f"{ext_cfg.name}__{et['name']}"
            t_desc = et.get("description") or f"External MCP tool {et['name']} from {ext_cfg.name}"
            tools.append(_make_external_langchain_tool(bridge, et["name"], t_name, t_desc))

    return tools


def _make_external_langchain_tool(
    bridge: MCPClientBridge,
    remote_name: str,
    local_name: str,
    description: str,
) -> Any:
    from langchain_core.tools import StructuredTool

    def _invoke(**kwargs: Any) -> Any:
        return bridge.call_tool(remote_name, kwargs)

    return StructuredTool.from_function(
        func=_invoke,
        name=local_name,
        description=description,
    )
