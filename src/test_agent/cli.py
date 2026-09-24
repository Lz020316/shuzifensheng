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
    parser.add_argument(
        "--mcp-endpoint",
        default="",
        help="真实 MCP HTTP 接口地址（不传则使用本地 mock）",
    )
    parser.add_argument(
        "--mcp-token",
        default="",
        help="调用 MCP 的 Bearer Token（可选）",
    )
    parser.add_argument(
        "--allow-private-url",
        action="store_true",
        help="允许访问内网地址（默认禁用，避免 SSRF 风险）",
    )
    parser.add_argument(
        "--allowed-domain",
        action="append",
        default=[],
        help="允许访问的域名（可重复传入，留空表示不限制）",
    )
    parser.add_argument(
        "--runtime-mode",
        choices=["mock", "playwright"],
        default="mock",
        help="工作流执行模式：mock 或 playwright",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="playwright 与 API 相对路径调用时使用的基础地址",
    )
    parser.add_argument(
        "--db-path",
        default="",
        help="query_db 动作默认使用的 SQLite 数据库文件路径",
    )
    parser.add_argument(
        "--artifacts-dir",
        default="artifacts",
        help="截图与日志等证据文件输出目录",
    )
    parser.add_argument(
        "--browser-headed",
        action="store_true",
        help="playwright 使用有头模式（默认无头）",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.source:
        workflow_agent = WorkflowTestAgent.default(
            runtime_mode=args.runtime_mode,
            base_url=args.base_url,
            db_path=args.db_path,
            artifacts_dir=args.artifacts_dir,
            browser_headless=not args.browser_headed,
            mcp_endpoint=args.mcp_endpoint or None,
            mcp_token=args.mcp_token,
            allow_private_url=args.allow_private_url,
            allowed_domains=tuple(args.allowed_domain),
        )
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
