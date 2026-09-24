"""Scenario-oriented automation testing workflow agent."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any

from .action_planner import ActionPlanner
from .case_generator import TestCaseGenerator
from .mcp_executor import HttpMCPClient, LocalMockMCPClient, MCPExecutor
from .models import ActionPoint, CaseEvaluation, MCPCallResult, TestCase
from .runtime_client import PlaywrightRuntimeClient
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
    def default(
        cls,
        *,
        runtime_mode: str = "mock",
        base_url: str = "",
        db_path: str = "",
        artifacts_dir: str = "artifacts",
        browser_headless: bool = True,
        mcp_endpoint: str | None = None,
        mcp_token: str = "",
        allow_private_url: bool = False,
        allowed_domains: tuple[str, ...] = (),
    ) -> "WorkflowTestAgent":
        """Construct workflow agent with built-in components."""
        if mcp_endpoint:
            client = HttpMCPClient(endpoint=mcp_endpoint, bearer_token=mcp_token)
        elif runtime_mode == "playwright":
            client = PlaywrightRuntimeClient(
                base_url=base_url,
                db_path=db_path,
                artifacts_dir=artifacts_dir,
                headless=browser_headless,
            )
        else:
            client = LocalMockMCPClient()

        return cls(
            source_loader=SourceLoader(
                allow_private_network=allow_private_url,
                allowed_domains=allowed_domains,
            ),
            case_generator=TestCaseGenerator(),
            action_planner=ActionPlanner(),
            executor=MCPExecutor(client=client),
            verifier=ResultVerifier(),
        )

    def run(self, source: str) -> dict[str, object]:
        """Run one complete workflow and return report payload."""
        stage = "source_loading"
        artifact = None
        cases: list[TestCase] = []
        actions: list[ActionPoint] = []
        call_results: list[MCPCallResult] = []
        evaluations: list[CaseEvaluation] = []

        try:
            artifact = self.source_loader.load(source)

            stage = "test_case_generation"
            cases = self.case_generator.generate(artifact)

            stage = "action_planning"
            actions = self.action_planner.plan(artifact=artifact, cases=cases)

            stage = "mcp_execution"
            call_results = self._execute_with_case_isolation(actions=actions, cases=cases)

            stage = "verification"
            evaluations = self.verifier.verify(
                cases=cases,
                actions=actions,
                results=call_results,
            )
        except Exception as exc:  # noqa: BLE001
            return self._error_report(
                source=source,
                stage=stage,
                error=exc,
                artifact=artifact,
                cases=cases,
                actions=actions,
                call_results=call_results,
                evaluations=evaluations,
            )
        finally:
            close_fn = getattr(self.executor.client, "close", None)
            if callable(close_fn):
                close_fn()

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "ok",
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
            "artifacts": self._collect_artifacts(call_results),
            "errors": [],
        }

    def to_json(self, report: dict[str, object]) -> str:
        """Serialize workflow report to JSON."""
        return json.dumps(report, ensure_ascii=False, indent=2)

    def _execute_with_case_isolation(
        self,
        actions: list[ActionPoint],
        cases: list[TestCase],
    ) -> list[MCPCallResult]:
        all_results: list[MCPCallResult] = []
        for case in cases:
            case_actions = [item for item in actions if item.case_id == case.case_id]
            reset_fn = getattr(self.executor.client, "reset_state", None)
            if callable(reset_fn):
                reset_fn()
            all_results.extend(self.executor.execute(case_actions))
        return all_results

    def _error_report(
        self,
        *,
        source: str,
        stage: str,
        error: Exception,
        artifact: Any,
        cases: list[TestCase],
        actions: list[ActionPoint],
        call_results: list[MCPCallResult],
        evaluations: list[CaseEvaluation],
    ) -> dict[str, object]:
        input_section = {
            "kind": "unknown",
            "identifier": source,
            "metadata": {},
        }
        if artifact is not None:
            input_section = {
                "kind": getattr(artifact, "kind", "unknown"),
                "identifier": getattr(artifact, "identifier", source),
                "metadata": getattr(artifact, "metadata", {}),
            }

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "status": "error",
            "input": input_section,
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
            "artifacts": self._collect_artifacts(call_results),
            "errors": [
                {
                    "stage": stage,
                    "message": str(error),
                    "type": error.__class__.__name__,
                }
            ],
        }

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

    @staticmethod
    def _collect_artifacts(results: list[MCPCallResult]) -> list[dict[str, str]]:
        artifacts: list[dict[str, str]] = []
        for item in results:
            evidence = item.output.get("evidence")
            if not isinstance(evidence, dict):
                continue
            screenshot = evidence.get("screenshot")
            if isinstance(screenshot, str) and screenshot:
                artifacts.append(
                    {
                        "action_id": item.action_id,
                        "case_id": item.case_id,
                        "type": "screenshot",
                        "path": screenshot,
                    }
                )
        return artifacts
