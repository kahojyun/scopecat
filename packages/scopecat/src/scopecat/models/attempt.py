"""Point-internal attempt summary contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from scopecat.diagnostics import Diagnostic

POINT_ATTEMPT_SUMMARY_SCHEMA_VERSION = "scopecat.point_attempt_summary.v2"

type AttemptValue = str | int | float | bool


class PointAttemptSummary(BaseModel):
    """Summary for repeated attempts inside one logical point."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.point_attempt_summary.v2"] = (
        POINT_ATTEMPT_SUMMARY_SCHEMA_VERSION
    )
    point_index: int
    success: bool
    attempts: int
    selected_attempt: int | None = None
    final_value: AttemptValue | None = None
    value_label: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


def summarize_point_attempts(
    rows: Sequence[Mapping[str, Any]],
    *,
    point_index: int,
    max_attempts: int,
    target_value: AttemptValue,
    attempt_column: str = "attempt",
    value_column: str = "value",
    value_label: str | None = None,
) -> PointAttemptSummary:
    if point_index < 0:
        msg = "point_index must be nonnegative"
        raise ValueError(msg)
    if max_attempts <= 0:
        msg = "max_attempts must be positive"
        raise ValueError(msg)

    diagnostics: list[Diagnostic] = []
    seen_attempts: set[int] = set()
    selected_attempt: int | None = None
    final_value: AttemptValue | None = None

    for row_index, row in enumerate(rows):
        attempt = row.get(attempt_column)
        if not isinstance(attempt, int) or isinstance(attempt, bool):
            diagnostics.append(
                _diagnostic(
                    "invalid_point_attempt",
                    f"row {row_index} has invalid attempt {attempt!r}",
                    f"rows.{row_index}.{attempt_column}",
                )
            )
            continue
        if attempt < 0 or attempt >= max_attempts:
            diagnostics.append(
                _diagnostic(
                    "invalid_point_attempt",
                    f"row {row_index} attempt {attempt} is out of range",
                    f"rows.{row_index}.{attempt_column}",
                )
            )
            continue
        if attempt in seen_attempts:
            diagnostics.append(
                _diagnostic(
                    "duplicate_point_attempt",
                    f"row {row_index} repeats attempt {attempt}",
                    f"rows.{row_index}.{attempt_column}",
                )
            )
            continue
        seen_attempts.add(attempt)

        value = row.get(value_column)
        if not _is_attempt_value(value):
            diagnostics.append(
                _diagnostic(
                    "invalid_attempt_value",
                    f"row {row_index} has invalid value {value!r}",
                    f"rows.{row_index}.{value_column}",
                )
            )
            continue
        final_value = value
        if value == target_value and selected_attempt is None:
            selected_attempt = attempt

    success = selected_attempt is not None
    if not success:
        diagnostics.append(
            _diagnostic(
                "point_attempt_target_not_reached",
                f"point {point_index} did not reach target value {target_value!r}",
                f"points.{point_index}",
            )
        )

    attempts = (
        selected_attempt + 1 if selected_attempt is not None else len(seen_attempts)
    )
    return PointAttemptSummary(
        point_index=point_index,
        success=success,
        attempts=attempts,
        selected_attempt=selected_attempt,
        final_value=final_value,
        value_label=value_label,
        diagnostics=diagnostics,
    )


def _is_attempt_value(value: object) -> bool:
    return isinstance(value, str | int | float | bool)


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


__all__ = ["AttemptValue", "PointAttemptSummary", "summarize_point_attempts"]
