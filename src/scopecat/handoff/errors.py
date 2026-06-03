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
            "summary_policy": {
                "source": "handoff_public_api_exception",
                "authority": "operator_error_review",
                "storage_mutation": "not_performed",
                "continuation_authority": "not_granted",
                "portable_export": "not_produced",
            },
            "error": {
                "code": self.code,
                "operation": self.operation,
                "message": self.message,
            },
            "does_not_claim": [
                "retry_authorization",
                "package_acceptance",
                "storage_mutation",
                "public_error_schema",
            ],
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
        return exc
    return HandoffContractError(str(exc), operation=operation)
