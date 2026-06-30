from __future__ import annotations

from typing import Any, Literal


class PlanningDiagnosticError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def planning_diagnostic(
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
