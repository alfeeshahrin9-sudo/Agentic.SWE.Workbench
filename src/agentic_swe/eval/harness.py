"""Gold-patch evaluation harness for reproducible SWE factory benchmarking.

Runs the full multi-agent pipeline against a JSON manifest of benchmark tasks,
verifies test execution, compares workspace outputs against gold-patch
assertions/files, enforces file-touch budgets, and emits a structured JSON
report suitable for CI regression gates.
"""

from __future__ import annotations

import difflib
import json
import time
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from agentic_swe.config import ROOT, Settings, get_settings
from agentic_swe.models import RunStatus, Ticket, utcnow
from agentic_swe.observability import changed_files
from agentic_swe.orchestrator import run_factory


class EvalTask(BaseModel):
    """Single gold-patch evaluation benchmark task."""

    task_id: str
    repo_path: str
    ticket_title: str
    ticket_description: str = ""
    acceptance_criteria: list[str] = Field(
        default_factory=lambda: ["Unit tests pass", "Minimal diff"]
    )
    gold_files: dict[str, str] = Field(default_factory=dict)
    required_substrings: dict[str, list[str]] = Field(default_factory=dict)
    forbidden_substrings: dict[str, list[str]] = Field(default_factory=dict)
    expected_touched_files: list[str] = Field(default_factory=list)
    max_heal_attempts: int | None = None


class EvalTaskResult(BaseModel):
    """Outcome of running a single EvalTask through the SWE factory."""

    task_id: str
    run_id: str
    status: str
    passed: bool
    tests_passed: bool
    review_approved: bool
    gold_match: bool
    gold_similarity: float
    within_file_budget: bool
    changed_files: list[str] = Field(default_factory=list)
    heal_attempts: int = 0
    duration_sec: float = 0.0
    notes: list[str] = Field(default_factory=list)
    error: str | None = None


class EvalReport(BaseModel):
    """Aggregate report across an evaluation suite."""

    suite_path: str
    sandbox_backend: str
    command_policy_mode: str
    created_at: datetime = Field(default_factory=utcnow)
    total_tasks: int = 0
    passed_tasks: int = 0
    gold_matched_tasks: int = 0
    pass_rate: float = 0.0
    gold_match_rate: float = 0.0
    results: list[EvalTaskResult] = Field(default_factory=list)


def load_eval_tasks(tasks_file: Path) -> list[EvalTask]:
    """Load evaluation task definitions from a JSON file."""
    path = tasks_file.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Evaluation tasks file not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("tasks") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        raise ValueError(f"Expected a list of tasks or {{'tasks': [...]}} in {path}")
    return [EvalTask.model_validate(item) for item in items]


def run_evaluation(
    tasks_file: Path,
    *,
    settings: Settings | None = None,
    output_path: Path | None = None,
    task_ids: list[str] | None = None,
    base_dir: Path | None = None,
) -> EvalReport:
    """Execute evaluation tasks and optionally persist a JSON report."""
    cfg = settings or get_settings()
    tasks = load_eval_tasks(tasks_file)
    if task_ids:
        wanted = set(task_ids)
        tasks = [t for t in tasks if t.task_id in wanted]

    repo_base = (base_dir or ROOT).resolve()
    results: list[EvalTaskResult] = []

    for task in tasks:
        results.append(_run_single_task(task, cfg, repo_base))

    total = len(results)
    passed_count = sum(1 for r in results if r.passed)
    gold_count = sum(1 for r in results if r.gold_match)

    report = EvalReport(
        suite_path=str(tasks_file.resolve()),
        sandbox_backend=cfg.sandbox_backend,
        command_policy_mode=cfg.command_policy_mode,
        total_tasks=total,
        passed_tasks=passed_count,
        gold_matched_tasks=gold_count,
        pass_rate=(passed_count / total) if total else 0.0,
        gold_match_rate=(gold_count / total) if total else 0.0,
        results=results,
    )

    if output_path is not None:
        out = output_path.resolve()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    return report


def _run_single_task(task: EvalTask, base_settings: Settings, repo_base: Path) -> EvalTaskResult:
    task_repo = Path(task.repo_path)
    if not task_repo.is_absolute():
        task_repo = (repo_base / task_repo).resolve()

    task_settings = base_settings.model_copy(deep=True)
    if task.max_heal_attempts is not None:
        task_settings.max_heal_attempts = task.max_heal_attempts

    issue = Ticket(
        title=task.ticket_title,
        description=task.ticket_description or task.ticket_title,
        acceptance_criteria=list(task.acceptance_criteria),
    )

    started = time.perf_counter()
    run = run_factory(
        ticket=issue,
        repo_path=task_repo,
        settings=task_settings,
        auto_approve=True,
    )
    duration = round(time.perf_counter() - started, 3)

    touched = changed_files(run)
    tests_passed = bool(run.test_results and run.test_results[-1].passed)
    review_approved = bool(run.reviews and run.reviews[-1].approved)
    within_budget = len(touched) <= task_settings.max_files_touched
    if task.expected_touched_files:
        allowed_set = set(task.expected_touched_files)
        within_budget = within_budget and bool(touched) and set(touched).issubset(allowed_set)

    notes: list[str] = []
    gold_match, similarity, gold_notes = _evaluate_gold(task, run.work_dir)
    notes.extend(gold_notes)

    overall_passed = (
        run.status == RunStatus.SUCCEEDED
        and tests_passed
        and review_approved
        and gold_match
        and within_budget
    )

    return EvalTaskResult(
        task_id=task.task_id,
        run_id=run.run_id,
        status=run.status.value,
        passed=overall_passed,
        tests_passed=tests_passed,
        review_approved=review_approved,
        gold_match=gold_match,
        gold_similarity=similarity,
        within_file_budget=within_budget,
        changed_files=touched,
        heal_attempts=len(run.heal_attempts),
        duration_sec=duration,
        notes=notes,
        error=run.error,
    )


def _evaluate_gold(task: EvalTask, work_dir: str | None) -> tuple[bool, float, list[str]]:
    if not work_dir:
        return False, 0.0, ["Missing work_dir in RunState"]

    root = Path(work_dir)
    notes: list[str] = []
    similarities: list[float] = []
    all_ok = True

    for rel_path, gold_content in task.gold_files.items():
        candidate = root / rel_path
        if not candidate.is_file():
            all_ok = False
            similarities.append(0.0)
            notes.append(f"Gold target missing: {rel_path}")
            continue
        actual = _normalize_text(candidate.read_text(encoding="utf-8"))
        expected = _normalize_text(gold_content)
        ratio = difflib.SequenceMatcher(None, actual, expected).ratio()
        similarities.append(ratio)
        if actual != expected:
            all_ok = False
            notes.append(f"Gold mismatch in {rel_path} (similarity={ratio:.2f})")

    for rel_path, substrings in task.required_substrings.items():
        candidate = root / rel_path
        if not candidate.is_file():
            all_ok = False
            notes.append(f"Required-substring target missing: {rel_path}")
            continue
        actual = candidate.read_text(encoding="utf-8")
        for needle in substrings:
            if needle not in actual:
                all_ok = False
                notes.append(f"Missing required substring {needle!r} in {rel_path}")

    for rel_path, substrings in task.forbidden_substrings.items():
        candidate = root / rel_path
        if not candidate.is_file():
            continue
        actual = candidate.read_text(encoding="utf-8")
        for needle in substrings:
            if needle in actual:
                all_ok = False
                notes.append(f"Found forbidden substring {needle!r} in {rel_path}")

    avg_sim = round(sum(similarities) / len(similarities), 4) if similarities else (1.0 if all_ok else 0.0)
    return all_ok, avg_sim, notes


def _normalize_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").strip().splitlines())
