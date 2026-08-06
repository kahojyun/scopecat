from __future__ import annotations

import runpy
from pathlib import Path
from typing import cast

EXAMPLE_ROOT = Path(__file__).parents[1]
NOTEBOOKS_DIR = EXAMPLE_ROOT / "notebooks"


def test_drag_beta_golden_notebook_executes() -> None:
    """The one user-facing notebook must complete its real daemon workflow."""

    namespace = runpy.run_path(str(NOTEBOOKS_DIR / "30_drag_calibration.py"))
    summary = cast("dict[str, object]", namespace["drag_beta_summary"])

    assert summary["status"] == "completed"
    assert summary["point_count"] == 15
    assert summary["candidate_run_uses_analysis"]
    assert summary["accepted_as_default"]
    assert summary["default_restored"]
