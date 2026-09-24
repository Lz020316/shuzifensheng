"""MCP invocation abstractions and local mock executor."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .models import ActionPoint, MCPCallResult

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}")


class MCPClient(Protocol):
    """Protocol for an MCP invoker."""

    def invoke(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Invoke an action via MCP and return structured payload."""


@dataclass(slots=True)
class HttpMCPClient:
    """HTTP-based MCP client for integrating with real services."""

    endpoint: str
    timeout_seconds: int = 15
    bearer_token: str = ""

    def invoke(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps({"action": action, "params": params}).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "auto-test-agent/0.2",
        }
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"

        request = Request(
            url=self.endpoint,
            data=payload,
            headers=headers,
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:  # noqa: S310
                content = response.read().decode("utf-8", errors="replace")
        except HTTPError as exc:
            return {"ok": False, "error": f"HTTP {exc.code}: {exc.reason}"}
        except URLError as exc:
            return {"ok": False, "error": f"MCP 网络错误: {exc.reason}"}
        except OSError as exc:
            return {"ok": False, "error": f"MCP 请求失败: {exc}"}

        try:
            decoded = json.loads(content)
        except json.JSONDecodeError:
            return {"ok": False, "error": "MCP 返回了非 JSON 响应", "raw": content[:300]}

        if not isinstance(decoded, dict):
            return {"ok": False, "error": "MCP 返回格式错误，预期对象"}
        decoded.setdefault("ok", False)
        return decoded


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
        expected_title = str(params.get("expected_title", "")).strip()
        self.state["current_url"] = url
        self.state["page_title"] = expected_title or url
        self.state["page_text"] = (
            f"页面加载成功 可见内容 核心业务关键词 {self.state['page_title']} {url}"
        )
        return {"ok": True, "url": url}

    def _handle_load_requirement_context(self, params: dict[str, Any]) -> dict[str, Any]:
        source = str(params.get("source", "inline-text"))
        content = str(params.get("content", "")).strip()
        self.state["source"] = source
        if content:
            self.state["page_text"] = content
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
            if self.state["logged_in"]:
                self.state["page_text"] = f"{self.state.get('page_text', '')} 登录成功"
        if target == "search":
            self.state["page_text"] = f"{self.state.get('page_text', '')} 搜索结果 测试关键字"
        return {"ok": True, "target": target}

    def _handle_call_api(self, params: dict[str, Any]) -> dict[str, Any]:
        endpoint = str(params.get("endpoint", "/api/mock"))
        return {"ok": True, "endpoint": endpoint, "status_code": 200}

    def _handle_query_db(self, params: dict[str, Any]) -> dict[str, Any]:
        sql = str(params.get("sql", "SELECT 1"))
        return {"ok": True, "sql": sql, "rows": 1}

    def _handle_assert_expectation(self, params: dict[str, Any]) -> dict[str, Any]:
        expected = str(params.get("expected", ""))
        page_text = str(self.state.get("page_text", ""))
        page_title = str(self.state.get("page_title", ""))
        success = self._is_expectation_satisfied(
            expected=expected,
            page_text=page_text,
            page_title=page_title,
            current_url=str(self.state.get("current_url", "")),
        )
        return {
            "ok": success,
            "expected": expected,
            "page_text_excerpt": page_text[:120],
            "page_title": page_title,
        }

    def reset_state(self) -> None:
        """Reset local state between test cases to avoid cross-case pollution."""
        self.state.clear()

    @staticmethod
    def _is_expectation_satisfied(
        expected: str,
        page_text: str,
        page_title: str,
        current_url: str,
    ) -> bool:
        if not expected.strip():
            return True

        expected_lower = expected.lower()
        if "页面加载成功" in expected:
            return bool(current_url) or "页面加载成功" in page_text

        if "页面标题包含" in expected:
            target = expected.replace("页面标题包含", "").strip("“”\"' ")
            if not target:
                return bool(page_title)
            return target.lower() in page_title.lower()

        expected_tokens = LocalMockMCPClient._tokenize(expected)
        if not expected_tokens:
            return True

        lowered_page = f"{page_text}\n{page_title}".lower()
        hits = sum(1 for token in expected_tokens if token.lower() in lowered_page)
        threshold = max(1, len(expected_tokens) // 2)
        if "should" in expected_lower or "must" in expected_lower:
            threshold = max(1, (len(expected_tokens) * 2) // 3)
        return hits >= threshold

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return _TOKEN_RE.findall(text)


@dataclass(slots=True)
class MCPExecutor:
    """Execute planned action points through an MCP client."""

    client: MCPClient

    def execute(self, actions: list[ActionPoint]) -> list[MCPCallResult]:
        """Execute actions one by one and return their results."""
        results: list[MCPCallResult] = []
        for action in actions:
            try:
                payload = self.client.invoke(action.action, action.params)
            except Exception as exc:  # noqa: BLE001
                payload = {"ok": False, "error": f"未捕获执行异常: {exc}"}
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
