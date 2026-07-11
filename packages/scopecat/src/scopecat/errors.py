"""Scopecat exception types."""

from __future__ import annotations

from scopecat.diagnostics import Diagnostic


class ScopecatError(Exception):
    """Base error for Scopecat failures."""


class ValidationFailed(ScopecatError):
    """Raised when validation diagnostics contain errors or blockers."""

    def __init__(self, diagnostics: list[Diagnostic]) -> None:
        self.diagnostics = diagnostics
        super().__init__("validation failed")


class RunExecutionFailed(ValidationFailed):
    """A durably recorded run reached a non-success terminal state."""

    def __init__(self, run_id: str, diagnostics: list[Diagnostic]) -> None:
        self.run_id = run_id
        super().__init__(diagnostics)
