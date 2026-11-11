from pathlib import Path

from agentic_swe.sandbox import LocalSandbox, SandboxManager

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_repo"


def test_local_sandbox_copy_and_test(tmp_path: Path):
    work = tmp_path / "ws"
    sb = LocalSandbox.from_repo(FIXTURE, work)
    assert "src/calculator.py" in sb.list_files("**/*.py")
    code, stdout, stderr, _ = sb.run_tests("pytest -q")
    assert code != 0  # fixture is intentionally broken
    assert "FAILED" in stdout or "failed" in stdout.lower() or code != 0


def test_sandbox_manager_create_destroy(tmp_path: Path):
    from agentic_swe.config import Settings

    settings = Settings(runs_dir=tmp_path / "runs")
    mgr = SandboxManager(settings)
    sb = mgr.create(FIXTURE, run_id="run_test")
    assert sb.work_dir.exists()
    mgr.destroy("run_test")
    assert not sb.work_dir.exists()
