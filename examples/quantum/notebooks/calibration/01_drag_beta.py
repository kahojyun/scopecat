"""Run the supported DRAG-beta calibration from measurement to undo."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import EXAMPLE_ROOT
from quantum_lab_demo.workflows.drag_beta_analysis import analyze_drag_beta_run
from quantum_lab_demo.workflows.drag_beta_experiment import drag_beta_template
from quantum_lab_demo.workflows.production_drag_gate import production_drag_template

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()
experiment = lab.prepare(drag_beta_template())
preview = experiment.preview()
baseline_run = experiment.run(
    name="DRAG beta rough calibration",
    tags=("calibration", "gate-pulse"),
)

# %%
result = analyze_drag_beta_run(baseline_run)
saved_analysis = result.analysis.save()
candidate = result.analysis.candidate_config()

# A candidate run records its analysis provenance without changing the default.
candidate_run = lab.prepare(drag_beta_template(), config=candidate).run(
    name="DRAG beta candidate check",
    tags=("calibration", "candidate"),
)

# %%
accepted = lab.config.accept(
    candidate,
    operator="nightly-calibration",
    note="accept the reviewed DRAG fit",
)

production_run = lab.prepare(production_drag_template()).run(
    name="Production X90 with accepted DRAG beta",
    tags=("calibration", "production-gate", "active-config"),
)

# %%
# Undo restores the previous default while retaining the durable audit trail.
restored = lab.config.undo(
    note="restore the previous default after the calibration example",
)
candidate_source = candidate_run.manifest.config_source
production_source = production_run.manifest.config_source

drag_beta_summary = {
    "status": baseline_run.manifest.status,
    "point_count": preview.point_count,
    "beta_hat": result.fit.beta_hat,
    "analysis": saved_analysis.record.id,
    "proposal_id": result.proposal_id,
    "candidate_run_uses_analysis": (
        candidate_source is not None
        and candidate_source.kind == "analysis_candidate"
        and candidate_source.proposal_id == candidate.proposal_id
    ),
    "accepted_as_default": (
        production_source is not None
        and production_source.content_hash == accepted.entry.content_hash
    ),
    "default_restored": (
        restored.active_state.active_entry_content_hash
        == accepted.activation.previous_entry_content_hash
    ),
}
print(drag_beta_summary)
