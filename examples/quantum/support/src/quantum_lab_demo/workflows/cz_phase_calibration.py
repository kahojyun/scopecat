"""Unified two-qubit gate and coupler-pulse conditional-phase calibration."""

from __future__ import annotations

from typing import Annotated

from scopecat import IntType, Quantity, QuantityType
from scopecat_quantum import (
    CalibrationId,
)
from scopecat_quantum import authoring as q

CZ_CANDIDATE_ID = "cz.conditional-phase"
_X = q.single_qubit_gate("x")
_X90 = q.single_qubit_gate("x90")
_CZ = q.two_qubit_gate("cz")

_CZ_DURATION = Quantity(32, "ns")
_READOUT_DURATION = Quantity(24, "ns")
_READOUT_AMPLITUDE = Quantity(0.35, "arb")

X90_TARGET_CALIBRATION_ID = CalibrationId("cz-phase.baseline.x90.q1")


@q.implementation(
    of=_CZ,
    candidate=CZ_CANDIDATE_ID,
    id="cz-phase.coupler-flux",
)
def cz_flux_candidate(
    control: q.Qubit,  # noqa: ARG001 - semantic gate operand
    target: q.Qubit,  # noqa: ARG001 - semantic gate operand
    coupler: q.Coupler,
    amplitude: Annotated[Quantity, QuantityType(unit="arb")],
) -> q.QuantumFragment:
    """Carry the CZ operands and its physical coupler as one typed call."""

    return q.play(
        q.flux(coupler),
        q.constant(
            duration=_CZ_DURATION,
            amplitude=amplitude,
        ),
    )


@q.pulse_template(id="cz-phase.readout-stimulus")
def cz_readout_pulse(qubit: q.Qubit) -> q.QuantumFragment:
    return q.play(
        q.readout(qubit),
        q.constant(
            duration=_READOUT_DURATION,
            amplitude=_READOUT_AMPLITUDE,
        ),
    )


@q.program(id="cz-conditional-phase")
def cz_conditional_phase(
    control: q.Qubit,
    target: q.Qubit,
    coupler: q.Coupler,
    control_state: Annotated[int, IntType(minimum=0, maximum=1)],
    coupler_amplitude: Annotated[Quantity, QuantityType(unit="arb")],
    analyzer_phase: Annotated[Quantity, QuantityType(unit="rad")],
) -> q.QuantumFragment:
    """Declare one conditional-phase Ramsey point in the unified DSL."""

    control_capture = q.acquire(
        control,
        duration=_READOUT_DURATION,
        result="control_iq_shots",
    )
    target_capture = q.acquire(
        target,
        duration=_READOUT_DURATION,
        result="target_iq_shots",
    )
    candidate = cz_flux_candidate(
        control,
        target,
        coupler,
        amplitude=coupler_amplitude,
    )
    return q.sequence(
        q.repeat(_X(control), control_state),
        _X90(target),
        candidate,
        q.shift_phase(q.drive(target), analyzer_phase),
        _X90(target),
        q.parallel(
            cz_readout_pulse(control),
            control_capture,
            cz_readout_pulse(target),
            target_capture,
        ),
    )


__all__ = [
    "CZ_CANDIDATE_ID",
    "X90_TARGET_CALIBRATION_ID",
    "cz_conditional_phase",
    "cz_flux_candidate",
    "cz_readout_pulse",
]
