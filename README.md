# Agentic SWE Workbench

Local framework for a multi-agent software engineering factory inspired by Open SWE / MetaGPT.

- **Ingress:** CLI tickets (no GitHub)
- **Execution:** pluggable sandboxes (`local` default, optional `e2b`)
- **Orchestration:** LangGraph Manager → Planner → Approve → Programmer → Diagnostic → Reviewer
- **Intelligence:** multi-language dependency graph (Python AST + TS/JS, optional Tree-sitter)
- **Healing:** diagnostic stubs + optional DSPy modules with hard iteration caps
- **HITL:** optional plan approval interrupt before any writes
- **Observability:** local run history via `agentic-swe runs` / `show`

## Quick start

Requires **Python ≥ 3.11** (this machine uses Homebrew `python3.12`). Node.js is needed for the TS fixture.

```bash
cd "/Users/shahrin-a/private/Agentic SWE Workbench"
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Python fixture
agentic-swe run -r examples/fixture_repo -t "fix add so that 2+2 equals 4"

# TypeScript/JS fixture (uses npm test → node --test)
agentic-swe run -r examples/fixture_ts -t "fix add so that 2+2 equals 4"

# HITL plan approval
agentic-swe run -r examples/fixture_repo -t "fix add" --no-auto-approve --interactive

# Inspect graph / runs
agentic-swe graph examples/fixture_ts
agentic-swe runs
agentic-swe show <run_id>

# MCP sandbox server
agentic-swe mcp
```

### Optional extras

```bash
pip install -e ".[llm]"          # OpenAI-backed agents
pip install -e ".[e2b]"          # cloud sandbox backend
pip install -e ".[treesitter]"   # native Tree-sitter parsers
export AGENTIC_SWE_SANDBOX_BACKEND=local   # or e2b
```

## Layout

```
src/agentic_swe/
  cli.py              # Typer CLI
  config.py           # settings
  models.py           # shared run-state schemas
  llm.py              # optional structured LLM helpers
  observability.py    # local run listing / load
  sandbox/            # protocol, local, optional e2b, MCP
  code_intel/         # Python + TS/JS indexer
  healing/            # diagnostic + DSPy stubs
  orchestrator/       # LangGraph multi-agent factory
examples/fixture_repo/
examples/fixture_ts/
tests/
docs/
```
