"""Configuration for the automated testing agent."""

from __future__ import annotations

from dataclasses import dataclass, field
import shlex


@dataclass(slots=True)
class AgentConfig:
    """Runtime configuration for the testing agent."""

    test_command: list[str] = field(default_factory=lambda: ["pytest", "-q"])
    max_output_chars: int = 20_000
    include_passing_tests: bool = False

    @classmethod
    def from_command_string(cls, command: str) -> "AgentConfig":
        """Build config from a shell-like command string."""
        parsed = shlex.split(command.strip())
        if not parsed:
            raise ValueError("test command must not be empty")
        return cls(test_command=parsed)
