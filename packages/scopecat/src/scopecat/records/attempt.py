"""Point-internal attempt summary contracts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, TypeGuard

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    has_blocking_problems,
    model_location,
)

POINT_ATTEMPT_SUMMARY_SCHEMA_VERSION = "scopecat.point_attempt_summary.v3"

type AttemptValue = str | int | float | bool


class PointAttemptSummary(BaseModel):
    """Summary for repeated attempts inside one logical point."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scopecat.point_attempt_summary.v3"] = (
        POINT_ATTEMPT_SUMMARY_SCHEMA_VERSION
    )
    point_index: int = Field(ge=0)
    success: bool
    attempts: int = Field(ge=0)
    selected_attempt: int | None = Field(default=None, ge=0)
    final_value: AttemptValue | None = None
    value_label: str | None = None
    problems: tuple[Problem, ...] = ()

    @model_validator(mode="after")
    def validate_result_state(self) -> PointAttemptSummary:
        if self.success and has_blocking_problems(self.problems):
            msg = "a successful point attempt summary cannot be blocked"
            raise ValueError(msg)
        if self.success and self.selected_attempt is None:
            msg = "a successful point attempt summary requires a selected attempt"
            raise ValueError(msg)
        if self.selected_attempt is not None and not (
            0 <= self.selected_attempt < self.attempts
        ):
            msg = "selected attempt is outside the attempted range"
            raise ValueError(msg)
        return self


def summarize_point_attempts(
    rows: Sequence[Mapping[str, object]],
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

    problems: list[Problem] = []
    seen_attempts: dict[int, int] = {}
    selected_attempt: int | None = None
    final_value: AttemptValue | None = None

    for row_index, row in enumerate(rows):
        attempt = row.get(attempt_column)
        if not isinstance(attempt, int) or isinstance(attempt, bool):
            problems.append(
                blocking_problem(
                    "invalid_point_attempt",
                    f"row {row_index} has invalid attempt {attempt!r}",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "point_attempts",
                        "rows",
                        row_index,
                        attempt_column,
                    ),
                )
            )
            continue
        if attempt < 0 or attempt >= max_attempts:
            problems.append(
                blocking_problem(
                    "invalid_point_attempt",
                    f"row {row_index} attempt {attempt} is out of range",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "point_attempts",
                        "rows",
                        row_index,
                        attempt_column,
                    ),
                    details={"attempt": attempt, "max_attempts": max_attempts},
                )
            )
            continue
        if attempt in seen_attempts:
            problems.append(
                blocking_problem(
                    "duplicate_point_attempt",
                    f"row {row_index} repeats attempt {attempt}",
                    category=ProblemCategory.CONFLICT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "point_attempts",
                        "rows",
                        row_index,
                        attempt_column,
                    ),
                    related_locations=(
                        model_location(
                            "point_attempts",
                            "rows",
                            seen_attempts[attempt],
                            attempt_column,
                        ),
                    ),
                    details={"attempt": attempt},
                )
            )
            continue
        seen_attempts[attempt] = row_index

        value = row.get(value_column)
        if not _is_attempt_value(value):
            problems.append(
                blocking_problem(
                    "invalid_attempt_value",
                    f"row {row_index} has invalid value {value!r}",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "point_attempts",
                        "rows",
                        row_index,
                        value_column,
                    ),
                )
            )
            continue
        final_value = value
        if value == target_value and selected_attempt is None:
            selected_attempt = attempt

    if problems:
        selected_attempt = None
    success = selected_attempt is not None
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
        problems=tuple(problems),
    )


def _is_attempt_value(value: object) -> TypeGuard[AttemptValue]:
    return isinstance(value, str | int | float | bool)


__all__ = ["AttemptValue", "PointAttemptSummary", "summarize_point_attempts"]
