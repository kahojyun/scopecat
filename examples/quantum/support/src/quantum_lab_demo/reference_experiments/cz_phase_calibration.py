"""Unified two-qubit gate and coupler-pulse conditional-phase calibration."""

from __future__ import annotations

from scopecat import IntType, Quantity, QuantityType, ScalarType
from scopecat_quantum import (
    CalibrationCatalog,
    CalibrationId,
    Constant,
    DriveSignal,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateId,
    Play,
    PulseEventId,
    PulseProgram,
    PulseProgramId,
    QubitId,
)
from scopecat_quantum import authoring as q

CZ_CANDIDATE_ID = "cz.conditional-phase"
CZ_AMPLITUDE_INPUT = q.input(
    "coupler_amplitude",
    ScalarType(QuantityType(unit="arb")),
)
CONTROL_STATE_INPUT = q.input(
    "control_state",
    ScalarType(IntType(minimum=0, maximum=1)),
)
ANALYZER_PHASE_INPUT = q.input(
    "analyzer_phase",
    ScalarType(QuantityType(unit="rad")),
)

_CONTROL = q.qubit("q0")
_TARGET = q.qubit("q1")
_COUPLER = q.coupler("coupler-q0-q1")
_TARGET_ID = QubitId("q1")
_X = q.single_qubit_gate("x")
_X90 = q.single_qubit_gate("x90")
_CZ = q.two_qubit_gate("cz")
_FORMAL_QUBIT = q.qubit("formal-qubit")
_FORMAL_COUPLER = q.coupler("formal-coupler")
_FORMAL_CZ_AMPLITUDE = q.input(
    "amplitude",
    ScalarType(QuantityType(unit="arb")),
)

_SINGLE_QUBIT_DURATION = Quantity(16, "ns")
_X90_AMPLITUDE = Quantity(0.2, "arb")
_CZ_DURATION = Quantity(32, "ns")
_READOUT_DURATION = Quantity(24, "ns")
_READOUT_AMPLITUDE = Quantity(0.35, "arb")

X90_TARGET_CALIBRATION_ID = CalibrationId("cz-phase.baseline.x90.q1")

CZ_FLUX_PULSE_TEMPLATE = q.pulse_template(
    "cz-phase.coupler-flux",
    q.play(
        q.flux(_FORMAL_COUPLER),
        q.constant(
            duration=_CZ_DURATION,
            amplitude=_FORMAL_CZ_AMPLITUDE,
        ),
    ),
    elements=(_FORMAL_COUPLER,),
)

CZ_READOUT_PULSE_TEMPLATE = q.pulse_template(
    "cz-phase.readout-stimulus",
    q.play(
        q.readout(_FORMAL_QUBIT),
        q.constant(
            duration=_READOUT_DURATION,
            amplitude=_READOUT_AMPLITUDE,
        ),
    ),
    elements=(_FORMAL_QUBIT,),
)


def cz_conditional_phase_program() -> q.Program:
    """Declare one conditional-phase Ramsey point in the unified DSL."""

    control_capture = q.acquire(
        _CONTROL,
        duration=_READOUT_DURATION,
        result="control_iq_shots",
    )
    target_capture = q.acquire(
        _TARGET,
        duration=_READOUT_DURATION,
        result="target_iq_shots",
    )
    candidate = q.implements(
        _CZ(_CONTROL, _TARGET),
        CZ_FLUX_PULSE_TEMPLATE(
            _COUPLER,
            amplitude=CZ_AMPLITUDE_INPUT,
        ),
        resources=(_COUPLER,),
        candidate=CZ_CANDIDATE_ID,
    )
    return q.program(
        "cz-conditional-phase",
        q.sequence(
            q.repeat(_X(_CONTROL), CONTROL_STATE_INPUT),
            _X90(_TARGET),
            candidate,
            q.shift_phase(q.drive(_TARGET), ANALYZER_PHASE_INPUT),
            _X90(_TARGET),
            q.parallel(
                CZ_READOUT_PULSE_TEMPLATE(_CONTROL),
                control_capture,
                CZ_READOUT_PULSE_TEMPLATE(_TARGET),
                target_capture,
            ),
        ),
    )


def cz_phase_calibration_catalog() -> CalibrationCatalog:
    """Return the q1 X90 calibration unique to the CZ experiment.

    The surrounding q0 X operation deliberately reuses the lab's canonical X
    calibration, so one physical gate key never has competing demo definitions.
    """

    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=X90_TARGET_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("x90"), (_TARGET_ID,)),
                    pulse_template=_drive_template(
                        "cz-phase.baseline-x90-q1",
                        qubit=_TARGET_ID,
                        amplitude=_X90_AMPLITUDE,
                    ),
                ),
            )
        )
    )


def _drive_template(
    program_id: str,
    *,
    qubit: QubitId,
    amplitude: Quantity,
) -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=Play(
            id=PulseEventId("drive"),
            signal=DriveSignal(qubit),
            envelope=Constant(
                duration=_SINGLE_QUBIT_DURATION,
                amplitude=amplitude,
            ),
        ),
    )


__all__ = [
    "ANALYZER_PHASE_INPUT",
    "CONTROL_STATE_INPUT",
    "CZ_AMPLITUDE_INPUT",
    "CZ_CANDIDATE_ID",
    "CZ_FLUX_PULSE_TEMPLATE",
    "CZ_READOUT_PULSE_TEMPLATE",
    "X90_TARGET_CALIBRATION_ID",
    "cz_conditional_phase_program",
    "cz_phase_calibration_catalog",
]
