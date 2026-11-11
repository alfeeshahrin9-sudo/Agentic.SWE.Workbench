from agentic_swe.healing import diagnose_failure, parse_pytest_failures, refine_repair_brief
from agentic_swe.models import TestResult


def test_parse_pytest_failures():
    output = """
FAILED tests/test_calculator.py::test_add_simple - AssertionError: assert -0 == 4
E       assert -0 == 4
"""
    info = parse_pytest_failures(output)
    assert info.failing_tests
    assert info.assertion_hints


def test_diagnose_and_refine():
    result = TestResult(
        command="pytest -q",
        exit_code=1,
        stdout="FAILED tests/test_calculator.py::test_add_simple\nassert add(2, 2) == 4",
        stderr="",
        passed=False,
    )
    diagnosis, brief = diagnose_failure(result)
    assert "exited" in diagnosis
    refined = refine_repair_brief(diagnosis, brief, prior_attempts=2)
    assert "Prior" in refined or "narrow" in refined.lower() or "smallest" in refined.lower()
