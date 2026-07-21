"""Accepted logical-to-pulse calibrations for the demo quantum lab."""

from __future__ import annotations

from scopecat_quantum import (
    CalibrationCatalog,
    GateCalibrationCatalog,
    MeasurementCalibrationCatalog,
)

from quantum_lab_demo.reference_experiments.cz_phase_calibration import (
    cz_phase_calibration_catalog,
)
from quantum_lab_demo.reference_experiments.drag_beta_calibration import (
    baseline_calibration_catalog,
)
from quantum_lab_demo.reference_experiments.fake_x_count import (
    fake_x_count_calibration_catalog,
)


def quantum_lab_calibration_catalog() -> CalibrationCatalog:
    """Build the lab catalog with exactly one owner for every physical key.

    Catalog composition is lab configuration rather than compilation behavior.
    Keeping it here makes ownership explicit: fake X owns q0 X/readout, DRAG
    owns q0 X90/Xm90, and CZ contributes only q1 X90.
    """

    fake_x = fake_x_count_calibration_catalog()
    drag = baseline_calibration_catalog()
    cz = cz_phase_calibration_catalog()
    return CalibrationCatalog(
        gates=GateCalibrationCatalog(
            (*fake_x.gates.entries, *drag.gates.entries, *cz.gates.entries)
        ),
        measurements=MeasurementCalibrationCatalog(fake_x.measurements.entries),
    )


__all__ = ["quantum_lab_calibration_catalog"]
