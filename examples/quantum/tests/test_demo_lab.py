from __future__ import annotations

import runpy
from pathlib import Path

import pytest

EXAMPLE_ROOT = Path(__file__).parents[1]
NOTEBOOKS_DIR = EXAMPLE_ROOT / "notebooks"

NOTEBOOK_CASES = (
    ("getting_started/01_open_project.py", "summary"),
    ("getting_started/02_edit_config.py", "summary"),
    ("getting_started/03_define_experiment.py", "summary"),
    ("getting_started/04_run_and_read_data.py", "summary"),
    ("getting_started/05_manual_analysis.py", "summary"),
    ("getting_started/06_promote_analysis_step.py", "summary"),
    ("getting_started/07_rerun_candidate_config.py", "summary"),
    ("authoring/01_template_and_scratch.py", "authoring_summary"),
    ("authoring/02_instrument_composition.py", "mixed_execution_results"),
    ("authoring/03_point_bound_sequence.py", "point_bound_summary"),
    ("authoring/04_recursive_results.py", "recursive_result_summary"),
    ("authoring/05_mixed_gate_pulse.py", "compiled_summary"),
    ("calibration/01_drag_beta.py", "drag_beta_summary"),
    ("calibration/02_cz_phase.py", "summary"),
    ("integration/01_opaque_collection.py", "opaque_collection_summary"),
)


@pytest.mark.parametrize(("relative_path", "completion_marker"), NOTEBOOK_CASES)
def test_notebook_executes(
    relative_path: str,
    completion_marker: str,
) -> None:
    """Notebooks are executable documentation; exact contracts live in unit tests."""

    namespace = runpy.run_path(str(NOTEBOOKS_DIR / relative_path))

    assert completion_marker in namespace
