from test_agent.workflow import WorkflowTestAgent


def test_workflow_agent_generates_cases_actions_and_report() -> None:
    source = """
    - 系统需要支持用户登录
    - 系统应支持商品搜索
    """.strip()

    agent = WorkflowTestAgent.default()
    # 预置页面文本，保证断言动作能够命中关键词。
    agent.executor.client.state["page_text"] = "系统需要支持用户登录与商品搜索"

    report = agent.run(source)

    summary = report["summary"]
    assert isinstance(summary, dict)
    assert summary["test_case_count"] >= 2
    assert summary["action_point_count"] >= summary["test_case_count"]
    assert summary["mcp_call_count"] == summary["action_point_count"]
    assert summary["passed_count"] >= 1

    action_points = report["action_points"]
    assert isinstance(action_points, list)
    assert any(item["action"] == "assert_expectation" for item in action_points)
