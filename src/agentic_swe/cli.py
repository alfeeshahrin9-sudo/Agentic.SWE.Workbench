from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agentic_swe import __version__
from agentic_swe.code_intel import index_python_repo
from agentic_swe.config import get_settings
from agentic_swe.models import Ticket
from agentic_swe.orchestrator import run_factory

app = typer.Typer(
    name="agentic-swe",
    help="Local Agentic Software Engineering Workbench",
    add_completion=False,
)
console = Console()


@app.callback()
def main() -> None:
    """Agentic SWE Workbench CLI."""


@app.command("version")
def version() -> None:
    """Print package version."""
    console.print(__version__)


@app.command("run")
def run_cmd(
    repo: Path = typer.Option(..., "--repo", "-r", help="Path to local target repository"),
    ticket: str = typer.Option(..., "--ticket", "-t", help="Natural-language issue description"),
    title: Optional[str] = typer.Option(None, "--title", help="Optional short title"),
) -> None:
    """Run the multi-agent factory against a local repo (offline heuristics by default)."""
    if not repo.is_dir():
        raise typer.BadParameter(f"Repo not found: {repo}")

    settings = get_settings()
    issue = Ticket(
        title=title or ticket[:72],
        description=ticket,
        acceptance_criteria=["Unit tests pass", "Minimal diff"],
    )

    console.print(Panel.fit(f"[bold]Ticket[/bold]\n{issue.title}", title="Manager"))
    result = run_factory(ticket=issue, repo_path=repo, settings=settings)

    table = Table(title=f"Run {result.run_id}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("status", str(result.status.value))
    table.add_row("work_dir", result.work_dir or "")
    table.add_row("heal_attempts", str(len(result.heal_attempts)))
    table.add_row("tests", str(len(result.test_results)))
    if result.test_results:
        last = result.test_results[-1]
        table.add_row("last_exit", str(last.exit_code))
        table.add_row("passed", str(last.passed))
    if result.error:
        table.add_row("error", result.error)
    console.print(table)

    state_path = settings.runs_dir / result.run_id / "state.json"
    console.print(f"State written to [cyan]{state_path}[/cyan]")

    if result.status.value != "succeeded":
        raise typer.Exit(code=1)


@app.command("graph")
def graph_cmd(
    repo: Path = typer.Argument(..., help="Repository path to index"),
) -> None:
    """Print a summary of the Python AST dependency graph."""
    if not repo.is_dir():
        raise typer.BadParameter(f"Repo not found: {repo}")
    g = index_python_repo(repo)
    summary = g.summary()
    console.print_json(json.dumps(summary, indent=2))

    symbols = list(g.symbols.values())[:15]
    table = Table(title="Sample symbols")
    table.add_column("kind")
    table.add_column("name")
    table.add_column("path")
    for s in symbols:
        table.add_row(s.kind, s.name, s.path)
    console.print(table)


@app.command("mcp")
def mcp_cmd() -> None:
    """Start the local sandbox MCP server over stdio."""
    from agentic_swe.sandbox.mcp_server import main as mcp_main

    mcp_main()


if __name__ == "__main__":
    app()
