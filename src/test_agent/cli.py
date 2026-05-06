"""CLI entrypoint for the automated testing agent."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .agent import AutoTestAgent
from .config import AgentConfig


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run automated test agent once.")
    parser.add_argument(
        "--cmd",
        default="pytest -q",
        help="测试命令，例如: \"pytest -q\" 或 \"python -m pytest tests -q\"",
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
