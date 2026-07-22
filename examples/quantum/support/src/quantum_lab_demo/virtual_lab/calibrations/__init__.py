"""Accepted logical-to-pulse calibrations for the demo quantum lab."""

from __future__ import annotations

from scopecat_quantum import (
    CalibrationCatalog,
    GateCalibrationCatalog,
    MeasurementCalibrationCatalog,
)

from quantum_lab_demo.virtual_lab.calibrations.cz_phase import (
    cz_phase_calibration_catalog,
)
from quantum_lab_demo.virtual_lab.calibrations.drag_beta import (
    baseline_calibration_catalog,
)
from quantum_lab_demo.virtual_lab.calibrations.fake_x_count import (
    fake_x_count_calibration_catalog,
)
from quantum_lab_demo.virtual_lab.calibrations.single_qubit_rb import (
    single_qubit_rb_calibration_catalog,
)


def quantum_lab_calibration_catalog() -> CalibrationCatalog:
    """Build the lab catalog with exactly one owner for every physical key.

    Catalog composition is lab configuration rather than compilation behavior.
    Keeping it here makes ownership explicit: fake X owns q0 X/readout, DRAG
    owns q0 X90/Xm90, RB owns q0 Y90/Ym90, and CZ contributes only q1 X90.
    """

    fake_x = fake_x_count_calibration_catalog()
    drag = baseline_calibration_catalog()
    rb = single_qubit_rb_calibration_catalog()
    cz = cz_phase_calibration_catalog()
    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (
                *fake_x.gates.entries,
                *drag.gates.entries,
                *rb.gates.entries,
                *cz.gates.entries,
            )
        ),
        measurements=MeasurementCalibrationCatalog(fake_x.measurements.entries),
    )


__all__ = ["quantum_lab_calibration_catalog"]
