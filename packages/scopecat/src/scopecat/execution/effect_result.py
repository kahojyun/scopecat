"""Observed facts returned by the run-effect interpreter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from scopecat.execution.program import RunDomainJob
from scopecat.kernel.problems import Problem
from scopecat.measurements.points import RunPoint
from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.records.instrument import InstrumentStateSnapshot

type CoverageMeasurementObserver = Callable[
    [tuple[RunPoint, ...], tuple[MeasurementValueCandidate, ...]],
    None,
]


@dataclass(frozen=True, slots=True)
class RunEffectResult:
    """Facts observed while interpreting effects; not a terminal run outcome."""

    problems: tuple[Problem, ...]
    observed_state: tuple[InstrumentStateSnapshot, ...]
    prepared_state: tuple[InstrumentStateSnapshot, ...]
    final_state: tuple[InstrumentStateSnapshot, ...]
    admitted_points: tuple[RunPoint, ...] = ()
    indeterminate: bool = False
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
