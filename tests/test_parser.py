from test_agent.parser import PytestOutputParser


def test_parse_failed_tests_extracts_summary_failures() -> None:
    stdout = """
============================= test session starts =============================
platform linux -- Python 3.12.0, pytest-8.2.2
collected 2 items

tests/test_sample.py .F                                                 [100%]

=================================== FAILURES ===================================
____________________________ test_addition_failure _____________________________
    def test_addition_failure():
>       assert 1 + 1 == 3
E       assert 2 == 3

tests/test_sample.py:6: AssertionError
=========================== short test summary info ============================
FAILED tests/test_sample.py::test_addition_failure - AssertionError: assert 2 == 3
========================= 1 failed, 1 passed in 0.03s =========================
""".strip()

    parser = PytestOutputParser()
    failures = parser.parse_failed_tests(stdout)

    assert len(failures) == 1
    assert failures[0].nodeid == "tests/test_sample.py::test_addition_failure"
    assert "AssertionError" in failures[0].reason
