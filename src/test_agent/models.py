"""Data models used by the automated testing agent."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FailedTest:
    """A failed test case extracted from test output."""

    nodeid: str
    reason: str
    details: str


@dataclass(slots=True)
class TestRunResult:
    """Result object for one test command execution."""

    command: list[str]
    return_code: int
    stdout: str
    stderr: str
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        """Whether the command exited successfully."""
        return self.return_code == 0

