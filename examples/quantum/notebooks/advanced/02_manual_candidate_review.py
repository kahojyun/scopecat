"""Advanced: review and activate one analysis candidate explicitly."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.virtual_lab import (
    DRAG_BETA_PARAMETER_COLUMN,
    q0_drag_beta_row,
)
from quantum_lab_demo.workflows.drag_beta_analysis import analyze_drag_beta_run
from quantum_lab_demo.workflows.drag_beta_experiment import (
    BETA,
    DRAG_BETA_POINTS,
    DRAG_BETA_SPAN,
    drag_beta_template,
)

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()
parameter_scan = sc.param_axis(
    BETA,
    q0_drag_beta_row(),
    DRAG_BETA_PARAMETER_COLUMN,
    span=DRAG_BETA_SPAN,
    points=DRAG_BETA_POINTS,
)
completed_run = (
    lab.prepare(drag_beta_template())
    .scan(parameter_scan)
    .run(
        name="DRAG beta manual review",
        tags=("calibration", "advanced", "manual-review"),
    )
)
result = analyze_drag_beta_run(completed_run)
saved_analysis = result.analysis.save()
if result.proposal_id is None:
    raise RuntimeError("the DRAG fit did not produce an eligible proposal")
candidate = result.analysis.candidate_config()

# %%
# Explicit review and generation control remain available for audited operator
# workflows. They are not required by the ordinary lab.config.accept() path.
review = lab.review_parameter_proposal(
    completed_run,
    result.proposal_id,
    decision="approved",
    note="fit evidence and scan coverage reviewed manually",
)
generation = lab.config_registry().active_state
if generation is None:
    raise RuntimeError("the project has no default configuration")
activated = lab.activate(
    candidate,
    entry_id=f"manual-drag-beta-{completed_run.id}",
    expected_generation=generation.generation,
    activation_note="select the manually reviewed DRAG beta",
)
restored = lab.rollback(
    expected_generation=activated.active_state.generation,
    note="restore the previous default after the advanced example",
)

# %%
advanced_candidate_summary = {
    "analysis": saved_analysis.record.id,
    "proposal": result.proposal_id,
    "review": review.decision,
    "activated_entry": activated.entry.id,
    "activated_generation": activated.active_state.generation,
    "restored_entry": restored.active_state.active_entry_id,
}
print(advanced_candidate_summary)
