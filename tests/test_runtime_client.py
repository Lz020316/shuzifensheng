import sqlite3
from pathlib import Path

from test_agent.runtime_client import PlaywrightRuntimeClient


class _FakeHTTPResponse:
    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body.encode("utf-8")
        self.status = status

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        return None

    def read(self) -> bytes:
        return self._body


def test_runtime_client_call_api_success(monkeypatch) -> None:
    def fake_urlopen(request, timeout):  # noqa: ANN001
        return _FakeHTTPResponse('{"ok": true}', status=200)

    monkeypatch.setattr("test_agent.runtime_client.urlopen", fake_urlopen)
    client = PlaywrightRuntimeClient(base_url="https://example.com")
    response = client.invoke(
        "call_api",
        {"endpoint": "/api/health", "method": "GET", "expected_status": 200},
    )
    assert response["ok"] is True
    assert response["status_code"] == 200


def test_runtime_client_query_db_read_only(tmp_path: Path) -> None:
    db_file = tmp_path / "demo.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO users(name) VALUES('alice')")
    conn.commit()
    conn.close()

    client = PlaywrightRuntimeClient(db_path=str(db_file))
    response = client.invoke("query_db", {"sql": "SELECT name FROM users"})
    assert response["ok"] is True
    assert response["row_count"] == 1

    denied = client.invoke("query_db", {"sql": "DELETE FROM users"})
    assert denied["ok"] is False
    assert "只允许只读 SQL" in denied["error"]


def test_runtime_client_assert_expectation_with_requirement_context() -> None:
    client = PlaywrightRuntimeClient()
    client.invoke(
        "load_requirement_context",
        {"source": "inline", "content": "系统需要支持订单查询与导出"},
    )
    response = client.invoke("assert_expectation", {"expected": "系统需要支持订单查询与导出"})
    assert response["ok"] is True
