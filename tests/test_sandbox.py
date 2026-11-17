from pathlib import Path

import pytest

from agentic_swe.sandbox import LocalSandbox, SandboxError, SandboxManager

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_repo"


def test_local_sandbox_copy_and_test(tmp_path: Path):
    work = tmp_path / "ws"
    sb = LocalSandbox.from_repo(FIXTURE, work)
    assert "src/calculator.py" in sb.list_files("**/*.py")
    code, stdout, _stderr, _ = sb.run_tests("pytest -q")
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


def test_sandbox_resolve_blocks_sibling_prefix_escape(tmp_path: Path):
    work = tmp_path / "ws"
    sibling = tmp_path / "ws_evil"
    sibling.mkdir(parents=True)
    (sibling / "secret.txt").write_text("nope", encoding="utf-8")

    sb = LocalSandbox(work)
    with pytest.raises(SandboxError, match="Path escapes sandbox"):
        sb.read_file("../ws_evil/secret.txt")
