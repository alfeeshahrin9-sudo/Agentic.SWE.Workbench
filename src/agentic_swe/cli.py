from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from agentic_swe import __version__
from agentic_swe.code_intel import detect_languages, index_repo
from agentic_swe.config import get_settings
from agentic_swe.llm import llm_available
from agentic_swe.models import Ticket
from agentic_swe.observability import changed_files, list_runs, load_run
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
    auto_approve: bool = typer.Option(
        True,
        "--auto-approve/--no-auto-approve",
        help="Skip human plan approval (default: on)",
    ),
    interactive: bool = typer.Option(
        False,
        "--interactive/--no-interactive",
        help="Prompt on stdin when plan approval is required",
    ),
    approve: Optional[bool] = typer.Option(
        None,
        "--approve/--reject",
        help="Non-interactive plan decision when --no-auto-approve is set",
    ),
    feedback: Optional[str] = typer.Option(
        None,
        "--feedback",
        help="Optional feedback attached to --approve/--reject",
    ),
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

    mode = "LLM" if llm_available(settings) else "heuristic"
    langs = ", ".join(detect_languages(repo)) or "unknown"
    console.print(
        Panel.fit(
            f"[bold]Ticket[/bold]\n{issue.title}\n"
            f"[dim]agent mode: {mode} | backend: {settings.sandbox_backend} | langs: {langs}[/dim]",
            title="Manager",
        )
    )

    decision = None
    if approve is not None:
        decision = {"approved": approve, "feedback": feedback or ""}

    result = run_factory(
        ticket=issue,
        repo_path=repo,
        settings=settings,
        auto_approve=auto_approve,
        approval_decision=decision,
        interactive=interactive and not auto_approve and decision is None,
    )

    table = Table(title=f"Run {result.run_id}")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("status", str(result.status.value))
    table.add_row("work_dir", result.work_dir or "")
    table.add_row("heal_attempts", str(len(result.heal_attempts)))
    table.add_row("reviews", str(len(result.reviews)))
    table.add_row("tests", str(len(result.test_results)))
    if result.test_results:
        last = result.test_results[-1]
        table.add_row("last_exit", str(last.exit_code))
        table.add_row("passed", str(last.passed))
    if result.reviews:
        table.add_row("review_approved", str(result.reviews[-1].approved))
        table.add_row("review_summary", result.reviews[-1].summary)
    if result.error:
        table.add_row("error", result.error)
    console.print(table)

    state_path = settings.runs_dir / result.run_id / "state.json"
    console.print(f"State written to [cyan]{state_path}[/cyan]")

    if result.status.value == "awaiting_approval":
        console.print(
            "[yellow]Paused for plan approval.[/yellow] Re-run with "
            "`--no-auto-approve --approve` or `--interactive`."
        )
        raise typer.Exit(code=2)

    if result.status.value != "succeeded":
        raise typer.Exit(code=1)


@app.command("graph")
def graph_cmd(
    repo: Path = typer.Argument(..., help="Repository path to index"),
) -> None:
    """Print a summary of the multi-language dependency graph (Python + TS/JS)."""
    if not repo.is_dir():
        raise typer.BadParameter(f"Repo not found: {repo}")
    g = index_repo(repo)
    summary = g.summary()
    summary["languages"] = detect_languages(repo)
    console.print_json(json.dumps(summary, indent=2))

    symbols = list(g.symbols.values())[:20]
    table = Table(title="Sample symbols")
    table.add_column("kind")
    table.add_column("name")
    table.add_column("path")
    for s in symbols:
        table.add_row(s.kind, s.name, s.path)
    console.print(table)


@app.command("runs")
def runs_cmd(
    limit: int = typer.Option(20, "--limit", "-n", help="Max runs to list"),
) -> None:
    """List recent local factory runs from .runs/."""
    settings = get_settings()
    rows = list_runs(settings=settings, limit=limit)
    if not rows:
        console.print("[dim]No runs found.[/dim]")
        return
    table = Table(title=f"Runs in {settings.runs_dir}")
    table.add_column("run_id")
    table.add_column("status")
    table.add_column("title")
    table.add_column("heals")
    table.add_column("reviews")
    for row in rows:
        table.add_row(
            row.run_id,
            row.status,
            row.title[:48],
            str(row.heal_attempts),
            str(row.reviews),
        )
    console.print(table)


@app.command("show")
def show_cmd(
    run_id: str = typer.Argument(..., help="Run id (e.g. run_abc123)"),
) -> None:
    """Show details for a persisted local run."""
    settings = get_settings()
    try:
        run = load_run(run_id, settings=settings)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc

    table = Table(title=run.run_id)
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("status", run.status.value)
    table.add_row("ticket", run.ticket.title)
    table.add_row("repo", run.repo_path)
    table.add_row("work_dir", run.work_dir or "")
    table.add_row("test_command", run.plan.test_command if run.plan else "")
    table.add_row("heal_attempts", str(len(run.heal_attempts)))
    table.add_row("reviews", str(len(run.reviews)))
    table.add_row("changed_files", ", ".join(changed_files(run)) or "(none)")
    if run.error:
        table.add_row("error", run.error)
    console.print(table)

    if run.messages:
        console.print(Panel("\n".join(run.messages[-12:]), title="Recent messages"))


@app.command("mcp")
def mcp_cmd() -> None:
    """Start the local sandbox MCP server over stdio."""
    from agentic_swe.sandbox.mcp_server import main as mcp_main

    mcp_main()


if __name__ == "__main__":
    app()
