import subprocess
import sys

import scopecat as sc
from scopecat.api.calibration_planner import CalibrationPlanningContext
from scopecat.automation import (
    CalibrationDependencyEvidence,
    CalibrationDependencyRequirement,
    CalibrationObservation,
    CalibrationTargetRef,
    calibration,
)


def test_root_facade_exports_calibration_authoring_contract() -> None:
    assert sc.calibration is calibration
    assert sc.CalibrationObservation is CalibrationObservation
    assert sc.CalibrationDependencyRequirement is CalibrationDependencyRequirement
    assert sc.CalibrationDependencyEvidence is CalibrationDependencyEvidence
    assert sc.CalibrationTargetRef is CalibrationTargetRef
    assert sc.CalibrationPlanningContext is CalibrationPlanningContext
    assert {
        "calibration",
        "CalibrationObservation",
        "CalibrationTargetRef",
        "CalibrationPlanningContext",
    } <= set(sc.__all__)


def test_root_facade_keeps_calibration_runtime_lazy() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
import scopecat

if "scopecat.api.calibration_planner" in sys.modules:
    raise SystemExit("root import eagerly loaded the calibration planner")
if "CalibrationPlanningContext" not in scopecat.__all__:
    raise SystemExit("root facade does not publish calibration authoring")
scopecat.CalibrationPlanningContext
if "scopecat.api.calibration_planner" not in sys.modules:
    raise SystemExit("lazy calibration authoring export did not resolve")
""",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
