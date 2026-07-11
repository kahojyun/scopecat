"""Compiler-local diagnostic helpers used by pure binding passes."""

from __future__ import annotations

from typing import Any, Literal


class CompilerDiagnosticError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def compiler_diagnostic(
    severity: Literal["info", "warning", "error", "blocker"],
    code: str,
    message: str,
    path: str,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "path": path,
    }


__all__ = ["CompilerDiagnosticError", "compiler_diagnostic"]
