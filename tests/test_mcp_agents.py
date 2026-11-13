from __future__ import annotations

import json
import sys
from pathlib import Path

from agentic_swe.config import Settings
from agentic_swe.llm import llm_available
from agentic_swe.mcp_client import (
    ExternalMCPServerConfig,
    MCPClientBridge,
    build_sandbox_langchain_tools,
    load_external_mcp_configs,
    run_mcp_agent_session,
)
from agentic_swe.models import EditPlan, PlanStep, RunState, RunStatus, Ticket
from agentic_swe.orchestrator.agents import _mcp_tool_patches
from agentic_swe.sandbox import LocalSandbox
from agentic_swe.sandbox.mcp_server import configure_server

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_repo"


def test_mcp_server_exposes_agent_and_workbench_tools(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs")
    configure_server(settings)

    bridge = MCPClientBridge()
    tools = bridge.list_tools()
    names = {t["name"] for t in tools}

    # Low-level sandbox tools + high-level agent/factory tools
    expected = {
        "sandbox_create",
        "sandbox_list_files",
        "sandbox_read_file",
        "sandbox_write_file",
        "sandbox_run",
        "sandbox_run_tests",
        "sandbox_destroy",
        "code_intel_graph",
        "agent_plan",
        "agent_diagnose",
        "factory_run",
        "factory_approve",
        "runs_list",
        "runs_show",
    }
    assert expected.issubset(names)

    # Call code_intel_graph over MCP ClientSession
    graph_out = bridge.call_tool(
        "code_intel_graph",
        {"repo_path": str(FIXTURE), "symbol": "add", "keyword": "calculator"},
    )
    assert "python" in graph_out["languages"]
    assert any(s["name"] == "add" for s in graph_out["matching_symbols"])
    assert any("calculator.py" in f for f in graph_out["candidate_files"])

    # Call agent_plan over MCP ClientSession
    plan_out = bridge.call_tool(
        "agent_plan",
        {"repo_path": str(FIXTURE), "ticket": "fix add so that 2+2 equals 4"},
    )
    assert plan_out["plan"]["test_command"] == "pytest -q"

    # Call agent_diagnose over MCP ClientSession
    diag_out = bridge.call_tool(
        "agent_diagnose",
        {
            "command": "pytest -q",
            "exit_code": 1,
            "stdout": "FAILED tests/test_calculator.py::test_add_simple\nassert add(2, 2) == 4",
            "prior_attempts": 1,
        },
    )
    assert "add" in diag_out["repair_brief"].lower()

    # Call factory_run over MCP ClientSession and inspect via runs_list / runs_show
    run_out = bridge.call_tool(
        "factory_run",
        {"repo_path": str(FIXTURE), "ticket": "fix add so that 2+2 equals 4"},
    )
    assert run_out["status"] == "succeeded"

    runs = bridge.call_tool("runs_list", {"limit": 5})
    assert any(r["run_id"] == run_out["run_id"] for r in runs)

    shown = bridge.call_tool("runs_show", {"run_id": run_out["run_id"]})
    assert shown["run_id"] == run_out["run_id"]
    assert "src/calculator.py" in shown["changed_files"]


def test_mcp_agent_session_end_to_end(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs")
    out = run_mcp_agent_session(
        repo_path=FIXTURE,
        ticket="fix add so that 2+2 equals 4",
        settings=settings,
    )
    assert out["initial_test_passed"] is False
    assert out["final_test_passed"] is True
    assert out["diagnosis"] is not None
    assert "src/calculator.py" in out["files"]


def test_external_stdio_mcp_client_bridge(tmp_path: Path):
    """Connect MCPClientBridge over real subprocess stdio to an external MCP server."""
    cfg_file = tmp_path / "mcp_servers.json"
    cfg_file.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "local-swe": {
                        "command": sys.executable,
                        "args": ["-m", "agentic_swe.sandbox.mcp_server"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    configs = load_external_mcp_configs(cfg_file)
    assert len(configs) == 1
    assert configs[0].name == "local-swe"

    ext_bridge = MCPClientBridge(
        external_config=ExternalMCPServerConfig(
            name="local-swe",
            command=sys.executable,
            args=["-m", "agentic_swe.sandbox.mcp_server"],
        )
    )
    tools = ext_bridge.list_tools()
    assert any(t["name"] == "agent_plan" for t in tools)

    plan_res = ext_bridge.call_tool(
        "agent_plan",
        {"repo_path": str(FIXTURE), "ticket": "fix add"},
    )
    assert plan_res["plan"]["steps"]


def test_free_llm_provider_settings():
    # Ollama requires zero API key
    ollama_cfg = Settings(llm_provider="ollama", openai_api_key=None)
    assert ollama_cfg.llm_enabled is True
    assert ollama_cfg.resolved_api_key == "ollama"
    assert ollama_cfg.resolved_base_url == "http://localhost:11434/v1"
    assert llm_available(ollama_cfg) is True

    # GitHub Models / Groq / Gemini base URL resolution
    gh_cfg = Settings(llm_provider="github", openai_api_key="ghp_test")
    assert gh_cfg.resolved_base_url == "https://models.inference.ai.azure.com"

    groq_cfg = Settings(llm_provider="groq", openai_api_key="gsk_test")
    assert groq_cfg.resolved_base_url == "https://api.groq.com/openai/v1"

    gemini_cfg = Settings(llm_provider="gemini", openai_api_key="AIza_test")
    assert gemini_cfg.resolved_base_url == "https://generativelanguage.googleapis.com/v1beta/openai/"


def test_programmer_mcp_tool_calling_loop(tmp_path: Path, monkeypatch):
    work = tmp_path / "ws"
    sandbox = LocalSandbox.from_repo(FIXTURE, work)
    settings = Settings(
        runs_dir=tmp_path / "runs",
        llm_provider="ollama",
        use_mcp_tools=True,
        mcp_servers_file=tmp_path / "nonexistent.json",
    )

    tools = build_sandbox_langchain_tools(sandbox, settings)
    tool_names = {t.name for t in tools}
    assert {
        "mcp_sandbox_list_files",
        "mcp_sandbox_read_file",
        "mcp_sandbox_write_file",
        "mcp_sandbox_run_tests",
        "mcp_code_intel_search",
    }.issubset(tool_names)

    # Simulate an LLM tool-calling execution that reads, writes, and tests via MCP tools
    fixed_code = '"""Calculator utilities."""\n\ndef add(a: int, b: int) -> int:\n    return a + b\n'

    def fake_tool_agent(cfg, *, system, user, tools, max_steps=6):
        t_map = {t.name: t for t in tools}
        t_map["mcp_sandbox_read_file"].invoke({"path": "src/calculator.py"})
        t_map["mcp_sandbox_write_file"].invoke(
            {"path": "src/calculator.py", "content": fixed_code}
        )
        return [
            {
                "tool": "mcp_sandbox_write_file",
                "args": {"path": "src/calculator.py", "content": fixed_code},
                "output": "Wrote src/calculator.py",
            }
        ]

    monkeypatch.setattr("agentic_swe.orchestrator.agents.run_tool_calling_agent", fake_tool_agent)

    state = RunState(
        ticket=Ticket(title="fix add", description="fix add"),
        repo_path=str(FIXTURE),
        work_dir=str(work),
        status=RunStatus.CODING,
        plan=EditPlan(
            summary="fix add",
            steps=[PlanStep(description="fix", target_files=["src/calculator.py"])],
            approved=True,
        ),
    )
    patches = _mcp_tool_patches(state, sandbox, settings)
    assert patches is not None
    assert len(patches) == 1
    assert patches[0].path == "src/calculator.py"
    assert "return a + b" in sandbox.read_file("src/calculator.py")
