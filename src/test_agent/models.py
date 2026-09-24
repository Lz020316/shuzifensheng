"""Data models used by the automated testing agent."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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


@dataclass(slots=True)
class InputArtifact:
    """Normalized input artifact from URL, file, or free text."""

    kind: str
    identifier: str
    content: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class TestCase:
    """Generated test case from source artifacts."""

    case_id: str
    title: str
    steps: list[str]
    expected_result: str
    source_ref: str


@dataclass(slots=True)
class ActionPoint:
    """One executable action for MCP invocation."""

    action_id: str
    case_id: str
    action: str
    params: dict[str, Any]


@dataclass(slots=True)
class MCPCallResult:
    """Result returned by one MCP action invocation."""

    action_id: str
    case_id: str
    success: bool
    output: dict[str, Any]
    error: str = ""


@dataclass(slots=True)
class CaseEvaluation:
    """Verification result for one generated test case."""

    case_id: str
    title: str
    passed: bool
    evidence: list[str]
    mismatches: list[str]

