"""CLI entrypoint for the automated testing agent."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .agent import AutoTestAgent
from .config import AgentConfig
from .workflow import WorkflowTestAgent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run automated test agent once.")
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--source",
        help="输入来源：可以是网站 URL、本地文件路径或直接输入的需求文本",
    )
    mode_group.add_argument(
        "--cmd",
        help="兼容旧模式：直接执行测试命令，例如 \"pytest -q\"",
    )
    parser.add_argument(
        "--output",
        default="report.json",
        help="输出 JSON 报告文件路径",
    )
    parser.add_argument(
        "--max-output-chars",
        type=int,
        default=20_000,
        help="报告中保留的日志最大字符数",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.source:
        workflow_agent = WorkflowTestAgent.default()
        report = workflow_agent.run(args.source)
        report_json = workflow_agent.to_json(report)
    else:
        try:
            config = AgentConfig.from_command_string(args.cmd)
        except ValueError as exc:
            print(f"无效测试命令: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc

        config.max_output_chars = args.max_output_chars
        agent = AutoTestAgent.default(config=config)
        report = agent.run_once()
        report_json = agent.to_json(report)

    output_path = Path(args.output)
    output_path.write_text(report_json, encoding="utf-8")
    print(f"报告已生成: {output_path}")


if __name__ == "__main__":
    main()
