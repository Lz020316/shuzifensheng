# 自动化测试智能体（Auto Test Agent）

一个轻量级的自动化测试智能体项目，用于：

- 自动执行测试命令（默认 `pytest -q`）
- 从测试输出中提取失败用例
- 基于失败信息生成可执行的修复建议
- 输出结构化 JSON 报告，便于接入 CI/CD 或二次分析

## 项目结构

```text
.
├── src/test_agent
│   ├── agent.py        # 智能体主编排
│   ├── analyzer.py     # 失败原因分析与修复建议
│   ├── cli.py          # 命令行入口
│   ├── config.py       # 运行配置
│   ├── models.py       # 数据模型
│   ├── parser.py       # pytest 输出解析
│   └── runner.py       # 测试命令执行器
├── tests
│   ├── test_agent.py
│   ├── test_analyzer.py
│   └── test_parser.py
└── pyproject.toml
```

## 快速开始

### 1) 安装（开发模式）

```bash
python -m pip install -e ".[dev]"
```

### 2) 运行智能体

```bash
auto-test-agent --cmd "pytest -q" --output report.json
```

运行后会在当前目录生成 `report.json`。

### 3) 运行单元测试

```bash
pytest -q
```

## 报告示例

```json
{
  "generated_at": "2026-05-06T03:58:00+00:00",
  "command": ["pytest", "-q"],
  "succeeded": false,
  "return_code": 1,
  "duration_seconds": 0.145,
  "summary": {
    "failure_count": 1,
    "insight_count": 1
  },
  "insights": [
    {
      "nodeid": "tests/test_sample.py::test_addition_failure",
      "reason": "AssertionError: assert 2 == 3",
      "probable_cause": "Test expectation does not match current implementation behavior.",
      "suggested_fix": "Check expected values in test and align with business rule changes."
    }
  ],
  "output_excerpt": "..."
}
```

## 扩展方向

- 接入 LLM 对 traceback 做更精准根因分析
- 自动生成修复补丁草案（human-in-the-loop）
- 多测试框架支持（unittest、nose、jest 等）
- 与 GitHub Actions / GitLab CI 集成自动回传报告
