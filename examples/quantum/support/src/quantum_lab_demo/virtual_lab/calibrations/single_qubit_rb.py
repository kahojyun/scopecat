"""Accepted quarter-turn calibrations installed for the RB workflow."""

import math

from scopecat import Quantity
from scopecat_quantum import (
    DRAG,
    CalibrationCatalog,
    CalibrationId,
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


def single_qubit_rb_calibration_catalog() -> CalibrationCatalog:
    """Install the calibrated Y quarter turns used by the RB generator."""

    qubit = QubitId("q0")
    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            tuple(
                GateCalibration(
                    id=CalibrationId(f"single-qubit-rb.{gate_id}.q0"),
                    key=GateCalibrationKey(GateId(gate_id), (qubit,)),
                    pulse_template=PulseProgram(
                        id=PulseProgramId(f"single-qubit-rb.{gate_id}.template"),
                        body=Play(
                            id=PulseEventId("drive"),
                            signal=DriveSignal(qubit),
                            envelope=DRAG(
                                duration=Quantity(16, "ns"),
                                amplitude=Quantity(0.2, "arb"),
                                sigma=Quantity(4, "ns"),
                                beta=Quantity(0.5, "ns"),
                                phase=phase,
                            ),
                        ),
                    ),
                )
                for gate_id, phase in (
                    ("y90", Quantity(math.pi / 2, "rad")),
                    ("ym90", Quantity(-math.pi / 2, "rad")),
                )
            )
        )
    )


__all__ = ["single_qubit_rb_calibration_catalog"]
