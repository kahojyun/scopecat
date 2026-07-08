"""Online analysis boundary records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from scopecat.diagnostics import Diagnostic


class EarlyStopDecision(BaseModel):
    """Typed decision record for online stop conditions."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.early_stop_decision.v2"
    stop: bool
    completed_point_indices: list[int] = Field(default_factory=list)
    reason: str | None = None
    diagnostics: list[Diagnostic] = Field(default_factory=list)


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
            completed_point_indices=_completed_point_indices(accepted),
            diagnostics=[
                _diagnostic(
                    "insufficient_convergence_points",
                    f"only {len(accepted)} points are available",
                    "rows",
                )
            ],
        )

    diagnostics: list[Diagnostic] = []
    values: list[float] = []
    for row in accepted:
        point_index = row.get("point_index")
        if x_column not in row or y_column not in row:
            diagnostics.append(
                _diagnostic(
                    "missing_convergence_column",
                    f"row {point_index!r} is missing x/y columns",
                    f"rows.{point_index}",
                )
            )
            continue
        y_value = row[y_column]
        if not _is_number(y_value):
            diagnostics.append(
                _diagnostic(
                    "invalid_convergence_value",
                    f"row {point_index!r} has nonnumeric y value",
                    f"rows.{point_index}.{y_column}",
                )
            )
            continue
        values.append(float(cast("int | float", y_value)))

    completed_point_indices = _completed_point_indices(accepted)
    if diagnostics:
        return EarlyStopDecision(
            stop=False,
            completed_point_indices=completed_point_indices,
            diagnostics=diagnostics,
        )

    tail = values[-window:]
    converged = len(tail) >= window and (max(tail) - min(tail)) <= tolerance
    return EarlyStopDecision(
        stop=converged,
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


def _completed_point_indices(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    point_indices: list[int] = []
    for row in rows:
        point_index = row.get("point_index")
        if isinstance(point_index, int) and not isinstance(point_index, bool):
            point_indices.append(point_index)
    return point_indices


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


__all__ = ["EarlyStopDecision", "decide_online_convergence"]
