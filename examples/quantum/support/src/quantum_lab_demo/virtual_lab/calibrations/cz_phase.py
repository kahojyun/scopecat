"""Accepted CZ-workflow calibrations installed by the demo virtual lab."""

from scopecat import Quantity
from scopecat_quantum import (
    CalibrationCatalog,
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

from quantum_lab_demo.workflows.cz_phase_calibration import (
    X90_TARGET_CALIBRATION_ID,
)


def cz_phase_calibration_catalog() -> CalibrationCatalog:
    """Install the q1 X90 baseline needed by the CZ workflow."""

    target = QubitId("q1")
    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=X90_TARGET_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("x90"), (target,)),
                    pulse_template=PulseProgram(
                        id=PulseProgramId("cz-phase.baseline-x90-q1"),
                        body=Play(
                            id=PulseEventId("drive"),
                            signal=DriveSignal(target),
                            envelope=Constant(
                                duration=Quantity(16, "ns"),
                                amplitude=Quantity(0.2, "arb"),
                            ),
                        ),
                    ),
                ),
            )
        )
    )


__all__ = ["cz_phase_calibration_catalog"]
