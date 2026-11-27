# Agentic SWE Workbench — Gemini Code Review Style Guide

When reviewing Pull Requests in this repository, enforce the following project conventions and guardrails:

1. **Python 3.11+ & Typing Conventions**:
   - Use modern type annotations (`list[str]`, `dict[str, Any]`, `X | None`, `enum.StrEnum`).
   - All public models and settings use Pydantic v2 (`BaseModel`, `Field`, `SettingsConfigDict`).
   - Keep formatting compatible with `ruff` (`line-length = 100`, target `py311`, rules `E`, `F`, `I`, `UP`, `RUF`).

2. **Sandbox & Command Safety Guardrails**:
   - File operations inside `LocalSandbox`, `DockerSandbox`, or `E2BSandbox` must strictly prevent path traversal outside the sandbox root (`_resolve_inside`).
   - Shell execution must always pass through `CommandPolicy.check()` (`strict`, `standard`, or `off`) before invoking subprocesses.
   - Never weaken `DockerSandbox` security flags (`--cap-drop=ALL`, `--security-opt=no-new-privileges`, `--read-only`, `--network=none` by default).

3. **Multi-Agent Orchestrator & Self-Healing**:
   - Ensure LangGraph nodes (`Manager`, `Planner`, `Approve`, `Programmer`, `Diagnostic`, `Reviewer`) preserve bounded execution (`max_heal_attempts` and `max_files_touched`).
   - Never allow patches or agent logic to delete tests or strip `assert` statements from test suites to make tests pass.
   - All LLM integrations must preserve the offline deterministic heuristic fallback when no API key is configured.
