from pathlib import Path

from agentic_swe.code_intel import detect_languages, detect_test_command, index_repo

TS_FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_ts"
PY_FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_repo"


def test_index_ts_fixture_finds_add():
    graph = index_repo(TS_FIXTURE)
    matches = graph.find_by_name("add")
    assert any(m.name == "add" for m in matches)
    assert any("calculator.js" in m.path for m in matches)


def test_detect_ts_metadata():
    assert "typescript" in detect_languages(TS_FIXTURE)
    assert detect_test_command(TS_FIXTURE) == "npm test"
    assert detect_test_command(PY_FIXTURE) == "pytest -q"
