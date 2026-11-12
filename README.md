# Agentic SWE Workbench

Local framework for a multi-agent software engineering factory inspired by Open SWE / MetaGPT.

- **Ingress:** CLI tickets (no GitHub)
- **Execution:** isolated local sandboxes under `.runs/`
- **Orchestration:** LangGraph Manager → Planner → Approve → Programmer → Diagnostic → Reviewer
- **Intelligence:** Python AST import/dependency graph
- **Healing:** diagnostic stubs + optional DSPy modules with hard iteration caps
- **HITL:** optional plan approval interrupt before any writes
- **LLM:** optional OpenAI-backed Planner/Programmer/Reviewer (`pip install -e ".[llm]"`)

## Quick start

Requires **Python ≥ 3.11** (this machine uses Homebrew `python3.12`).

```bash
cd "/Users/shahrin-a/private/Agentic SWE Workbench"
/opt/homebrew/bin/python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Offline heuristic run against the broken fixture (auto-approves plan)
agentic-swe run \
  --repo examples/fixture_repo \
  --ticket "fix add so that 2+2 equals 4"

# Human-in-the-loop plan approval (interactive)
agentic-swe run \
  --repo examples/fixture_repo \
  --ticket "fix add so that 2+2 equals 4" \
  --no-auto-approve --interactive

# Non-interactive approve / reject
agentic-swe run -r examples/fixture_repo -t "fix add" --no-auto-approve --approve
agentic-swe run -r examples/fixture_repo -t "fix add" --no-auto-approve --reject --feedback "too broad"

# Optional LLM mode
pip install -e ".[llm]"
export OPENAI_API_KEY=sk-...
agentic-swe run -r examples/fixture_repo -t "fix add so that 2+2 equals 4"

# Inspect AST graph for a repo
agentic-swe graph examples/fixture_repo

# Start local MCP sandbox server (stdio)
agentic-swe mcp
# or: mcp run src/agentic_swe/sandbox/mcp_server.py:mcp
```

Run artifacts land in `.runs/<run_id>/` (workspace copy + `state.json`). The original fixture stays intentionally broken.

## Layout

```
src/agentic_swe/
  cli.py              # Typer CLI
  config.py           # settings
  models.py           # shared run-state schemas
  llm.py              # optional structured LLM helpers
  sandbox/            # local isolated worktrees + MCP tools
  code_intel/         # AST indexer + dependency graph
  healing/            # diagnostic + DSPy stubs
  orchestrator/       # LangGraph multi-agent factory
examples/fixture_repo/
tests/
docs/
```

## Design notes

Runs fully offline by default (heuristic Planner/Programmer/Reviewer). When `OPENAI_API_KEY` is set and extras `[llm]` are installed, the same graph nodes prefer structured LLM outputs and fall back to heuristics on failure.
