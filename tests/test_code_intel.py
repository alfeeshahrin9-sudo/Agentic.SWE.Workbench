from pathlib import Path

from agentic_swe.code_intel import index_python_repo

FIXTURE = Path(__file__).resolve().parents[1] / "examples" / "fixture_repo"


def test_index_fixture_finds_add():
    graph = index_python_repo(FIXTURE)
    matches = graph.find_by_name("add")
    assert any(m.name == "add" and m.kind == "function" for m in matches)
    assert graph.summary()["file_count"] >= 2


def test_keyword_search_hits_calculator():
    graph = index_python_repo(FIXTURE)
    files = graph.find_files_for_keywords(["add", "calculator"])
    assert any("calculator.py" in f for f in files)
