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
