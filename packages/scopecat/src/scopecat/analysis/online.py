"""Online analysis boundary records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, model_validator

from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    has_blocking_problems,
    model_location,
)

OnlineEvaluationStatus = Literal["collecting", "evaluated", "invalid"]


class EarlyStopDecision(BaseModel):
    """Typed decision record for online stop conditions."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scopecat.early_stop_decision.v3"] = (
        "scopecat.early_stop_decision.v3"
    )
    stop: bool
    evaluation_status: OnlineEvaluationStatus
    completed_point_indices: tuple[int, ...] = ()
    reason: str | None = None
    problems: tuple[Problem, ...] = ()

    @model_validator(mode="after")
    def validate_evaluation_state(self) -> EarlyStopDecision:
        blocking = has_blocking_problems(self.problems)
        if self.evaluation_status == "invalid" and not blocking:
            msg = "an invalid online evaluation requires a blocking problem"
            raise ValueError(msg)
        if self.evaluation_status != "invalid" and blocking:
            msg = "a valid online evaluation cannot contain blocking problems"
            raise ValueError(msg)
        if self.stop and self.evaluation_status != "evaluated":
            msg = "only an evaluated online decision can stop a run"
            raise ValueError(msg)
        return self


def decide_online_convergence(
    rows: Sequence[Mapping[str, Any]],
    *,
    point_count: int,
    x_column: str,
    y_column: str,
    min_points: int,
    tolerance: float,
    window: int = 2,
) -> EarlyStopDecision:
    if min_points <= 0 or window <= 0:
        msg = "min_points and window must be positive"
        raise ValueError(msg)
    if tolerance < 0:
        msg = "tolerance must be nonnegative"
        raise ValueError(msg)

    accepted = _online_accepted_rows(rows, point_count=point_count)
    if len(accepted) < min_points:
        return EarlyStopDecision(
            stop=False,
            evaluation_status="collecting",
            completed_point_indices=_completed_point_indices(accepted),
        )

    problems: list[Problem] = []
    values: list[float] = []
    for row in accepted:
        point_index = cast("int", row["point_index"])
        if x_column not in row or y_column not in row:
            problems.append(
                blocking_problem(
                    "missing_convergence_column",
                    f"row {point_index!r} is missing x/y columns",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location("online_analysis", "rows", point_index),
                    details={
                        "point_index": point_index,
                        "x_column": x_column,
                        "y_column": y_column,
                    },
                )
            )
            continue
        y_value = row[y_column]
        if not _is_number(y_value):
            problems.append(
                blocking_problem(
                    "invalid_convergence_value",
                    f"row {point_index!r} has nonnumeric y value",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.ANALYSIS,
                    location=model_location(
                        "online_analysis",
                        "rows",
                        point_index,
                        y_column,
                    ),
                    details={
                        "point_index": point_index,
                        "column": y_column,
                    },
                )
            )
            continue
        values.append(float(cast("int | float", y_value)))

    completed_point_indices = _completed_point_indices(accepted)
    if problems:
        return EarlyStopDecision(
            stop=False,
            evaluation_status="invalid",
            completed_point_indices=completed_point_indices,
            problems=tuple(problems),
        )

    tail = values[-window:]
    converged = len(tail) >= window and (max(tail) - min(tail)) <= tolerance
    return EarlyStopDecision(
        stop=converged,
        evaluation_status="evaluated",
        completed_point_indices=completed_point_indices,
        reason=(
            f"last {window} {y_column!r} values within {tolerance}"
            if converged
            else None
        ),
    )


def _online_accepted_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    point_count: int,
) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    seen_points: set[int] = set()
    for row in rows:
        point_index = row.get("point_index")
        if not isinstance(point_index, int) or isinstance(point_index, bool):
            continue
        if point_index < 0 or point_index >= point_count or point_index in seen_points:
            continue
        accepted.append(dict(row))
        seen_points.add(point_index)
    return sorted(accepted, key=lambda row: cast("int", row["point_index"]))


def _completed_point_indices(rows: Sequence[Mapping[str, Any]]) -> tuple[int, ...]:
    point_indices: list[int] = []
    for row in rows:
        point_index = row.get("point_index")
        if isinstance(point_index, int) and not isinstance(point_index, bool):
            point_indices.append(point_index)
    return tuple(point_indices)


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


__all__ = [
    "EarlyStopDecision",
    "OnlineEvaluationStatus",
    "decide_online_convergence",
]
