"""Correlate list-mode result matrices to logical quantum outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scopecat.measurements.results import (
    MeasurementArray,
    MeasurementUnavailable,
    MeasurementValue,
)
from scopecat.sdk.domain import DomainResultValue
from scopecat_quantum.program_results import MappedQuantumTarget
from scopecat_quantum.targets import TargetAcquisitionAddress

from reference_lab.targets.list_mode.execution_model import (
    DigitizerResultBatch,
    ListModeRun,
)
from reference_lab.targets.list_mode.model import ListModeArtifact

_RESPONSE_UNIT = "ratio"

type _MappedListModeTarget = MappedQuantumTarget[ListModeArtifact]


@dataclass(frozen=True, slots=True)
class CorrelatedListModeRun:
    """Mapping-ordered raw target data retained as address-major arrays."""

    mapped_target: _MappedListModeTarget
    results: DigitizerResultBatch


def correlate_list_mode_run(
    mapped_target: _MappedListModeTarget,
    target_run: ListModeRun,
) -> CorrelatedListModeRun:
    """Validate and reorder one raw result batch without expanding shots."""

    artifact = mapped_target.artifact
    if target_run.artifact != artifact:
        raise ValueError("list-mode run does not retain the compiled target artifact")
    expected_addresses = tuple(
        result.result_address for result in mapped_target.mapping.results
    )
    if set(target_run.results.addresses) != set(expected_addresses):
        raise ValueError(
            "list-mode result rows must exactly cover every mapped acquisition"
        )
    if target_run.results.values.shape[1] != artifact.repetitions:
        raise ValueError("list-mode result shot count does not match the artifact")
    return CorrelatedListModeRun(
        mapped_target=mapped_target,
        results=target_run.results.select(expected_addresses),
    )


def realize_measurements(
    correlated_run: CorrelatedListModeRun,
) -> tuple[DomainResultValue[TargetAcquisitionAddress], ...]:
    """Project address rows directly to integrated-IQ measurement arrays."""

    return tuple(
        DomainResultValue(
            result.result_address,
            _realize_integrated_iq_value(
                cast(
                    "NDArray[np.complex128]",
                    correlated_run.results.values[row_index],
                ),
                cast(
                    "NDArray[np.bool_]",
                    correlated_run.results.available[row_index],
                ),
            ),
        )
        for row_index, result in enumerate(correlated_run.mapped_target.mapping.results)
    )


def _realize_integrated_iq_value(
    values: NDArray[np.complex128],
    available: NDArray[np.bool_],
) -> MeasurementValue:
    if not np.any(available):
        return MeasurementUnavailable.create(
            dtype="complex128",
            unit=_RESPONSE_UNIT,
            shape=(len(values),),
            reason="missing",
            metadata={"source": "virtual-demodulator", "detail": "no lock"},
        )
    if not np.all(available):
        raise ValueError(
            "one acquisition result cannot mix available and missing shots"
        )
    return MeasurementArray.create(
        dtype="complex128",
        unit=_RESPONSE_UNIT,
        values=values,
    )


__all__ = [
    "CorrelatedListModeRun",
    "correlate_list_mode_run",
    "realize_measurements",
]
