"""Online evaluation boundary records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field

from scopecat.diagnostics import Diagnostic


class EarlyStopDecision(BaseModel):
    """Typed decision record for online stop conditions."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "scopecat.early_stop_decision.v1"
    stop: bool
    completed_point_ids: list[int] = Field(default_factory=list)
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
            completed_point_ids=_completed_point_ids(accepted),
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
        point_id = row.get("point_id")
        if x_column not in row or y_column not in row:
            diagnostics.append(
                _diagnostic(
                    "missing_convergence_column",
                    f"row {point_id!r} is missing x/y columns",
                    f"rows.{point_id}",
                )
            )
            continue
        y_value = row[y_column]
        if not _is_number(y_value):
            diagnostics.append(
                _diagnostic(
                    "invalid_convergence_value",
                    f"row {point_id!r} has nonnumeric y value",
                    f"rows.{point_id}.{y_column}",
                )
            )
            continue
        values.append(float(cast(int | float, y_value)))

    completed_point_ids = _completed_point_ids(accepted)
    if diagnostics:
        return EarlyStopDecision(
            stop=False,
            completed_point_ids=completed_point_ids,
            diagnostics=diagnostics,
        )

    tail = values[-window:]
    converged = len(tail) >= window and (max(tail) - min(tail)) <= tolerance
    return EarlyStopDecision(
        stop=converged,
        completed_point_ids=completed_point_ids,
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
        point_id = row.get("point_id")
        if not isinstance(point_id, int) or isinstance(point_id, bool):
            continue
        if point_id < 0 or point_id >= point_count or point_id in seen_points:
            continue
        accepted.append(dict(row))
        seen_points.add(point_id)
    return sorted(accepted, key=lambda row: cast(int, row["point_id"]))


def _completed_point_ids(rows: Sequence[Mapping[str, Any]]) -> list[int]:
    point_ids: list[int] = []
    for row in rows:
        point_id = row.get("point_id")
        if isinstance(point_id, int) and not isinstance(point_id, bool):
            point_ids.append(point_id)
    return point_ids


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _diagnostic(code: str, message: str, path: str) -> Diagnostic:
    return Diagnostic(severity="error", code=code, message=message, path=path)


__all__ = ["EarlyStopDecision", "decide_online_convergence"]
