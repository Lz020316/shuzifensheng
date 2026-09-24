import sqlite3
from pathlib import Path

import pytest

from test_agent.db_readonly import execute_read_only_query


def test_execute_read_only_query_with_sqlite_path(tmp_path: Path) -> None:
    db_file = tmp_path / "demo.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items(name) VALUES('book')")
    conn.commit()
    conn.close()

    result = execute_read_only_query(
        sql="SELECT name FROM items",
        sqlite_path=str(db_file),
    )
    assert result.columns == ["name"]
    assert result.rows == [["book"]]


def test_execute_read_only_query_rejects_dangerous_sql(tmp_path: Path) -> None:
    db_file = tmp_path / "demo.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError):
        execute_read_only_query(
            sql="DELETE FROM items",
            sqlite_path=str(db_file),
        )
