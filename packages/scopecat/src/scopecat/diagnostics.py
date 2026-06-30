"""Shared diagnostic records for validation and boundary reporting."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

DiagnosticSeverity = Literal["info", "warning", "error", "blocker"]


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: DiagnosticSeverity
    code: str
    message: str
    path: str | None = None


__all__ = [
    "Diagnostic",
    "DiagnosticSeverity",
]
