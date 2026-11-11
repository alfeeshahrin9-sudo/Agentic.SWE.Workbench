# Agentic SWE Workbench

Local framework for a multi-agent software engineering factory inspired by Open SWE / MetaGPT.

- **Ingress:** CLI tickets (no GitHub)
- **Execution:** isolated local sandboxes under `.runs/`
- **Orchestration:** LangGraph Manager → Planner → Programmer → Diagnostic
- **Intelligence:** Python AST import/dependency graph
- **Healing:** diagnostic stubs + optional DSPy modules with hard iteration caps

## Quick start

Requires **Python ≥ 3.11** (this machine uses Homebrew `python3.12`).

```bash
cd "/Users/shahrin-a/private/Agentic SWE Workbench"
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Offline heuristic run against the broken fixture
agentic-swe run \
  --repo examples/fixture_repo \
  --ticket "fix add so that 2+2 equals 4"

# Inspect AST graph for a repo
agentic-swe graph examples/fixture_repo

# Start local MCP sandbox server (stdio)
agentic-swe mcp
```

Run artifacts land in `.runs/<run_id>/` (workspace copy + `state.json`). The original fixture stays intentionally broken.

## Layout

```
src/agentic_swe/
  cli.py              # Typer CLI
  config.py           # settings
  models.py           # shared run-state schemas
  sandbox/            # local isolated worktrees + MCP tools
  code_intel/         # AST indexer + dependency graph
  healing/            # diagnostic + DSPy stubs
  orchestrator/       # LangGraph multi-agent factory
examples/fixture_repo/
tests/
```

## Design notes

This groundbase runs fully offline by default. When `OPENAI_API_KEY` is set and extras `[llm]` are installed, agents can call an LLM; otherwise heuristic stubs drive the same graph so the framework is testable without cloud accounts.
