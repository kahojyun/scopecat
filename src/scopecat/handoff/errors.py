"""Route-local handoff error diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HandoffErrorDiagnostic:
    """Stable local diagnostic for a handoff API error."""

    code: str
    operation: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_posture": "local_handoff_error_diagnostic",
            "error": {
                "code": self.code,
                "operation": self.operation,
                "message": self.message,
            },
        }


class HandoffError(ValueError):
    """Base ValueError-compatible handoff public API error."""

    code = "handoff_error"

    def __init__(self, message: str, *, operation: str) -> None:
        super().__init__(message)
        self.operation = operation

    def to_diagnostic(self) -> HandoffErrorDiagnostic:
        return HandoffErrorDiagnostic(
            code=self.code,
            operation=self.operation,
            message=str(self),
        )


class HandoffContractError(HandoffError):
    """Public handoff API input, contract, or continuity failure."""

    code = "handoff_contract_error"


def promote_handoff_contract_error(exc: ValueError, *, operation: str) -> HandoffError:
    """Return a handoff public error while preserving existing ValueError callers."""

    if isinstance(exc, HandoffError):
        return HandoffContractError(str(exc), operation=operation)
    return HandoffContractError(str(exc), operation=operation)
