from __future__ import annotations

import json
from pathlib import Path


def detect_test_command(repo_path: Path) -> str:
    """Infer a default test command from local project metadata."""
    root = repo_path.resolve()

    pkg = root / "package.json"
    if pkg.is_file():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8"))
            scripts = data.get("scripts") or {}
            for key in ("test", "test:unit", "unit"):
                if key in scripts:
                    return f"npm run {key}" if key != "test" else "npm test"
        except (OSError, json.JSONDecodeError):
            pass
        return "npm test"

    if (root / "pyproject.toml").is_file() or (root / "pytest.ini").is_file():
        return "pytest -q"
    if list(root.rglob("test_*.py")) or list(root.rglob("*_test.py")):
        return "pytest -q"
    if list(root.rglob("*.test.ts")) or list(root.rglob("*.test.js")):
        return "npm test"
    return "pytest -q"


def detect_languages(repo_path: Path) -> list[str]:
    root = repo_path.resolve()
    langs: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix == ".py":
            langs.add("python")
        elif path.suffix in {".ts", ".tsx", ".js", ".jsx"}:
            langs.add("typescript")
    return sorted(langs)
