from pathlib import Path
import time

from test_agent.storage import TaskRepository
from test_agent.worker import RunJobWorkerPool


def test_worker_pool_retries_failed_job(tmp_path: Path) -> None:
    db_file = tmp_path / "agent.db"
    repository = TaskRepository(db_file=str(db_file))
    task = repository.create_task(
        source="系统需要支持用户登录",
        runtime_mode="mock",
        config={},
    )
    job = repository.create_run_job(task_id=task.task_id, max_attempts=2)
    attempts = {"count": 0}

    def execute_task_fn(task_record, override_source):  # noqa: ANN001
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary failure")
        report = {"status": "ok", "summary": {"passed_count": 1}, "errors": []}
        return repository.create_run(task_id=task_record.task_id, status="ok", report=report)

    pool = RunJobWorkerPool(
        repository=repository,
        execute_task_fn=execute_task_fn,
        worker_count=1,
        poll_interval_seconds=0.05,
    )
    pool.start()
    try:
        deadline = time.time() + 5
        final_job = None
        while time.time() < deadline:
            final_job = repository.get_run_job(job.job_id)
            if final_job and final_job.status in {"succeeded", "failed"}:
                break
            time.sleep(0.1)
    finally:
        pool.stop()

    assert final_job is not None
    assert final_job.status == "succeeded"
    assert final_job.attempt_count >= 2


def test_worker_retry_backoff_growth() -> None:
    assert RunJobWorkerPool._compute_retry_delay_seconds(1) == 0.4
    assert RunJobWorkerPool._compute_retry_delay_seconds(2) == 0.8
    assert RunJobWorkerPool._compute_retry_delay_seconds(5) <= 8.0
