"""Focused helpers for interpreting exact local effect coverage in tests."""

from __future__ import annotations

from scopecat.execution.program import (
    RunCoverageBlock,
    RunOperation,
)
from tests.testkit.local_materialization import LocalEffectInspection


def complete_coverage_operations(
    execution: LocalEffectInspection,
) -> tuple[RunOperation, ...]:
    return (
        (
            RunCoverageBlock(
                points=execution.points,
                operations=execution.effects,
            ),
        )
        if execution.points
        else ()
    )
