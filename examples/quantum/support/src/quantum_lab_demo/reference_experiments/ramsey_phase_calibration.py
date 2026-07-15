"""Unified gate/pulse reference program for a Ramsey phase scan.

The first X90 remains a logical gate resolved from the calibration catalog.  A
relative frame shift and a PulseTemplate-backed X90 candidate then live beside
it in the same authored program.  Readout stimulus and explicit acquisition are
parallel pulse statements, so this example exercises the physical experiment
surface without introducing another DSL.
"""

from __future__ import annotations

from collections.abc import Sequence

from scopecat import Quantity, QuantityType, ScalarType
from scopecat_quantum import (
    CalibrationCatalog,
    CalibrationId,
    GateCalibration,
    GateCalibrationCatalog,
    GateCalibrationKey,
    GateId,
    Play,
    PreparedQuantumTargetEntry,
    PulseEventId,
    PulseProgram,
    PulseProgramId,
    QubitId,
    TargetCompileEntryId,
    lower_quantum_program_to_pulses,
    prepare_quantum_target_entry,
)
from scopecat_quantum import authoring as q
from scopecat_quantum.pulses import Constant, DriveSignal

PHASE_INPUT = q.input(
    "phase",
    ScalarType(QuantityType(unit="rad")),
)

_FORMAL_QUBIT = q.qubit("formal")
_FORMAL_AMPLITUDE = q.input(
    "amplitude",
    ScalarType(QuantityType(unit="arb")),
)
_Q0 = q.qubit("q0")
_Q0_ID = QubitId("q0")
_X90 = q.single_qubit_gate("x90")

X90_CANDIDATE_ID = "x90.ramsey-phase"
X90_CALIBRATION_ID = CalibrationId("ramsey-phase.baseline.x90.q0")

_X90_DURATION = Quantity(16, "ns")
_X90_AMPLITUDE = Quantity(0.2, "arb")
_RAMSEY_DELAY = Quantity(16, "ns")
_READOUT_DURATION = Quantity(24, "ns")
_READOUT_AMPLITUDE = Quantity(0.35, "arb")

RAMSEY_X90_PULSE_TEMPLATE = q.pulse_template(
    "ramsey-phase.x90-candidate",
    q.play(
        q.drive(_FORMAL_QUBIT),
        q.constant(
            duration=_X90_DURATION,
            amplitude=_FORMAL_AMPLITUDE,
        ),
    ),
    elements=(_FORMAL_QUBIT,),
)

RAMSEY_READOUT_PULSE_TEMPLATE = q.pulse_template(
    "ramsey-phase.readout-stimulus",
    q.play(
        q.readout(_FORMAL_QUBIT),
        q.constant(
            duration=_READOUT_DURATION,
            amplitude=_READOUT_AMPLITUDE,
        ),
    ),
    elements=(_FORMAL_QUBIT,),
)


def ramsey_phase_program() -> q.Program:
    """Declare one bindable Ramsey point in the unified quantum DSL."""

    capture = q.acquire(
        _Q0,
        duration=_READOUT_DURATION,
        result="iq_shots",
    )
    return q.program(
        "ramsey-phase-calibration",
        q.sequence(
            _X90(_Q0),
            q.delay(q.drive(_Q0), _RAMSEY_DELAY),
            q.shift_phase(q.drive(_Q0), PHASE_INPUT),
            q.implements(
                _X90(_Q0),
                RAMSEY_X90_PULSE_TEMPLATE(_Q0, amplitude=_X90_AMPLITUDE),
                candidate=X90_CANDIDATE_ID,
            ),
            q.parallel(
                RAMSEY_READOUT_PULSE_TEMPLATE(_Q0),
                capture,
            ),
        ),
    )


def ramsey_phase_calibration_catalog() -> CalibrationCatalog:
    """Return the logical baseline X90 needed by the Ramsey declaration."""

    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=X90_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("x90"), (_Q0_ID,)),
                    pulse_template=PulseProgram(
                        id=PulseProgramId("ramsey-phase.baseline-x90"),
                        body=Play(
                            id=PulseEventId("drive"),
                            signal=DriveSignal(_Q0_ID),
                            envelope=Constant(
                                duration=_X90_DURATION,
                                amplitude=_X90_AMPLITUDE,
                            ),
                        ),
                    ),
                ),
            )
        )
    )


def prepare_ramsey_phase_entry(
    declaration: q.Program,
    phase: Quantity,
    *,
    entry_id: TargetCompileEntryId,
) -> PreparedQuantumTargetEntry:
    """Bind, refine, schedule, and prepare one Ramsey phase point."""

    bound = q.bind(declaration, {PHASE_INPUT.id: phase})
    lowered = lower_quantum_program_to_pulses(
        bound.verified,
        ramsey_phase_calibration_catalog(),
        output_id=PulseProgramId(f"{entry_id.value}.pulses"),
    )
    return prepare_quantum_target_entry(entry_id, lowered)


def prepare_ramsey_phase_scan(
    phases: Sequence[Quantity],
) -> tuple[q.Program, tuple[PreparedQuantumTargetEntry, ...]]:
    """Prepare an ordered phase scan from one declaration."""

    selected = tuple(phases)
    if not selected:
        msg = "Ramsey phase scans require at least one phase"
        raise ValueError(msg)
    declaration = ramsey_phase_program()
    return declaration, tuple(
        prepare_ramsey_phase_entry(
            declaration,
            phase,
            entry_id=TargetCompileEntryId(f"phase-{index}"),
        )
        for index, phase in enumerate(selected)
    )


__all__ = [
    "PHASE_INPUT",
    "RAMSEY_READOUT_PULSE_TEMPLATE",
    "RAMSEY_X90_PULSE_TEMPLATE",
    "X90_CALIBRATION_ID",
    "X90_CANDIDATE_ID",
    "prepare_ramsey_phase_entry",
    "prepare_ramsey_phase_scan",
    "ramsey_phase_calibration_catalog",
    "ramsey_phase_program",
]
