# 自动化测试智能体（Auto Test Agent）

该项目已经升级为你设想的流程：

1. 输入来源（网站 URL / 需求文档 / PRD / 任意文本）
2. 自动产出测试用例
3. 基于用例规划自动测试动作点
4. 通过 MCP 执行动作
5. 核对执行结果与测试用例
6. 生成结构化测试报告

## 工作流架构

```text
输入(source)
  -> SourceLoader(来源归一化)
  -> TestCaseGenerator(测试用例生成)
  -> ActionPlanner(动作点规划)
  -> MCPExecutor(发起 MCP 调用)
  -> ResultVerifier(核对用例与调用结果)
  -> Report(JSON)
```

## 项目结构

```text
.
├── src/test_agent
│   ├── workflow.py        # 新链路智能体编排（source -> report）
│   ├── source_loader.py   # 网站/文件/文本 输入归一化
│   ├── case_generator.py  # 测试用例生成
│   ├── action_planner.py  # 动作点规划
│   ├── mcp_executor.py    # MCP 调用抽象与本地 mock
│   ├── verifier.py        # 核对执行结果
│   ├── cli.py             # 命令行入口
│   ├── agent.py           # 兼容旧模式：命令式测试解析
│   ├── analyzer.py
│   ├── parser.py
│   ├── runner.py
│   ├── config.py
│   └── models.py
├── tests
│   ├── test_source_loader.py
│   ├── test_workflow.py
│   ├── test_agent_report.py
│   ├── test_analyzer.py
│   └── test_parser.py
└── pyproject.toml
```

## 快速开始

### 1) 安装

```bash
python3 -m pip install -e ".[dev]"
```

### 2) 工作流模式（推荐）

#### 输入网站

```bash
auto-test-agent --source "https://example.com" --output report.json
```

#### 输入 PRD 文件

```bash
auto-test-agent --source "./docs/sample.prd" --output report.json
```

#### 输入需求文本

```bash
auto-test-agent --source "系统需要支持用户登录并支持商品搜索" --output report.json
```

### 3) 兼容旧模式（命令式测试）

```bash
auto-test-agent --cmd "pytest -q" --output report.json
```

### 4) 运行单元测试

```bash
pytest -q
```

## 报告字段（工作流模式）

```json
{
  "generated_at": "2026-05-06T09:00:00+00:00",
  "input": {
    "kind": "prd",
    "identifier": "./docs/sample.prd",
    "metadata": {
      "extension": "prd",
      "length": "248"
    }
  },
  "summary": {
    "test_case_count": 3,
    "action_point_count": 10,
    "mcp_call_count": 10,
    "passed_count": 2,
    "failed_count": 1
  },
  "test_cases": [],
  "action_points": [],
  "mcp_results": [],
  "case_results": []
}
```

## MCP 接入说明

当前默认使用 `LocalMockMCPClient`（本地 mock）演示端到端流程。  
接入真实 MCP 时，只需要实现同样的接口：

- `invoke(action: str, params: dict[str, Any]) -> dict[str, Any]`

然后替换 `MCPExecutor(client=...)` 的 client 即可。
