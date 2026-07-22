"""Deterministic acquisition responses registered by authored Program id."""

from __future__ import annotations

from typing import cast

from scopecat import Quantity
from scopecat_quantum import (
    AcquisitionSlotId,
    PreparedQuantumTargetEntry,
    TargetAcquisitionAddress,
)

from quantum_lab_demo.reference_experiments.cz_phase_calibration import (
    cz_conditional_phase,
)
from quantum_lab_demo.reference_experiments.cz_phase_response import (
    CzPhaseAcquisitionResponse,
    CzPhaseResponsePoint,
)
from quantum_lab_demo.reference_experiments.drag_beta_calibration import (
    drag_beta_program,
)
from quantum_lab_demo.reference_experiments.drag_beta_response import (
    DragBetaAcquisitionResponse,
    DragBetaResponsePoint,
)
from quantum_lab_demo.reference_experiments.single_qubit_rb import (
    single_qubit_rb_program,
)
from quantum_lab_demo.reference_experiments.single_qubit_rb_response import (
    SingleQubitRbAcquisitionResponse,
    SingleQubitRbResponsePoint,
)
from quantum_lab_demo.response_registry import (
    QuantumLabResponseRegistry,
    QuantumLabResponseRequest,
)
from quantum_lab_demo.targets.fake_list_mode import FakeAcquisitionResponse


def quantum_lab_response_registry() -> QuantumLabResponseRegistry:
    """Return the fake lab's Program-to-response policy."""

    return QuantumLabResponseRegistry(
        {
            drag_beta_program.id: _drag_beta_response,
            cz_conditional_phase.id: _cz_phase_response,
            single_qubit_rb_program.id: _single_qubit_rb_response,
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


def _cz_phase_response(
    request: QuantumLabResponseRequest,
) -> FakeAcquisitionResponse:
    control_result, target_result = request.program.results
    return CzPhaseAcquisitionResponse(
        points=tuple(
            CzPhaseResponsePoint(
                control_address=_result_address(
                    entry,
                    control_result.acquisition_slot_id,
                ),
                target_address=_result_address(
                    entry,
                    target_result.acquisition_slot_id,
                ),
                amplitude=cast("Quantity", point.value("coupler_amplitude")),
                control_state=cast("int", point.value("control_state")),
                analyzer_phase=cast("Quantity", point.value("analyzer_phase")),
            )
            for entry, point in zip(request.entries, request.points, strict=True)
        ),
        shots=request.shots,
    )


def _single_qubit_rb_response(
    request: QuantumLabResponseRequest,
) -> FakeAcquisitionResponse:
    [result] = request.program.results
    return SingleQubitRbAcquisitionResponse(
        points=tuple(
            SingleQubitRbResponsePoint(
                address=_result_address(entry, result.acquisition_slot_id),
                length=cast("int", point.value("length")),
                seed=cast("int", point.value("seed")),
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
