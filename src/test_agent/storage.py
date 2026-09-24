"""SQLite persistence for workflow tasks and run history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any


@dataclass(slots=True)
class TaskRecord:
    """Persisted workflow task definition."""

    task_id: int
    source: str
    runtime_mode: str
    config_json: str
    created_at: str


@dataclass(slots=True)
class RunRecord:
    """Persisted workflow run result."""

    run_id: int
    task_id: int
    status: str
    report_json: str
    created_at: str


@dataclass(slots=True)
class RunJobRecord:
    """Queued background job metadata."""

    job_id: int
    task_id: int
    override_source: str
    status: str
    max_attempts: int
    attempt_count: int
    run_id: int
    last_error: str
    created_at: str
    updated_at: str


class TaskRepository:
    """Simple SQLite-based repository for tasks and runs."""

    def __init__(self, db_file: str = "data/agent.db") -> None:
        self.db_file = db_file
        self._ensure_schema()

    def create_task(self, source: str, runtime_mode: str, config: dict[str, Any]) -> TaskRecord:
        created_at = datetime.now(timezone.utc).isoformat()
        config_json = json.dumps(config, ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks(source, runtime_mode, config_json, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (source, runtime_mode, config_json, created_at),
            )
            task_id = int(cursor.lastrowid)
        return TaskRecord(
            task_id=task_id,
            source=source,
            runtime_mode=runtime_mode,
            config_json=config_json,
            created_at=created_at,
        )

    def get_task(self, task_id: int) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT task_id, source, runtime_mode, config_json, created_at
                FROM tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return TaskRecord(
            task_id=row[0],
            source=row[1],
            runtime_mode=row[2],
            config_json=row[3],
            created_at=row[4],
        )

    def list_tasks(self, limit: int = 50) -> list[TaskRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT task_id, source, runtime_mode, config_json, created_at
                FROM tasks
                ORDER BY task_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [
            TaskRecord(
                task_id=item[0],
                source=item[1],
                runtime_mode=item[2],
                config_json=item[3],
                created_at=item[4],
            )
            for item in rows
        ]

    def create_run(self, task_id: int, status: str, report: dict[str, Any]) -> RunRecord:
        created_at = datetime.now(timezone.utc).isoformat()
        report_json = json.dumps(report, ensure_ascii=False)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO runs(task_id, status, report_json, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (task_id, status, report_json, created_at),
            )
            run_id = int(cursor.lastrowid)
        return RunRecord(
            run_id=run_id,
            task_id=task_id,
            status=status,
            report_json=report_json,
            created_at=created_at,
        )

    def get_run(self, run_id: int) -> RunRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT run_id, task_id, status, report_json, created_at
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return RunRecord(
            run_id=row[0],
            task_id=row[1],
            status=row[2],
            report_json=row[3],
            created_at=row[4],
        )

    def list_runs(self, task_id: int, limit: int = 100) -> list[RunRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT run_id, task_id, status, report_json, created_at
                FROM runs
                WHERE task_id = ?
                ORDER BY run_id DESC
                LIMIT ?
                """,
                (task_id, limit),
            ).fetchall()
        return [
            RunRecord(
                run_id=item[0],
                task_id=item[1],
                status=item[2],
                report_json=item[3],
                created_at=item[4],
            )
            for item in rows
        ]

    def create_run_job(
        self,
        *,
        task_id: int,
        override_source: str = "",
        max_attempts: int = 2,
    ) -> RunJobRecord:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO run_jobs(
                    task_id, override_source, status, max_attempts,
                    attempt_count, run_id, last_error, created_at, updated_at
                )
                VALUES(?, ?, 'queued', ?, 0, 0, '', ?, ?)
                """,
                (task_id, override_source, max_attempts, now, now),
            )
            job_id = int(cursor.lastrowid)
        return self.get_run_job(job_id)  # type: ignore[return-value]

    def get_run_job(self, job_id: int) -> RunJobRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    job_id, task_id, override_source, status, max_attempts,
                    attempt_count, run_id, last_error, created_at, updated_at
                FROM run_jobs
                WHERE job_id = ?
                """,
                (job_id,),
            ).fetchone()
        return self._row_to_job(row)

    def list_run_jobs(self, limit: int = 100) -> list[RunJobRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    job_id, task_id, override_source, status, max_attempts,
                    attempt_count, run_id, last_error, created_at, updated_at
                FROM run_jobs
                ORDER BY job_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        jobs: list[RunJobRecord] = []
        for row in rows:
            job = self._row_to_job(row)
            if job is not None:
                jobs.append(job)
        return jobs

    def claim_next_job(self) -> RunJobRecord | None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT
                    job_id, task_id, override_source, status, max_attempts,
                    attempt_count, run_id, last_error, created_at, updated_at
                FROM run_jobs
                WHERE status = 'queued'
                ORDER BY job_id ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None

            job_id = int(row[0])
            conn.execute(
                """
                UPDATE run_jobs
                SET status = 'running',
                    attempt_count = attempt_count + 1,
                    updated_at = ?
                WHERE job_id = ? AND status = 'queued'
                """,
                (now, job_id),
            )
            conn.execute("COMMIT")
        return self.get_run_job(job_id)

    def mark_run_job_succeeded(self, job_id: int, run_id: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE run_jobs
                SET status = 'succeeded', run_id = ?, updated_at = ?, last_error = ''
                WHERE job_id = ?
                """,
                (run_id, now, job_id),
            )

    def mark_run_job_failed(self, job_id: int, error: str, retry: bool) -> None:
        now = datetime.now(timezone.utc).isoformat()
        next_status = "queued" if retry else "failed"
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE run_jobs
                SET status = ?, last_error = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (next_status, error[:500], now, job_id),
            )

    def _ensure_schema(self) -> None:
        db_parent = Path(self.db_file).parent
        db_parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    runtime_mode TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS run_jobs (
                    job_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    override_source TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL,
                    max_attempts INTEGER NOT NULL DEFAULT 2,
                    attempt_count INTEGER NOT NULL DEFAULT 0,
                    run_id INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id),
                    FOREIGN KEY(run_id) REFERENCES runs(run_id)
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_file, timeout=20, isolation_level=None)

    @staticmethod
    def _row_to_job(row: Any) -> RunJobRecord | None:
        if row is None:
            return None
        return RunJobRecord(
            job_id=int(row[0]),
            task_id=int(row[1]),
            override_source=str(row[2]),
            status=str(row[3]),
            max_attempts=int(row[4]),
            attempt_count=int(row[5]),
            run_id=int(row[6]),
            last_error=str(row[7]),
            created_at=str(row[8]),
            updated_at=str(row[9]),
        )
