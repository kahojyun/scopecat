"""Run the supported DRAG-beta calibration from measurement to undo."""

from __future__ import annotations

# %%
import scopecat as sc

from reference_lab.configuration import EXAMPLE_ROOT
from reference_lab.notebook import show
from reference_lab.workflows.drag_beta_analysis import drag_beta_analysis
from reference_lab.workflows.drag_beta_experiment import drag_beta_experiment
from reference_lab.workflows.drag_beta_verification import (
    DRAG_BETA_VERIFICATION_SCHEMA,
    drag_beta_candidate_verification,
)
from reference_lab.workflows.production_drag_gate import production_drag_experiment

# %%
lab = sc.open_project(EXAMPLE_ROOT).connect()
prepared = lab.prepare(drag_beta_experiment())
preview = prepared.preview()
baseline_run = prepared.run(
    name="DRAG beta rough calibration",
    tags=("calibration", "gate-pulse"),
)

# %%
analysis = baseline_run.analyze(drag_beta_analysis())
candidate = analysis.candidate_config()
fit_report = baseline_run.published_analysis(analysis.id).artifact("fit-report")
[proposal] = analysis.parameter_proposals

# A candidate run records its analysis provenance without changing the default.
candidate_run = lab.run(
    drag_beta_experiment(),
    config=candidate,
    name="DRAG beta candidate check",
    tags=("calibration", "candidate"),
)

# %%
verification = lab.analyze(
    drag_beta_candidate_verification(
        baseline_run=baseline_run,
        candidate_run=candidate_run,
    )
)
verification_decision = verification.fact_as(
    "decision",
    DRAG_BETA_VERIFICATION_SCHEMA,
)
verification_report = verification.artifact("verification-report")
if not verification_decision.accepted:
    raise RuntimeError("DRAG beta candidate did not improve the verification scan")

# Only the cross-run verification decision authorizes changing the default.
accepted = lab.config.accept(
    analysis,
    verified_by=(verification, "decision"),
    actor="nightly-calibration",
    note="accept the project-verified DRAG candidate",
)

production_run = lab.run(
    production_drag_experiment(),
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
    "analysis": analysis.id,
    "proposal_id": proposal.id,
    "output_kinds": [output.kind for output in analysis.outputs],
    "execution_evidence": len(analysis.executions),
    "fit_report": fit_report.entry.filename,
    "proposal_evidence": proposal.evidence_output_ids,
    "verification": verification.id,
    "verification_subject": verification.view.analysis.subject.kind,
    "verification_inputs": [
        (item.id, item.run_id, item.role) for item in verification.inputs
    ],
    "verification_improvement": verification_decision.improvement,
    "verification_accepted": verification_decision.accepted,
    "verification_report": verification_report.entry.filename,
    "verification_is_project_owned": all(
        entry.id != verification.id
        for entry in (*baseline_run.manifest.records, *candidate_run.manifest.records)
    ),
    "accepted_verification": (
        accepted.entry.source.verification.analysis_record_id
        if accepted.entry.source.kind == "candidate_config"
        and accepted.entry.source.verification is not None
        else None
    ),
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
        restored.activation.entry_content_hash
        == accepted.activation.previous_entry_content_hash
    ),
}
show(drag_beta_summary)
