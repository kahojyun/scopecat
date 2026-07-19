"""Focused helpers for interpreting materialized local effects in tests."""

from __future__ import annotations

from scopecat.execution.points import RunPoint
from scopecat.execution.program import (
    RunCoverageBlock,
    RunCoverageEffect,
    RunOperation,
)
from tests.testkit.local_materialization import MaterializedLocalEffects


def complete_point_operations(
    execution: MaterializedLocalEffects,
) -> tuple[RunOperation, ...]:
    return tuple(
        RunCoverageBlock(
            points=(RunPoint(point.logical_id, point.coordinates),),
            operations=tuple(
                RunCoverageEffect.at_point(point.point_index, operation)
                for operation in point.operations
            ),
        )
        for point in execution.points
    )
