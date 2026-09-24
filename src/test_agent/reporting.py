"""Report rendering helpers."""

from __future__ import annotations

import html
import json
from typing import Any


def render_report_html(run_id: int, report: dict[str, Any]) -> str:
    """Render a workflow report as a standalone HTML page."""
    summary = report.get("summary", {})
    case_results = report.get("case_results", [])
    artifacts = report.get("artifacts", [])
    errors = report.get("errors", [])

    summary_rows = "".join(
        f"<li><strong>{html.escape(str(key))}</strong>: {html.escape(str(value))}</li>"
        for key, value in summary.items()
    )

    case_blocks: list[str] = []
    for item in case_results:
        title = html.escape(str(item.get("title", "")))
        case_id = html.escape(str(item.get("case_id", "")))
        passed = bool(item.get("passed"))
        status = "PASS" if passed else "FAIL"
        evidence = "".join(
            f"<li>{html.escape(str(line))}</li>" for line in item.get("evidence", [])
        )
        mismatches = "".join(
            f"<li>{html.escape(str(line))}</li>" for line in item.get("mismatches", [])
        )
        case_blocks.append(
            f"""
            <section class="case {'pass' if passed else 'fail'}">
              <h3>{case_id} - {title} <span>{status}</span></h3>
              <div class="columns">
                <div><h4>Evidence</h4><ul>{evidence or '<li>None</li>'}</ul></div>
                <div><h4>Mismatches</h4><ul>{mismatches or '<li>None</li>'}</ul></div>
              </div>
            </section>
            """
        )

    artifact_rows = []
    for item in artifacts:
        artifact_rows.append(
            "<li>"
            f"{html.escape(str(item.get('action_id', '')))} / "
            f"{html.escape(str(item.get('type', '')))} - "
            f"{html.escape(str(item.get('path', '')))}"
            "</li>"
        )
    artifacts_html = "".join(artifact_rows) or "<li>None</li>"

    error_rows = "".join(
        "<li>"
        f"{html.escape(str(item.get('stage', '')))}: "
        f"{html.escape(str(item.get('type', '')))} - "
        f"{html.escape(str(item.get('message', '')))}"
        "</li>"
        for item in errors
    ) or "<li>None</li>"

    raw_json = html.escape(json.dumps(report, ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Auto Test Agent Report #{run_id}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; line-height: 1.5; }}
    .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }}
    .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 12px; }}
    .case {{ border: 1px solid #ddd; border-radius: 8px; padding: 10px; margin-bottom: 10px; }}
    .case.pass {{ border-color: #1f9d55; }}
    .case.fail {{ border-color: #d64545; }}
    .columns {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
    pre {{ background: #111; color: #eaeaea; padding: 12px; border-radius: 8px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>Auto Test Agent Report #{run_id}</h1>
  <div class="grid">
    <section class="card">
      <h2>Summary</h2>
      <ul>{summary_rows}</ul>
    </section>
    <section class="card">
      <h2>Errors</h2>
      <ul>{error_rows}</ul>
    </section>
    <section class="card">
      <h2>Artifacts</h2>
      <ul>{artifacts_html}</ul>
    </section>
  </div>
  <h2>Case Results</h2>
  {''.join(case_blocks) or '<p>No case results.</p>'}
  <h2>Raw JSON</h2>
  <pre>{raw_json}</pre>
</body>
</html>
"""
