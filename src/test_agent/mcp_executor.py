"""MCP invocation abstractions and local mock executor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from .models import ActionPoint, MCPCallResult


class MCPClient(Protocol):
    """Protocol for an MCP invoker."""

    def invoke(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Invoke an action via MCP and return structured payload."""


@dataclass(slots=True)
class LocalMockMCPClient:
    """In-memory MCP mock used for local runs and tests."""

    state: dict[str, Any] = field(default_factory=dict)

    def invoke(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        handler = getattr(self, f"_handle_{action}", None)
        if handler is None:
            return {"ok": False, "error": f"unsupported action: {action}"}
        return handler(params)

    def _handle_open_page(self, params: dict[str, Any]) -> dict[str, Any]:
        url = str(params.get("url", ""))
        self.state["current_url"] = url
        self.state.setdefault("page_text", f"Mock page for {url}")
        return {"ok": True, "url": url}

    def _handle_load_requirement_context(self, params: dict[str, Any]) -> dict[str, Any]:
        source = str(params.get("source", "inline-text"))
        self.state["source"] = source
        return {"ok": True, "source": source}

    def _handle_input_text(self, params: dict[str, Any]) -> dict[str, Any]:
        field = str(params.get("field", ""))
        value = str(params.get("value", ""))
        inputs = self.state.setdefault("inputs", {})
        inputs[field] = value
        return {"ok": True, "field": field}

    def _handle_click(self, params: dict[str, Any]) -> dict[str, Any]:
        target = str(params.get("target", ""))
        self.state["last_click"] = target
        if target == "login":
            username = self.state.get("inputs", {}).get("username")
            password = self.state.get("inputs", {}).get("password")
            self.state["logged_in"] = bool(username and password)
        return {"ok": True, "target": target}

    def _handle_assert_expectation(self, params: dict[str, Any]) -> dict[str, Any]:
        expected = str(params.get("expected", ""))
        page_text = str(self.state.get("page_text", ""))
        success = self._is_expectation_satisfied(expected=expected, page_text=page_text)
        return {
            "ok": success,
            "expected": expected,
            "page_text_excerpt": page_text[:120],
        }

    @staticmethod
    def _is_expectation_satisfied(expected: str, page_text: str) -> bool:
        if not expected.strip():
            return True
        expected_tokens = [token for token in expected.split() if len(token) >= 2]
        if not expected_tokens:
            return True
        lowered_page = page_text.lower()
        return any(token.lower() in lowered_page for token in expected_tokens[:4])


@dataclass(slots=True)
class MCPExecutor:
    """Execute planned action points through an MCP client."""

    client: MCPClient

    def execute(self, actions: list[ActionPoint]) -> list[MCPCallResult]:
        """Execute actions one by one and return their results."""
        results: list[MCPCallResult] = []
        for action in actions:
            payload = self.client.invoke(action.action, action.params)
            ok = bool(payload.get("ok"))
            error = ""
            if not ok:
                error = str(payload.get("error", "action failed"))
            results.append(
                MCPCallResult(
                    action_id=action.action_id,
                    case_id=action.case_id,
                    success=ok,
                    output=payload,
                    error=error,
                )
            )
        return results
