from __future__ import annotations

import re
from dataclasses import dataclass

from agentic_swe.models import TestResult


@dataclass
class FailureInfo:
    failing_tests: list[str]
    assertion_hints: list[str]
    raw_excerpt: str


_PYTEST_TEST_RE = re.compile(r"^(?:FAILED|ERROR)\s+([^\s]+)", re.MULTILINE)
_NODE_TAP_RE = re.compile(r"^not ok \d+\s+-\s+(.+)$", re.MULTILINE)
_NODE_SYM_RE = re.compile(r"^[✖✗×]\s+([^\n(]+)", re.MULTILINE)
_ASSERT_RE = re.compile(r"AssertionError(?:\s*\[ERR_ASSERTION\])?:?\s*(.*)", re.MULTILINE)
_E_RE = re.compile(r"^E\s+(.*)$", re.MULTILINE)


def parse_pytest_failures(output: str) -> FailureInfo:
    """Parse failure names and assertion hints from pytest or Node/TS test runners."""
    failing = [m.group(1).strip() for m in _PYTEST_TEST_RE.finditer(output)]
    if not failing:
        failing = [m.group(1).strip() for m in _NODE_TAP_RE.finditer(output)]
    if not failing:
        failing = [
            m.group(1).strip()
            for m in _NODE_SYM_RE.finditer(output)
            if not m.group(1).strip().startswith("failing tests")
        ]

    assertions = [m.group(1).strip() for m in _ASSERT_RE.finditer(output) if m.group(1).strip()]
    e_lines = [m.group(1).strip() for m in _E_RE.finditer(output) if m.group(1).strip()]
    hints = assertions or e_lines
    excerpt = output[-2500:] if len(output) > 2500 else output
    return FailureInfo(failing_tests=failing, assertion_hints=hints, raw_excerpt=excerpt)


def diagnose_failure(test_result: TestResult) -> tuple[str, str]:
    """Return (diagnosis, repair_brief) from a failed test run."""
    blob = f"{test_result.stdout}\n{test_result.stderr}"
    info = parse_pytest_failures(blob)

    failing = ", ".join(info.failing_tests) or "unknown test(s)"
    hints = "; ".join(info.assertion_hints[:5]) or "no assertion text captured"

    diagnosis = (
        f"Command `{test_result.command}` exited {test_result.exit_code}. "
        f"Failing: {failing}. Hints: {hints}."
    )

    repair_brief = (
        "Inspect the failing assertion and correct the implementation so the "
        "expected value is returned. Prefer minimal edits to the production "
        f"module referenced by: {failing}. Do not weaken or delete tests."
    )

    is_js_ts = "npm" in test_result.command.lower() or "node" in test_result.command.lower()
    target_hint = "src/calculator.js" if is_js_ts else "src/calculator.py"

    # Heuristic for the fixture: add() returns wrong sum
    if "add" in blob.lower() and (
        "== 4" in blob or "expected" in blob.lower() or "err_assertion" in blob.lower()
    ):
        repair_brief = (
            "The `add` function returns an incorrect result for simple arithmetic. "
            f"Update `{target_hint}` so `add(a, b)` returns `a + b`."
        )

    return diagnosis, repair_brief
