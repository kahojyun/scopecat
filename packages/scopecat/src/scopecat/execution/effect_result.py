"""Observed facts returned by the run-effect interpreter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from scopecat.execution.program import RunDomainJob
from scopecat.kernel.points import AcceptedRunPoint
from scopecat.kernel.problems import Problem
from scopecat.measurements.records import ValueRecordCandidate
from scopecat.measurements.values import MeasurementValueCandidate
from scopecat.records.execution import InstrumentFinalizationActionEvidence
from scopecat.records.instrument import InstrumentStateSnapshot
from scopecat.sdk.domain.evidence import DomainExecutionEvidence

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
    finalization_actions: tuple[InstrumentFinalizationActionEvidence, ...] = ()
    domain_execution: DomainExecutionEvidence | None = None
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
