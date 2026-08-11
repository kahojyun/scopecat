"""Focused helpers for interpreting exact local effect coverage in tests."""

from __future__ import annotations

from scopecat.execution.program import RunCoveredOperation

from scopecat_testkit.local_materialization import LocalEffectInspection


def complete_coverage_operations(
    execution: LocalEffectInspection,
) -> tuple[RunCoveredOperation, ...]:
    return execution.effects
