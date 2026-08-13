"""Observed facts returned by the run-effect interpreter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from scopecat.execution.program import RunDomainJob
from scopecat.kernel.problems import Problem
from scopecat.measurements.points import AcceptedRunPoint
from scopecat.measurements.records import ValueRecordCandidate
from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.records.instrument import InstrumentStateSnapshot

type CoverageMeasurementObserver = Callable[
    [
        tuple[AcceptedRunPoint, ...],
        tuple[MeasurementValueCandidate, ...],
        tuple[ValueRecordCandidate, ...],
    ],
    None,
]


@dataclass(frozen=True, slots=True)
class RunEffectResult:
    """Observed effect facts, including best-effort terminal hardware readback."""

    problems: tuple[Problem, ...]
    observed_state: tuple[InstrumentStateSnapshot, ...]
    baseline_state: tuple[InstrumentStateSnapshot, ...]
    final_state: tuple[InstrumentStateSnapshot, ...]
    indeterminate: bool = False
    cancelled: bool = False
    domain_failure: tuple[RunDomainJob, BaseException] | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    coverage_failure: BaseException | None = field(
        default=None,
        compare=False,
        repr=False,
    )
    interruption: BaseException | None = field(
        default=None,
        compare=False,
        repr=False,
    )


__all__ = [
    "CoverageMeasurementObserver",
    "RunEffectResult",
]
