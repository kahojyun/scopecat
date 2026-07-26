"""Deterministic acquisition responses registered by authored Program id."""

from __future__ import annotations

from typing import cast

from scopecat import Quantity
from scopecat_quantum._ids import AcquisitionSlotId
from scopecat_quantum.program_targets import PreparedQuantumTargetEntry
from scopecat_quantum.targets import TargetAcquisitionAddress

from quantum_lab_demo.response_registry import (
    QuantumLabResponseRegistry,
    QuantumLabResponseRequest,
)
from quantum_lab_demo.targets.fake_list_mode import FakeAcquisitionResponse
from quantum_lab_demo.virtual_lab.responses.drag_beta import (
    DragBetaAcquisitionResponse,
    DragBetaResponsePoint,
)
from quantum_lab_demo.workflows.drag_beta_calibration import (
    drag_beta_program,
)


def quantum_lab_response_registry() -> QuantumLabResponseRegistry:
    """Return the fake lab's Program-to-response policy."""

    return QuantumLabResponseRegistry(
        {
            drag_beta_program.id: _drag_beta_response,
        }
    )


def _drag_beta_response(
    request: QuantumLabResponseRequest,
) -> FakeAcquisitionResponse:
    [result] = request.program.results
    return DragBetaAcquisitionResponse(
        points=tuple(
            DragBetaResponsePoint(
                address=_result_address(entry, result.acquisition_slot_id),
                beta=cast("Quantity", point.value("beta")),
                amplification=cast("int", point.value("amplification")),
            )
            for entry, point in zip(request.entries, request.points, strict=True)
        ),
        shots=request.shots,
    )


def _result_address(
    entry: PreparedQuantumTargetEntry,
    slot_id: AcquisitionSlotId,
) -> TargetAcquisitionAddress:
    [address] = tuple(
        address for address in entry.acquisition_addresses if address.slot_id == slot_id
    )
    return address


__all__ = ["quantum_lab_response_registry"]
