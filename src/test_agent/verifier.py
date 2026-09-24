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
            has_assert_action = False
            assert_passed = False

            for action in case_actions:
                call_result = result_by_action.get(action.action_id)
                if call_result is None:
                    passed = False
                    mismatches.append(f"{action.action_id} 缺少执行结果")
                    continue
                if call_result.success:
                    evidence.append(f"{action.action_id}:{action.action} 执行成功")
                    if action.action == "assert_expectation":
                        has_assert_action = True
                        assert_passed = True
                else:
                    passed = False
                    detail = call_result.error or "执行失败"
                    mismatches.append(f"{action.action_id}:{action.action} -> {detail}")
                    if action.action == "assert_expectation":
                        has_assert_action = True

            if not has_assert_action:
                passed = False
                mismatches.append("缺少 assert_expectation 动作，无法核对预期结果")
            elif not assert_passed:
                passed = False
                mismatches.append("断言动作未通过，预期结果未被满足")

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
