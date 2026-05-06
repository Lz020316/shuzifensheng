from test_agent.agent import AutoTestAgent
from test_agent.config import AgentConfig
from test_agent.models import TestRunResult


class DummyRunner:
    def run(self, command: list[str]) -> TestRunResult:
        stdout = """
============================= test session starts =============================
collected 1 item

tests/test_sample.py F

=================================== FAILURES ===================================
____________________________ test_addition_failure _____________________________
>       assert 1 + 1 == 3
E       assert 2 == 3

=========================== short test summary info ============================
FAILED tests/test_sample.py::test_addition_failure - AssertionError: assert 2 == 3
============================== 1 failed in 0.01s ==============================
""".strip()
        return TestRunResult(
            command=command,
            return_code=1,
            stdout=stdout,
            stderr="",
            duration_seconds=0.012,
        )


def test_agent_run_once_generates_report() -> None:
    config = AgentConfig.from_command_string("pytest -q")
    agent = AutoTestAgent.default(config=config)
    agent.runner = DummyRunner()

    report = agent.run_once()

    assert report["succeeded"] is False
    summary = report["summary"]
    assert isinstance(summary, dict)
    assert summary["failure_count"] == 1
    insights = report["insights"]
    assert isinstance(insights, list)
    assert insights[0]["nodeid"] == "tests/test_sample.py::test_addition_failure"
