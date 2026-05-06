"""Verify MCP execution results against generated test cases."""

from __future__ import annotations

from dataclasses import dataclass

from .models import ActionPoint, CaseEvaluation, MCPCallResult, TestCase


@dataclass(slots=True)
class ResultVerifier:
    """Evaluate whether each test case has passed."""

    def verify(
        self,
        cases: list[TestCase],
        actions: list[ActionPoint],
        results: list[MCPCallResult],
    ) -> list[CaseEvaluation]:
        """Verify each case with action and execution outcomes."""
        result_by_action = {item.action_id: item for item in results}
        evaluations: list[CaseEvaluation] = []

        for case in cases:
            case_actions = [action for action in actions if action.case_id == case.case_id]
            evidence: list[str] = []
            mismatches: list[str] = []
            passed = True

            for action in case_actions:
                call_result = result_by_action.get(action.action_id)
                if call_result is None:
                    passed = False
                    mismatches.append(f"{action.action_id} 缺少执行结果")
                    continue
                if call_result.success:
                    evidence.append(f"{action.action_id}:{action.action} 执行成功")
                else:
                    passed = False
                    detail = call_result.error or "执行失败"
                    mismatches.append(f"{action.action_id}:{action.action} -> {detail}")

            evaluations.append(
                CaseEvaluation(
                    case_id=case.case_id,
                    title=case.title,
                    passed=passed,
                    evidence=evidence,
                    mismatches=mismatches,
                )
            )
        return evaluations
