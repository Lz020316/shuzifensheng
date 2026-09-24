import json
from pathlib import Path

from test_agent.storage import TaskRepository


def test_task_repository_persists_tasks_and_runs(tmp_path: Path) -> None:
    db_file = tmp_path / "agent.db"
    repository = TaskRepository(db_file=str(db_file))

    task = repository.create_task(
        source="系统需要支持用户登录",
        runtime_mode="mock",
        config={"base_url": "", "allowed_domains": []},
    )
    assert task.task_id > 0

    loaded_task = repository.get_task(task.task_id)
    assert loaded_task is not None
    assert loaded_task.source == task.source

    report = {"status": "ok", "summary": {"passed_count": 1}, "errors": []}
    run = repository.create_run(task_id=task.task_id, status="ok", report=report)
    assert run.run_id > 0

    loaded_run = repository.get_run(run.run_id)
    assert loaded_run is not None
    payload = json.loads(loaded_run.report_json)
    assert payload["status"] == "ok"

    runs = repository.list_runs(task_id=task.task_id)
    assert len(runs) == 1

    job = repository.create_run_job(task_id=task.task_id, max_attempts=2)
    assert job.status == "queued"
    claimed = repository.claim_next_job()
    assert claimed is not None
    assert claimed.job_id == job.job_id
    assert claimed.status == "running"

    repository.mark_run_job_failed(job.job_id, "temporary error", retry=True)
    queued_again = repository.get_run_job(job.job_id)
    assert queued_again is not None
    assert queued_again.status == "queued"

    claimed_again = repository.claim_next_job()
    assert claimed_again is not None
    repository.mark_run_job_succeeded(job.job_id, run_id=run.run_id)
    done = repository.get_run_job(job.job_id)
    assert done is not None
    assert done.status == "succeeded"
