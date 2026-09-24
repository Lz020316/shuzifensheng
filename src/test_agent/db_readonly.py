"""Read-only database query helpers for multiple engines."""

from __future__ import annotations

from dataclasses import dataclass
import re
import sqlite3
from typing import Any
from urllib.parse import parse_qs, urlparse

_DANGEROUS_SQL_RE = re.compile(
    r"\b(insert|update|delete|drop|alter|truncate|create|replace|grant|revoke)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class QueryResult:
    """Normalized query result."""

    columns: list[str]
    rows: list[list[Any]]


def ensure_read_only_sql(sql: str) -> None:
    """Validate SQL is read-only and does not contain dangerous statements."""
    normalized = sql.strip()
    if not normalized:
        raise ValueError("sql is required")
    lowered = normalized.lower()
    if not (lowered.startswith("select") or lowered.startswith("with ")):
        raise ValueError("只允许只读 SQL（SELECT/WITH）")
    if _DANGEROUS_SQL_RE.search(normalized):
        raise ValueError("SQL 包含潜在危险关键字，已拒绝执行")


def execute_read_only_query(
    *,
    sql: str,
    db_url: str = "",
    sqlite_path: str = "",
    limit: int = 20,
) -> QueryResult:
    """Execute read-only SQL against sqlite/postgresql/mysql based on db_url."""
    ensure_read_only_sql(sql)

    if db_url:
        parsed = urlparse(db_url)
        scheme = parsed.scheme.lower()
        if scheme in {"sqlite", "sqlite3"}:
            path = _sqlite_path_from_url(db_url)
            return _execute_sqlite(sql=sql, db_path=path, limit=limit)
        if scheme in {"postgres", "postgresql"}:
            return _execute_postgresql(sql=sql, db_url=db_url, limit=limit)
        if scheme in {"mysql"}:
            return _execute_mysql(sql=sql, db_url=db_url, limit=limit)
        raise ValueError(f"不支持的数据库协议: {scheme}")

    if sqlite_path:
        return _execute_sqlite(sql=sql, db_path=sqlite_path, limit=limit)

    raise ValueError("db_url 或 sqlite_path 至少提供一个")


def _execute_sqlite(*, sql: str, db_path: str, limit: int) -> QueryResult:
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        cursor = connection.execute(sql)
        rows = cursor.fetchmany(limit)
        columns = [item[0] for item in cursor.description or []]
    finally:
        connection.close()
    return QueryResult(columns=columns, rows=[list(row) for row in rows])


def _execute_postgresql(*, sql: str, db_url: str, limit: int) -> QueryResult:
    try:
        import psycopg  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "缺少 psycopg。请安装: python3 -m pip install 'psycopg[binary]'"
        ) from exc

    with psycopg.connect(db_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchmany(limit)
            columns = [item.name for item in cursor.description or []]
    return QueryResult(columns=columns, rows=[list(row) for row in rows])


def _execute_mysql(*, sql: str, db_url: str, limit: int) -> QueryResult:
    try:
        import pymysql  # type: ignore
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("缺少 pymysql。请安装: python3 -m pip install pymysql") from exc

    parsed = urlparse(db_url)
    query_params = parse_qs(parsed.query)
    charset = query_params.get("charset", ["utf8mb4"])[0]
    port = parsed.port or 3306
    database = parsed.path.lstrip("/")
    connection = pymysql.connect(  # type: ignore[call-arg]
        host=parsed.hostname or "localhost",
        user=parsed.username or "",
        password=parsed.password or "",
        db=database,
        port=port,
        charset=charset,
        cursorclass=pymysql.cursors.Cursor,
        read_timeout=10,
        write_timeout=10,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchmany(limit)
            columns = [item[0] for item in cursor.description or []]
    finally:
        connection.close()
    return QueryResult(columns=columns, rows=[list(row) for row in rows])


def _sqlite_path_from_url(db_url: str) -> str:
    parsed = urlparse(db_url)
    path = parsed.path
    if parsed.netloc and parsed.netloc != "":
        # sqlite:///path and sqlite://relative-path compatibility
        path = f"/{parsed.netloc}{path}"
    return path
