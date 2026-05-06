"""Main orchestration for the automated testing agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

from .analyzer import FailureAnalyzer
from .config import AgentConfig
from .parser import PytestOutputParser
from .runner import TestRunner


@dataclass(slots=True)
class AutoTestAgent:
    """Run tests, parse failures, and produce structured reports."""

    config: AgentConfig
    runner: TestRunner
    parser: PytestOutputParser
    analyzer: FailureAnalyzer

    @classmethod
    def default(cls, config: AgentConfig | None = None) -> "AutoTestAgent":
        """Construct a default agent with built-in components."""
        effective_config = config if config is not None else AgentConfig()
        return cls(
            config=effective_config,
            runner=TestRunner(),
            parser=PytestOutputParser(),
            analyzer=FailureAnalyzer(),
        )

    def run_once(self) -> dict[str, object]:
        """Execute one full test-analysis cycle."""
        result = self.runner.run(self.config.test_command)
        failures = self.parser.parse_failed_tests(result.stdout)
        insights = self.analyzer.analyze(failures)

        output_text = self._compose_output(result.stdout, result.stderr)
        report: dict[str, object] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "command": result.command,
            "succeeded": result.succeeded,
            "return_code": result.return_code,
            "duration_seconds": round(result.duration_seconds, 3),
            "summary": {
                "failure_count": len(failures),
                "insight_count": len(insights),
            },
            "insights": [
                {
                    "nodeid": insight.nodeid,
                    "reason": insight.reason,
                    "probable_cause": insight.probable_cause,
                    "suggested_fix": insight.suggested_fix,
                }
                for insight in insights
            ],
            "output_excerpt": output_text[-self.config.max_output_chars :],
        }
        return report

    def to_json(self, report: dict[str, object]) -> str:
        """Serialize report as pretty JSON."""
        return json.dumps(report, ensure_ascii=False, indent=2)

    def _compose_output(self, stdout: str, stderr: str) -> str:
        if not stderr:
            return stdout
        if not stdout:
            return stderr
        return f"{stdout}\n\n[stderr]\n{stderr}"
