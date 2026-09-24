from test_agent.workflow import WorkflowTestAgent


def test_workflow_agent_generates_cases_actions_and_report() -> None:
    source = """
    - 系统需要支持用户登录
    - 系统应支持商品搜索
    """.strip()

    agent = WorkflowTestAgent.default()
    report = agent.run(source)

    assert report["status"] == "ok"
    summary = report["summary"]
    assert isinstance(summary, dict)
    assert summary["test_case_count"] >= 2
    assert summary["action_point_count"] >= summary["test_case_count"]
    assert summary["mcp_call_count"] == summary["action_point_count"]
    assert summary["passed_count"] >= 1

    action_points = report["action_points"]
    assert isinstance(action_points, list)
    assert any(item["action"] == "assert_expectation" for item in action_points)
    assert "artifacts" in report
    assert report["errors"] == []


def test_workflow_agent_returns_structured_error_report() -> None:
    agent = WorkflowTestAgent.default()
    report = agent.run("http://127.0.0.1:3000")

    assert report["status"] == "error"
    errors = report["errors"]
    assert isinstance(errors, list)
    assert errors
    assert errors[0]["stage"] == "source_loading"
