"""Correlate list-mode target evidence to Scopecat logical quantum outputs."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scopecat.measurements.results import (
    MeasurementArray,
    MeasurementUnavailable,
    MeasurementValue,
)
from scopecat.sdk.domain import (
    DomainResultValue,
)
from scopecat_quantum.program_results import (
    MappedQuantumTarget,
)
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
)

from reference_lab.targets.list_mode.execution_model import (
    DigitizerFrame,
    ListModeRun,
)
from reference_lab.targets.list_mode.model import (
    ListModeArtifact,
)

_RESPONSE_UNIT = "ratio"

type _MappedListModeTarget = MappedQuantumTarget[ListModeArtifact]


@dataclass(frozen=True, slots=True)
class CorrelatedListModeRun:
    """Canonically ordered raw target data after correlation."""

    mapped_target: _MappedListModeTarget
    frames: tuple[DigitizerFrame, ...]


def correlate_list_mode_run(
    mapped_target: _MappedListModeTarget,
    target_run: ListModeRun,
) -> CorrelatedListModeRun:
    """Correlate one raw device run without interpreting values."""

    mapping = mapped_target.mapping
    artifact = mapped_target.artifact
    if target_run.artifact != artifact:
        msg = "list-mode run does not retain the compiled target artifact"
        raise ValueError(msg)

    raw_by_address_shot = {
        (frame.address, frame.shot_index): frame for frame in target_run.frames
    }
    if len(raw_by_address_shot) != len(target_run.frames):
        msg = "list-mode run contains duplicate acquisition-address shots"
        raise ValueError(msg)
    expected_keys = {
        (result.result_address, shot_index)
        for result in mapping.results
        for shot_index in range(artifact.repetitions)
    }
    if set(raw_by_address_shot) != expected_keys:
        msg = (
            "list-mode frames must exactly cover every mapped acquisition for "
            "every shot"
        )
        raise ValueError(msg)

    correlated_frames = tuple(
        raw_by_address_shot[(result.result_address, shot_index)]
        for result in mapping.results
        for shot_index in range(artifact.repetitions)
    )
    return CorrelatedListModeRun(
        mapped_target,
        correlated_frames,
    )


def realize_measurements(
    correlated_run: CorrelatedListModeRun,
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
    correlated_run: CorrelatedListModeRun,
    result_address: TargetAcquisitionAddress,
) -> tuple[DigitizerFrame, ...]:
    return tuple(
        frame for frame in correlated_run.frames if frame.address == result_address
    )


def _realize_integrated_iq_value(
    frames: tuple[DigitizerFrame, ...],
) -> MeasurementValue:
    if all(frame.value is None for frame in frames):
        return MeasurementUnavailable.create(
            dtype="complex128",
            unit=_RESPONSE_UNIT,
            shape=(len(frames),),
            reason="missing",
            metadata={"source": "virtual-demodulator", "detail": "no lock"},
        )
    if any(frame.value is None for frame in frames):
        raise ValueError(
            "one acquisition result cannot mix available and missing shots"
        )
    return MeasurementArray.create(
        dtype="complex128",
        unit=_RESPONSE_UNIT,
        values=np.asarray(
            [frame.value for frame in frames],
            dtype=np.complex128,
        ),
    )


__all__ = [
    "CorrelatedListModeRun",
    "correlate_list_mode_run",
    "realize_measurements",
]
