"""Plan MCP action points from generated test cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import ActionPoint, InputArtifact, TestCase


@dataclass(slots=True)
class ActionPlanner:
    """Convert test cases into executable MCP action points."""

    def plan(self, artifact: InputArtifact, cases: list[TestCase]) -> list[ActionPoint]:
        """Return ordered action points for all test cases."""
        actions: list[ActionPoint] = []
        action_counter = 1
        for case in cases:
            case_actions = self._plan_case_actions(artifact=artifact, case=case)
            for action, params in case_actions:
                actions.append(
                    ActionPoint(
                        action_id=f"AP-{action_counter:03d}",
                        case_id=case.case_id,
                        action=action,
                        params=params,
                    )
                )
                action_counter += 1
        return actions

    def _plan_case_actions(
        self, artifact: InputArtifact, case: TestCase
    ) -> list[tuple[str, dict[str, Any]]]:
        actions: list[tuple[str, dict[str, Any]]] = []
        if artifact.kind == "website":
            actions.append(("open_page", {"url": artifact.identifier}))
        else:
            actions.append(("load_requirement_context", {"source": artifact.identifier}))

        expected = case.expected_result
        lowered = expected.lower()

        if any(token in lowered for token in ("登录", "login", "signin")):
            actions.extend(
                [
                    ("input_text", {"field": "username", "value": "test-user"}),
                    ("input_text", {"field": "password", "value": "pass-1234"}),
                    ("click", {"target": "login"}),
                ]
            )

        if any(token in lowered for token in ("搜索", "search", "查询")):
            actions.extend(
                [
                    ("input_text", {"field": "search", "value": "测试关键字"}),
                    ("click", {"target": "search"}),
                ]
            )

        actions.append(("assert_expectation", {"expected": expected}))
        return actions
