"""Failure analysis utilities for the automated testing agent."""

from __future__ import annotations

from dataclasses import dataclass

from .models import FailedTest


@dataclass(slots=True)
class FailureInsight:
    """Actionable insight for one failed test."""

    nodeid: str
    reason: str
    probable_cause: str
    suggested_fix: str


@dataclass(slots=True)
class FailureAnalyzer:
    """Generate lightweight root-cause hints from test failures."""

    def analyze(self, failures: list[FailedTest]) -> list[FailureInsight]:
        """Return insights for each failure."""
        return [
            FailureInsight(
                nodeid=failure.nodeid,
                reason=failure.reason,
                probable_cause=self._infer_probable_cause(failure),
                suggested_fix=self._suggest_fix(failure),
            )
            for failure in failures
        ]

    def _infer_probable_cause(self, failure: FailedTest) -> str:
        haystack = f"{failure.reason}\n{failure.details}".lower()
        if "assert" in haystack:
            return "Test expectation does not match current implementation behavior."
        if "timeout" in haystack:
            return "Execution path is too slow or waiting on unavailable dependency."
        if "keyerror" in haystack:
            return "Input data misses required dictionary key."
        if "attributeerror" in haystack:
            return "Object contract changed or value is None unexpectedly."
        if "typeerror" in haystack:
            return "Function call uses incompatible argument types or signature."
        if "modulenotfounderror" in haystack:
            return "Runtime dependency or module import path is missing."
        return "Unknown from heuristics; inspect traceback details for root cause."

    def _suggest_fix(self, failure: FailedTest) -> str:
        haystack = f"{failure.reason}\n{failure.details}".lower()
        if "assert" in haystack:
            return "Check expected values in test and align with business rule changes."
        if "timeout" in haystack:
            return "Stub external I/O and optimize slow code paths."
        if "keyerror" in haystack:
            return "Validate input payload and provide default keys when absent."
        if "attributeerror" in haystack:
            return "Add defensive checks and verify object initialization path."
        if "typeerror" in haystack:
            return "Review function signature and normalize argument types."
        if "modulenotfounderror" in haystack:
            return "Install or declare missing dependency and fix import paths."
        return "Reproduce locally with verbose traceback and patch the failing path."
