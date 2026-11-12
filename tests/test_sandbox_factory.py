from pathlib import Path

import pytest

from agentic_swe.config import Settings
from agentic_swe.sandbox import SandboxError, SandboxManager, create_sandbox
from agentic_swe.sandbox.local import LocalSandbox

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_repo"


def test_create_local_sandbox(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs", sandbox_backend="local")
    sb = create_sandbox(
        source_repo=FIXTURE,
        work_dir=tmp_path / "ws",
        settings=settings,
    )
    assert isinstance(sb, LocalSandbox)
    assert "src/calculator.py" in sb.list_files("**/*.py")


def test_unknown_backend_raises(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs", sandbox_backend="nope")
    with pytest.raises(SandboxError, match="Unknown sandbox backend"):
        create_sandbox(source_repo=FIXTURE, work_dir=tmp_path / "ws", settings=settings)


def test_e2b_backend_requires_key(tmp_path: Path):
    settings = Settings(runs_dir=tmp_path / "runs", sandbox_backend="e2b", e2b_api_key=None)
    with pytest.raises(SandboxError, match="E2B_API_KEY"):
        SandboxManager(settings).create(FIXTURE, run_id="run_e2b_test")
