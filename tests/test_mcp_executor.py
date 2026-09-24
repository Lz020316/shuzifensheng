import json

from test_agent.mcp_executor import HttpMCPClient, LocalMockMCPClient


class _FakeHTTPResponse:
    def __init__(self, payload: str) -> None:
        self._payload = payload.encode("utf-8")

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def read(self) -> bytes:
        return self._payload


def test_http_mcp_client_parses_json_response(monkeypatch) -> None:
    payload = json.dumps({"ok": True, "result": {"status": "done"}})

    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeHTTPResponse(payload)

    monkeypatch.setattr("test_agent.mcp_executor.urlopen", fake_urlopen)
    client = HttpMCPClient(endpoint="https://mcp.example.internal/execute")

    result = client.invoke("assert_expectation", {"expected": "系统应支持登录"})
    assert result["ok"] is True
    assert result["result"]["status"] == "done"


def test_http_mcp_client_handles_non_json_response(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeHTTPResponse("NOT_JSON")

    monkeypatch.setattr("test_agent.mcp_executor.urlopen", fake_urlopen)
    client = HttpMCPClient(endpoint="https://mcp.example.internal/execute")
    result = client.invoke("assert_expectation", {"expected": "系统应支持登录"})

    assert result["ok"] is False
    assert "非 JSON" in result["error"]


def test_local_mock_supports_chinese_expectation_without_whitespace() -> None:
    client = LocalMockMCPClient()
    client.invoke(
        "load_requirement_context",
        {"source": "inline-text", "content": "系统需要支持用户登录并支持商品搜索"},
    )
    response = client.invoke(
        "assert_expectation",
        {"expected": "系统需要支持用户登录并支持商品搜索"},
    )
    assert response["ok"] is True
