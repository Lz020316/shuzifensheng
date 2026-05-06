"""Parse raw pytest output into structured failures."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .models import FailedTest

_FAILED_LINE = re.compile(r"^FAILED\s+(?P<nodeid>\S+)\s+-\s+(?P<reason>.+)$")
_SHORT_SUMMARY_START = "short test summary info"


@dataclass(slots=True)
class PytestOutputParser:
    """Extract failed test cases from pytest output."""

    max_detail_lines: int = 25

    def parse_failed_tests(self, stdout: str) -> list[FailedTest]:
        """Parse failed test records from pytest stdout."""
        failures: list[FailedTest] = []
        lines = stdout.splitlines()

        summary_start_idx = self._find_summary_start(lines)
        if summary_start_idx == -1:
            return failures

        for line in lines[summary_start_idx + 1 :]:
            stripped = line.strip()
            if not stripped:
                continue
            match = _FAILED_LINE.match(stripped)
            if not match:
                continue

            nodeid = match.group("nodeid")
            reason = match.group("reason")
            details = self._collect_failure_details(lines, nodeid=nodeid)
            failures.append(FailedTest(nodeid=nodeid, reason=reason, details=details))

        return failures

    @staticmethod
    def _find_summary_start(lines: list[str]) -> int:
        for idx, line in enumerate(lines):
            if _SHORT_SUMMARY_START in line.lower():
                return idx
        return -1

    def _collect_failure_details(self, lines: list[str], nodeid: str) -> str:
        """Collect up to max_detail_lines around a failed test block."""
        block_start = -1
        for idx, line in enumerate(lines):
            if nodeid in line and line.lstrip().startswith(("____", "===")):
                block_start = idx
                break

        if block_start == -1:
            return ""

        block: list[str] = []
        for line in lines[block_start : block_start + self.max_detail_lines]:
            if not line.strip() and block:
                break
            block.append(line)
        return "\n".join(block).strip()
