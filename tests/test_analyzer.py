from test_agent.analyzer import FailureAnalyzer
from test_agent.models import FailedTest


def test_analyzer_recognizes_assertion_failures() -> None:
    analyzer = FailureAnalyzer()
    failures = [
        FailedTest(
            nodeid="tests/test_sample.py::test_addition_failure",
            reason="AssertionError: assert 2 == 3",
            details="E       assert 2 == 3",
        )
    ]

    insights = analyzer.analyze(failures)

    assert len(insights) == 1
    assert insights[0].nodeid == failures[0].nodeid
    assert "expectation" in insights[0].probable_cause.lower()
    assert "business rule" in insights[0].suggested_fix.lower()
