from pathlib import Path
import time

from fastapi.testclient import TestClient

from test_agent.server import create_app


def test_server_task_run_and_report_endpoints(tmp_path: Path) -> None:
    db_file = tmp_path / "agent.db"
    app = create_app(db_file=str(db_file), worker_count=1, poll_interval_seconds=0.05)
    client = TestClient(app)

    create_response = client.post(
        "/tasks",
        json={
            "source": "系统需要支持用户登录并支持商品搜索",
            "runtime_mode": "mock",
            "auto_run": True,
        },
    )
    assert create_response.status_code == 200
    payload = create_response.json()
    task_id = payload["task"]["task_id"]
    run_id = payload["run"]["run_id"]
    assert payload["run"]["status"] == "ok"

    tasks_response = client.get("/tasks")
    assert tasks_response.status_code == 200
    assert tasks_response.json()["items"]

    runs_response = client.get(f"/tasks/{task_id}/runs")
    assert runs_response.status_code == 200
    assert runs_response.json()["items"][0]["run_id"] == run_id

    report_response = client.get(f"/runs/{run_id}/report")
    assert report_response.status_code == 200
    assert report_response.json()["report"]["status"] == "ok"

    html_response = client.get(f"/runs/{run_id}/report.html")
    assert html_response.status_code == 200
    assert "Auto Test Agent Report" in html_response.text


def test_server_async_run_job_worker(tmp_path: Path) -> None:
    db_file = tmp_path / "agent.db"
    app = create_app(db_file=str(db_file), worker_count=1, poll_interval_seconds=0.05)
    with TestClient(app) as client:
        create_response = client.post(
            "/tasks",
            json={
                "source": "系统需要支持用户登录",
                "runtime_mode": "mock",
                "auto_run": True,
                "auto_run_async": True,
                "max_attempts": 2,
            },
        )
        assert create_response.status_code == 200
        payload = create_response.json()
        assert "job" in payload
        job_id = payload["job"]["job_id"]

        deadline = time.time() + 5
        final_job = None
        while time.time() < deadline:
            job_resp = client.get(f"/run-jobs/{job_id}")
            assert job_resp.status_code == 200
            final_job = job_resp.json()["job"]
            if final_job["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.1)

        assert final_job is not None
        assert final_job["status"] == "succeeded"
        assert final_job["run_id"] > 0
