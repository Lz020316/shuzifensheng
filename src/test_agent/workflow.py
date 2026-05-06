"""Scenario-oriented automation testing workflow agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json

from .action_planner import ActionPlanner
from .case_generator import TestCaseGenerator
from .mcp_executor import LocalMockMCPClient, MCPExecutor
from .models import ActionPoint, CaseEvaluation, MCPCallResult, TestCase
from .source_loader import SourceLoader
from .verifier import ResultVerifier


@dataclass(slots=True)
class WorkflowTestAgent:
    """End-to-end workflow: source -> cases -> actions -> MCP -> report."""

    source_loader: SourceLoader
    case_generator: TestCaseGenerator
    action_planner: ActionPlanner
    executor: MCPExecutor
    verifier: ResultVerifier

    @classmethod
    def default(cls) -> "WorkflowTestAgent":
        """Construct workflow agent with default components."""
        return cls(
            source_loader=SourceLoader(),
            case_generator=TestCaseGenerator(),
            action_planner=ActionPlanner(),
            executor=MCPExecutor(client=LocalMockMCPClient()),
            verifier=ResultVerifier(),
        )

    def run(self, source: str) -> dict[str, object]:
        """Run one complete workflow and return report payload."""
        artifact = self.source_loader.load(source)
        cases = self.case_generator.generate(artifact)
        actions = self.action_planner.plan(artifact=artifact, cases=cases)
        call_results = self.executor.execute(actions)
        evaluations = self.verifier.verify(cases=cases, actions=actions, results=call_results)

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "input": {
                "kind": artifact.kind,
                "identifier": artifact.identifier,
                "metadata": artifact.metadata,
            },
            "summary": {
                "test_case_count": len(cases),
                "action_point_count": len(actions),
                "mcp_call_count": len(call_results),
                "passed_count": sum(1 for item in evaluations if item.passed),
                "failed_count": sum(1 for item in evaluations if not item.passed),
            },
            "test_cases": [self._serialize_case(case) for case in cases],
            "action_points": [self._serialize_action(action) for action in actions],
            "mcp_results": [self._serialize_call_result(item) for item in call_results],
            "case_results": [self._serialize_evaluation(item) for item in evaluations],
        }

    def to_json(self, report: dict[str, object]) -> str:
        """Serialize workflow report to JSON."""
        return json.dumps(report, ensure_ascii=False, indent=2)

    @staticmethod
    def _serialize_case(case: TestCase) -> dict[str, object]:
        return {
            "case_id": case.case_id,
            "title": case.title,
            "steps": case.steps,
            "expected_result": case.expected_result,
            "source_ref": case.source_ref,
        }

    @staticmethod
    def _serialize_action(action: ActionPoint) -> dict[str, object]:
        return {
            "action_id": action.action_id,
            "case_id": action.case_id,
            "action": action.action,
            "params": action.params,
        }

    @staticmethod
    def _serialize_call_result(result: MCPCallResult) -> dict[str, object]:
        return {
            "action_id": result.action_id,
            "case_id": result.case_id,
            "success": result.success,
            "output": result.output,
            "error": result.error,
        }

    @staticmethod
    def _serialize_evaluation(evaluation: CaseEvaluation) -> dict[str, object]:
        return {
            "case_id": evaluation.case_id,
            "title": evaluation.title,
            "passed": evaluation.passed,
            "evidence": evaluation.evidence,
            "mismatches": evaluation.mismatches,
        }
