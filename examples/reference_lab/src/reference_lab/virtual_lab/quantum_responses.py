"""Deterministic acquisition responses for the fake quantum lab."""

from __future__ import annotations

from typing import cast

from scopecat import Quantity
from scopecat_quantum import authoring as quantum
from scopecat_quantum._ids import AcquisitionSlotId
from scopecat_quantum.program_targets import PreparedQuantumTargetEntry
from scopecat_quantum.targets import TargetAcquisitionAddress

from reference_lab.point_values import QuantumLabPointValues
from reference_lab.targets.fake_list_mode import FakeAcquisitionResponse
from reference_lab.virtual_lab.responses.drag_beta import (
    DragBetaAcquisitionResponse,
    DragBetaResponsePoint,
)
from reference_lab.workflows.drag_beta_calibration import (
    drag_beta_program,
)


def quantum_lab_response(
    program: quantum.Program,
    points: tuple[QuantumLabPointValues, ...],
    entries: tuple[PreparedQuantumTargetEntry, ...],
    shots: int,
) -> FakeAcquisitionResponse | None:
    """Select the one workflow-specific response used by the demo."""

    if program.id != drag_beta_program.id:
        return None
    [result] = program.results
    return DragBetaAcquisitionResponse(
        points=tuple(
            DragBetaResponsePoint(
                address=_result_address(entry, result.acquisition_slot_id),
                beta=cast("Quantity", point.value("beta")),
                amplification=cast("int", point.value("amplification")),
            )
            for entry, point in zip(entries, points, strict=True)
        ),
        shots=shots,
    )


def _result_address(
    entry: PreparedQuantumTargetEntry,
    slot_id: AcquisitionSlotId,
) -> TargetAcquisitionAddress:
    [address] = tuple(
        address for address in entry.acquisition_addresses if address.slot_id == slot_id
    )
    return address


__all__ = ["quantum_lab_response"]
