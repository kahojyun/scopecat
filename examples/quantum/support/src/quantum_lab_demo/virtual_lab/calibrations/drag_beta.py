"""Accepted DRAG calibrations installed by the demo virtual lab."""

from __future__ import annotations

import math

from scopecat import Quantity
from scopecat_quantum import (
    DRAG,
    CalibrationCatalog,
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

from quantum_lab_demo.workflows.drag_beta_calibration import (
    DEFAULT_BASELINE_BETA,
    X90_CALIBRATION_ID,
    XM90_CALIBRATION_ID,
)

_Q0_ID = QubitId("q0")


def baseline_calibration_catalog(
    beta: Quantity = DEFAULT_BASELINE_BETA,
) -> CalibrationCatalog:
    """Install the virtual lab's accepted X90 and Xm90 baselines."""

    selected_beta = Quantity(float(beta.to("ns").value), "ns")
    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                GateCalibration(
                    id=X90_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("x90"), (_Q0_ID,)),
                    pulse_template=_drag_template(
                        "x90-baseline-template",
                        beta=selected_beta,
                        phase=Quantity(0, "rad"),
                    ),
                ),
                GateCalibration(
                    id=XM90_CALIBRATION_ID,
                    key=GateCalibrationKey(GateId("xm90"), (_Q0_ID,)),
                    pulse_template=_drag_template(
                        "xm90-baseline-template",
                        beta=selected_beta,
                        phase=Quantity(math.pi, "rad"),
                    ),
                ),
            )
        ),
    )


def _drag_template(program_id: str, *, beta: Quantity, phase: Quantity) -> PulseProgram:
    return PulseProgram(
        id=PulseProgramId(program_id),
        body=Play(
            id=PulseEventId("drive"),
            signal=DriveSignal(_Q0_ID),
            envelope=DRAG(
                duration=Quantity(16, "ns"),
                amplitude=Quantity(0.2, "arb"),
                sigma=Quantity(4, "ns"),
                beta=beta,
                phase=phase,
            ),
        ),
    )


__all__ = ["baseline_calibration_catalog"]
