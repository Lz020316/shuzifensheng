"""Test runner for executing test commands."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
import subprocess

from .models import TestRunResult


@dataclass(slots=True)
class TestRunner:
    """Execute tests and capture outputs."""

    timeout_seconds: int = 120

    def run(self, command: list[str]) -> TestRunResult:
        """Run the test command and return a rich result object."""
        if not command:
            raise ValueError("test command must not be empty")

        start = perf_counter()
        completed = subprocess.run(  # noqa: S603
            command,
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            check=False,
        )
        duration = perf_counter() - start

        return TestRunResult(
            command=command,
            return_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
        )
