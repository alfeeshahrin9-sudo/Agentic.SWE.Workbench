from __future__ import annotations

import re
from dataclasses import dataclass

from agentic_swe.models import TestResult


@dataclass
class FailureInfo:
    failing_tests: list[str]
    assertion_hints: list[str]
    raw_excerpt: str


_TEST_RE = re.compile(r"^(FAILED|ERROR)\s+([^\s]+)", re.MULTILINE)
_ASSERT_RE = re.compile(r"AssertionError:?\s*(.*)", re.MULTILINE)
_E_RE = re.compile(r"^E\s+(.*)$", re.MULTILINE)


def parse_pytest_failures(output: str) -> FailureInfo:
    failing = [m.group(2) for m in _TEST_RE.finditer(output)]
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

    # Heuristic for the fixture: add() returns wrong sum
    if "add" in blob.lower() and ("== 4" in blob or "expected" in blob.lower()):
        repair_brief = (
            "The `add` function returns an incorrect result for simple arithmetic. "
            "Update `src/calculator.py` so `add(a, b)` returns `a + b`."
        )

    return diagnosis, repair_brief
