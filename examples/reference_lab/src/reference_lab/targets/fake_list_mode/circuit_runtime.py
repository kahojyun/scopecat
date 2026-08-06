"""Correlate fake target evidence to Scopecat logical quantum outputs."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scopecat.measurements.results import MeasurementArray
from scopecat.sdk.domain import (
    DomainResultValue,
)
from scopecat_quantum.program_results import (
    MappedQuantumTarget,
)
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
)

from reference_lab.targets.fake_list_mode.model import (
    FakeListArtifact,
)
from reference_lab.targets.fake_list_mode.runtime import (
    FakeDigitizerFrame,
    FakeListRun,
)

_FAKE_RESPONSE_UNIT = "ratio"

type _MappedFakeListTarget = MappedQuantumTarget[FakeListArtifact]


@dataclass(frozen=True, slots=True)
class CorrelatedFakeListRun:
    """Canonically ordered raw target data after correlation."""

    mapped_target: _MappedFakeListTarget
    frames: tuple[FakeDigitizerFrame, ...]


def correlate_fake_list_run(
    mapped_target: _MappedFakeListTarget,
    target_run: FakeListRun,
) -> CorrelatedFakeListRun:
    """Correlate one raw fake run without interpreting values."""

    mapping = mapped_target.mapping
    artifact = mapped_target.artifact
    if target_run.artifact != artifact:
        msg = "fake-list run does not retain the compiled target artifact"
        raise ValueError(msg)

    raw_by_address_shot = {
        (frame.address, frame.shot_index): frame for frame in target_run.frames
    }
    if len(raw_by_address_shot) != len(target_run.frames):
        msg = "fake-list run contains duplicate acquisition-address shots"
        raise ValueError(msg)
    expected_keys = {
        (result.result_address, shot_index)
        for result in mapping.results
        for shot_index in range(artifact.repetitions)
    }
    if set(raw_by_address_shot) != expected_keys:
        msg = (
            "fake-list frames must exactly cover every mapped acquisition for "
            "every shot"
        )
        raise ValueError(msg)

    correlated_frames = tuple(
        raw_by_address_shot[(result.result_address, shot_index)]
        for result in mapping.results
        for shot_index in range(artifact.repetitions)
    )
    return CorrelatedFakeListRun(
        mapped_target,
        correlated_frames,
    )


def realize_fake_measurements(
    correlated_run: CorrelatedFakeListRun,
) -> tuple[DomainResultValue[TargetAcquisitionAddress], ...]:
    """Project one correlated run to canonical integrated-IQ values."""

    return tuple(
        DomainResultValue(
            result.result_address,
            _realize_integrated_iq_value(
                _frames_for_result_address(correlated_run, result.result_address),
            ),
        )
        for result in correlated_run.mapped_target.mapping.results
    )


def _frames_for_result_address(
    correlated_run: CorrelatedFakeListRun,
    result_address: TargetAcquisitionAddress,
) -> tuple[FakeDigitizerFrame, ...]:
    return tuple(
        frame for frame in correlated_run.frames if frame.address == result_address
    )


def _realize_integrated_iq_value(
    frames: tuple[FakeDigitizerFrame, ...],
) -> MeasurementArray:
    return MeasurementArray.create(
        dtype="complex128",
        unit=_FAKE_RESPONSE_UNIT,
        values=np.asarray(
            [frame.value for frame in frames],
            dtype=np.complex128,
        ),
    )


__all__ = [
    "CorrelatedFakeListRun",
    "correlate_fake_list_run",
    "realize_fake_measurements",
]
