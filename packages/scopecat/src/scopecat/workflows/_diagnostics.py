"""Shared workflow diagnostic helpers."""

from scopecat.diagnostics import Diagnostic, DiagnosticSeverity


def diagnostic(
    severity: DiagnosticSeverity,
    code: str,
    message: str,
    path: str | None = None,
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)
