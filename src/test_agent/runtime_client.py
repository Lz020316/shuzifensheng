"""Real execution runtime client with browser/API/DB capabilities."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from .db_readonly import execute_read_only_query

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]{2,}")


@dataclass(slots=True)
class PlaywrightRuntimeClient:
    """Run action points against real targets with evidence artifacts."""

    base_url: str = ""
    db_url: str = ""
    db_path: str = ""
    artifacts_dir: str = "artifacts"
    storage_state_path: str = ""
    persist_storage_state: bool = True
    headless: bool = True
    browser_timeout_ms: int = 10_000
    api_timeout_seconds: int = 12
    api_retry_count: int = 1
    state: dict[str, Any] = field(default_factory=dict)
    _playwright: Any = field(default=None, init=False, repr=False)
    _browser: Any = field(default=None, init=False, repr=False)
    _context: Any = field(default=None, init=False, repr=False)
    _page: Any = field(default=None, init=False, repr=False)
    _step_index: int = field(default=0, init=False, repr=False)

    def invoke(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        """Invoke one action and return structured result payload."""
        handler = getattr(self, f"_handle_{action}", None)
        if handler is None:
            return {"ok": False, "error": f"unsupported action: {action}"}
        try:
            self._step_index += 1
            payload = handler(params)
            screenshot = self._try_capture_screenshot(action)
            if screenshot:
                payload["evidence"] = {"screenshot": screenshot}
            return payload
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{action} 执行失败: {exc}"}

    def reset_state(self) -> None:
        """Reset mutable state between test cases."""
        self.state.clear()
        self._step_index = 0
        self._close_page_objects()

    def close(self) -> None:
        """Close runtime resources."""
        self._close_page_objects()
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def _handle_open_page(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._ensure_page()
        raw_url = str(params.get("url", "")).strip()
        if not raw_url:
            return {"ok": False, "error": "url is required"}
        target_url = self._resolve_url(raw_url)
        page.goto(target_url, wait_until="domcontentloaded", timeout=self.browser_timeout_ms)
        title = page.title()
        body_text = page.locator("body").inner_text(timeout=self.browser_timeout_ms)
        self.state["current_url"] = target_url
        self.state["page_title"] = title
        self.state["page_text"] = body_text
        return {"ok": True, "url": target_url, "title": title}

    def _handle_input_text(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._ensure_page()
        selector = str(params.get("selector", "")).strip()
        field = str(params.get("field", "")).strip()
        value = str(params.get("value", ""))
        if not selector:
            selector = self._guess_input_selector(field)
        if not selector:
            return {"ok": False, "error": "input selector unresolved"}
        page.locator(selector).first.fill(value, timeout=self.browser_timeout_ms)
        return {"ok": True, "selector": selector, "field": field}

    def _handle_click(self, params: dict[str, Any]) -> dict[str, Any]:
        page = self._ensure_page()
        selector = str(params.get("selector", "")).strip()
        target = str(params.get("target", "")).strip()
        if not selector:
            selector = self._guess_click_selector(target)
        if not selector:
            return {"ok": False, "error": "click selector unresolved"}
        page.locator(selector).first.click(timeout=self.browser_timeout_ms)
        page.wait_for_timeout(200)
        self.state["page_text"] = page.locator("body").inner_text(timeout=self.browser_timeout_ms)
        self.state["page_title"] = page.title()
        if target.lower() in {"login", "signin"}:
            self._save_storage_state_if_enabled()
        return {"ok": True, "selector": selector, "target": target}

    def _handle_load_requirement_context(self, params: dict[str, Any]) -> dict[str, Any]:
        source = str(params.get("source", "inline-text"))
        content = str(params.get("content", ""))
        self.state["source"] = source
        self.state["requirement_text"] = content
        return {"ok": True, "source": source}

    def _handle_call_api(self, params: dict[str, Any]) -> dict[str, Any]:
        endpoint = str(params.get("endpoint", "")).strip()
        if not endpoint:
            return {"ok": False, "error": "endpoint is required"}
        url = self._resolve_url(endpoint)
        method = str(params.get("method", "GET")).upper()
        expected_status = int(params.get("expected_status", 200))
        payload_obj = params.get("json")
        payload = None
        headers = {"User-Agent": "auto-test-agent/0.3"}
        if payload_obj is not None:
            payload = json.dumps(payload_obj).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(url=url, method=method, data=payload, headers=headers)
        body = ""
        status_code = 0
        last_error = ""
        attempts = max(1, self.api_retry_count)
        for _ in range(attempts):
            try:
                with urlopen(request, timeout=self.api_timeout_seconds) as response:  # noqa: S310
                    status_code = getattr(response, "status", 200)
                    body = response.read().decode("utf-8", errors="replace")
                last_error = ""
                break
            except HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                status_code = exc.code
                last_error = f"HTTP {exc.code}"
                break
            except URLError as exc:
                last_error = f"API 网络错误: {exc.reason}"
            except OSError as exc:
                last_error = f"API 调用失败: {exc}"
        if last_error and status_code == 0:
            return {"ok": False, "error": last_error}

        self.state["last_api_response"] = body
        self.state["last_api_status"] = status_code
        ok = status_code == expected_status
        return {
            "ok": ok,
            "url": url,
            "status_code": status_code,
            "expected_status": expected_status,
            "body_excerpt": body[:300],
            "error": "" if ok else f"状态码不匹配: {status_code} != {expected_status}",
        }

    def _handle_query_db(self, params: dict[str, Any]) -> dict[str, Any]:
        sql = str(params.get("sql", "")).strip()
        db_url = str(params.get("db_url", "")).strip() or self.db_url
        db_path = str(params.get("db_path", "")).strip() or self.db_path
        try:
            result = execute_read_only_query(
                sql=sql,
                db_url=db_url,
                sqlite_path=db_path,
                limit=20,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

        self.state["last_db_rows"] = result.rows
        return {
            "ok": True,
            "columns": result.columns,
            "row_count": len(result.rows),
            "rows": result.rows,
        }

    def _handle_save_storage_state(self, params: dict[str, Any]) -> dict[str, Any]:
        target_path = str(params.get("path", "")).strip() or self.storage_state_path
        if not target_path:
            return {"ok": False, "error": "storage_state_path is required"}
        page = self._ensure_page()
        _ = page  # ensure context exists
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=target_path)
        self.state["storage_state_path"] = target_path
        return {"ok": True, "path": target_path}

    def _handle_assert_expectation(self, params: dict[str, Any]) -> dict[str, Any]:
        expected = str(params.get("expected", "")).strip()
        if not expected:
            return {"ok": True, "reason": "no expectation provided"}
        evidence_haystack = "\n".join(
            [
                str(self.state.get("page_title", "")),
                str(self.state.get("page_text", "")),
                str(self.state.get("requirement_text", "")),
                str(self.state.get("last_api_response", "")),
                json.dumps(self.state.get("last_db_rows", []), ensure_ascii=False),
            ]
        )
        tokens = self._tokenize(expected)
        if not tokens:
            return {"ok": True, "reason": "expectation tokenization empty"}
        lowered = evidence_haystack.lower()
        hit_count = sum(1 for token in tokens if token.lower() in lowered)
        threshold = max(1, len(tokens) // 2)
        ok = hit_count >= threshold
        return {
            "ok": ok,
            "hit_count": hit_count,
            "threshold": threshold,
            "error": "" if ok else "断言命中不足",
            "evidence_excerpt": evidence_haystack[:300],
        }

    def _ensure_page(self) -> Any:
        self._ensure_browser()
        if self._context is None:
            storage_path = self._resolve_storage_state_path()
            if storage_path and Path(storage_path).exists():
                self._context = self._browser.new_context(
                    ignore_https_errors=True,
                    storage_state=storage_path,
                )
            else:
                self._context = self._browser.new_context(ignore_https_errors=True)
        if self._page is None:
            self._page = self._context.new_page()
            self._page.set_default_timeout(self.browser_timeout_ms)
        return self._page

    def _ensure_browser(self) -> None:
        if self._browser is not None:
            return
        try:
            from playwright.sync_api import sync_playwright  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError(
                "Playwright 未安装。请执行: python3 -m pip install -e '.[playwright]' "
                "并运行: python3 -m playwright install chromium"
            ) from exc
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)

    def _close_page_objects(self) -> None:
        if self._page is not None:
            self._page.close()
            self._page = None
        if self._context is not None:
            self._context.close()
            self._context = None

    def _resolve_url(self, url: str) -> str:
        if url.startswith(("http://", "https://")):
            return url
        if not self.base_url:
            raise ValueError(f"relative url requires base_url: {url}")
        return urljoin(self.base_url.rstrip("/") + "/", url.lstrip("/"))

    def _try_capture_screenshot(self, action: str) -> str:
        if self._page is None:
            return ""
        artifact_root = Path(self.artifacts_dir)
        artifact_root.mkdir(parents=True, exist_ok=True)
        screenshot_path = artifact_root / f"step-{self._step_index:03d}-{action}.png"
        self._page.screenshot(path=str(screenshot_path), full_page=True)
        return str(screenshot_path)

    def _resolve_storage_state_path(self) -> str:
        return self.storage_state_path.strip()

    def _save_storage_state_if_enabled(self) -> None:
        if not self.persist_storage_state:
            return
        storage_path = self._resolve_storage_state_path()
        if not storage_path or self._context is None:
            return
        Path(storage_path).parent.mkdir(parents=True, exist_ok=True)
        self._context.storage_state(path=storage_path)

    @staticmethod
    def _guess_input_selector(field: str) -> str:
        normalized = field.lower()
        mapping = {
            "username": "input[name='username'], input#username, input[type='email']",
            "password": "input[name='password'], input#password, input[type='password']",
            "search": "input[name='search'], input[type='search'], input#search",
        }
        return mapping.get(normalized, f"input[name='{field}'], input#{field}")

    @staticmethod
    def _guess_click_selector(target: str) -> str:
        normalized = target.lower()
        mapping = {
            "login": "button[type='submit'], button[name='login'], button#login",
            "search": "button[name='search'], button#search, button[type='submit']",
        }
        return mapping.get(normalized, f"button[name='{target}'], button#{target}")

    @staticmethod
    def _tokenize(text: str) -> list[str]:
        return _TOKEN_RE.findall(text)
