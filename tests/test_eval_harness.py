import json
from pathlib import Path

from agentic_swe.config import Settings
from agentic_swe.eval import load_eval_tasks, run_evaluation

ROOT = Path(__file__).resolve().parents[1]
TASKS_FILE = ROOT / "evals" / "tasks.json"


def test_load_eval_tasks_reads_manifest():
    tasks = load_eval_tasks(TASKS_FILE)
    ids = [t.task_id for t in tasks]
    assert "py-calc-add" in ids
    assert "ts-calc-add" in ids


def test_run_evaluation_python_fixture_and_report(tmp_path: Path):
    settings = Settings(
        runs_dir=tmp_path / "runs",
        sandbox_backend="local",
        command_policy_mode="strict",
        openai_api_key=None,
    )
    report_path = tmp_path / "eval_report.json"

    report = run_evaluation(
        TASKS_FILE,
        settings=settings,
        output_path=report_path,
        task_ids=["py-calc-add"],
        base_dir=ROOT,
    )

    assert report.total_tasks == 1
    assert report.passed_tasks == 1
    assert report.pass_rate == 1.0
    assert report.gold_match_rate == 1.0
    assert report.results[0].within_file_budget
    assert report.results[0].changed_files == ["src/calculator.py"]

    assert report_path.is_file()
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["passed_tasks"] == 1
    assert persisted["command_policy_mode"] == "strict"
