"""FastAPI service for task execution and report querying."""

from __future__ import annotations

from dataclasses import asdict
from contextlib import asynccontextmanager
import json
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from .reporting import render_report_html
from .storage import RunJobRecord, RunRecord, TaskRecord, TaskRepository
from .workflow import WorkflowTestAgent
from .worker import RunJobWorkerPool

DEFAULT_DB_FILE = "data/agent.db"


class TaskCreateRequest(BaseModel):
    """Request body for creating a workflow task."""

    source: str = Field(min_length=1)
    runtime_mode: Literal["mock", "playwright"] = "mock"
    mcp_endpoint: str | None = None
    mcp_token: str = ""
    allow_private_url: bool = False
    allowed_domains: list[str] = Field(default_factory=list)
    base_url: str = ""
    db_url: str = ""
    db_path: str = ""
    artifacts_dir: str = "artifacts"
    storage_state_path: str = ""
    persist_storage_state: bool = True
    browser_headless: bool = True
    auto_run: bool = True
    auto_run_async: bool = False
    max_attempts: int = Field(default=2, ge=1, le=10)
    queue_priority: int = Field(default=100, ge=1, le=1000)


class TaskRunRequest(BaseModel):
    """Request body for triggering a task run."""

    override_source: str | None = None


class RunJobCreateRequest(BaseModel):
    """Request body for enqueueing a background run job."""

    override_source: str = ""
    max_attempts: int = Field(default=2, ge=1, le=10)
    priority: int = Field(default=100, ge=1, le=1000)


class RunJobCancelRequest(BaseModel):
    """Request body for canceling run jobs."""

    reason: str = ""


def create_app(
    db_file: str = DEFAULT_DB_FILE,
    worker_count: int = 2,
    poll_interval_seconds: float = 0.5,
) -> FastAPI:
    """Create and configure FastAPI app."""
    repository = TaskRepository(db_file=db_file)
    worker_pool = RunJobWorkerPool(
        repository=repository,
        execute_task_fn=lambda task, override_source: _execute_task(
            repository=repository,
            task=task,
            override_source=override_source,
        ),
        worker_count=worker_count,
        poll_interval_seconds=poll_interval_seconds,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[override]
        worker_pool.start()
        yield
        worker_pool.stop()

    app = FastAPI(title="Auto Test Agent API", version="0.2.0", lifespan=lifespan)
    artifacts_dir = Path("artifacts")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/artifacts", StaticFiles(directory=str(artifacts_dir)), name="artifacts")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/tasks")
    def create_task(request: TaskCreateRequest) -> dict[str, Any]:
        config = request.model_dump()
        source = config.pop("source")
        runtime_mode = config.pop("runtime_mode")
        auto_run = bool(config.pop("auto_run"))
        auto_run_async = bool(config.pop("auto_run_async"))
        max_attempts = int(config.pop("max_attempts"))
        queue_priority = int(config.pop("queue_priority"))
        task = repository.create_task(source=source, runtime_mode=runtime_mode, config=config)
        response: dict[str, Any] = {"task": _serialize_task(task)}
        if auto_run and auto_run_async:
            job = repository.create_run_job(
                task_id=task.task_id,
                max_attempts=max_attempts,
                priority=queue_priority,
            )
            response["job"] = _serialize_run_job(job)
        elif auto_run:
            run = _execute_task(repository=repository, task=task)
            response["run"] = _serialize_run(run)
        return response

    @app.get("/tasks")
    def list_tasks(limit: int = Query(default=50, ge=1, le=500)) -> dict[str, Any]:
        tasks = repository.list_tasks(limit=limit)
        return {"items": [_serialize_task(item) for item in tasks]}

    @app.get("/tasks/{task_id}")
    def get_task(task_id: int) -> dict[str, Any]:
        task = repository.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        return {"task": _serialize_task(task)}

    @app.post("/tasks/{task_id}/runs")
    def run_task(task_id: int, request: TaskRunRequest) -> dict[str, Any]:
        task = repository.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        run = _execute_task(
            repository=repository,
            task=task,
            override_source=request.override_source or "",
        )
        return {"task": _serialize_task(task), "run": _serialize_run(run)}

    @app.post("/tasks/{task_id}/run-jobs")
    def enqueue_run_job(task_id: int, request: RunJobCreateRequest) -> dict[str, Any]:
        task = repository.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        job = repository.create_run_job(
            task_id=task_id,
            override_source=request.override_source,
            max_attempts=request.max_attempts,
            priority=request.priority,
        )
        return {"task": _serialize_task(task), "job": _serialize_run_job(job)}

    @app.post("/run-jobs/{job_id}/cancel")
    def cancel_run_job(job_id: int, request: RunJobCancelRequest) -> dict[str, Any]:
        job = repository.request_cancel_run_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="run job not found")
        if request.reason and job.status == "canceled":
            repository.mark_run_job_canceled(job_id, reason=request.reason)
            job = repository.get_run_job(job_id) or job
        return {"job": _serialize_run_job(job)}

    @app.get("/tasks/{task_id}/runs")
    def list_runs(task_id: int, limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        task = repository.get_task(task_id)
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        runs = repository.list_runs(task_id=task_id, limit=limit)
        return {"items": [_serialize_run(item) for item in runs]}

    @app.get("/runs/{run_id}")
    def get_run(run_id: int) -> dict[str, Any]:
        run = repository.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run": _serialize_run(run)}

    @app.get("/runs/{run_id}/report")
    def get_run_report(run_id: int) -> dict[str, Any]:
        run = repository.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        return {"run_id": run_id, "report": json.loads(run.report_json)}

    @app.get("/runs/{run_id}/report.html", response_class=HTMLResponse)
    def get_run_report_html(run_id: int) -> str:
        run = repository.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        report = json.loads(run.report_json)
        return render_report_html(run_id=run_id, report=report)

    @app.get("/run-jobs")
    def list_run_jobs(limit: int = Query(default=100, ge=1, le=500)) -> dict[str, Any]:
        jobs = repository.list_run_jobs(limit=limit)
        return {"items": [_serialize_run_job(item) for item in jobs]}

    @app.get("/run-jobs/{job_id}")
    def get_run_job(job_id: int) -> dict[str, Any]:
        job = repository.get_run_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="run job not found")
        return {"job": _serialize_run_job(job)}

    return app


def _execute_task(
    repository: TaskRepository,
    task: TaskRecord,
    override_source: str = "",
) -> RunRecord:
    config = json.loads(task.config_json)
    source = override_source or task.source
    agent = WorkflowTestAgent.default(
        runtime_mode=task.runtime_mode,
        base_url=str(config.get("base_url", "")),
        db_url=str(config.get("db_url", "")),
        db_path=str(config.get("db_path", "")),
        artifacts_dir=str(config.get("artifacts_dir", "artifacts")),
        storage_state_path=str(config.get("storage_state_path", "")),
        persist_storage_state=bool(config.get("persist_storage_state", True)),
        browser_headless=bool(config.get("browser_headless", True)),
        mcp_endpoint=config.get("mcp_endpoint"),
        mcp_token=str(config.get("mcp_token", "")),
        allow_private_url=bool(config.get("allow_private_url", False)),
        allowed_domains=tuple(config.get("allowed_domains", [])),
    )
    report = agent.run(source)
    status = str(report.get("status", "error"))
    return repository.create_run(task_id=task.task_id, status=status, report=report)


def _serialize_task(task: TaskRecord) -> dict[str, Any]:
    data = asdict(task)
    data["config"] = json.loads(task.config_json)
    return data


def _serialize_run(run: RunRecord) -> dict[str, Any]:
    data = asdict(run)
    report = json.loads(run.report_json)
    data["report"] = report
    return data


def _serialize_run_job(job: RunJobRecord) -> dict[str, Any]:
    return asdict(job)


def main() -> None:
    """Run API server."""
    app = create_app()
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
