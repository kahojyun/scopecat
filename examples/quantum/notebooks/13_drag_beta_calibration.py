"""Unified gate/pulse UX: run, review, activate, and roll back DRAG beta."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import (
    QuantumLabCompiler,
    notebook_workspace,
    quantum_lab,
)
from quantum_lab_demo.reference_experiments import (
    BETA,
    DRAG_BETA_POINTS,
    DRAG_BETA_SPAN,
    analyze_drag_beta_run,
    drag_beta_template,
    production_drag_template,
)
from quantum_lab_demo.reference_experiments.drag_beta_experiment import (
    drag_beta_program,
)
from quantum_lab_demo.reference_experiments.production_drag_gate import (
    production_drag_program,
    production_x90_event_id,
    trusted_xm90_event_id,
)
from quantum_lab_demo.virtual_lab import (
    DRAG_BETA_PARAMETER_COLUMN,
    QUBIT_PARAMETER_TABLE,
    q0_drag_beta_row,
)

# %%
# One Workspace experiment carries both levels of intent:
#
# baseline X90 gate -> N * [PulseTemplate DRAG X90, PulseTemplate DRAG Xm90]
# -> baseline Xm90 gate -> parallel(readout play, explicit acquire).
#
# ``beta`` binds the pulse envelopes while ``amplification`` binds the repeat
# count in that same Program declaration. The accepted ``drag_beta``
# parameter-table cell centers a point-local overlay; each point then reaches
# the same compiler as an ordinary resolved Program input.
workspace = notebook_workspace("13-drag-beta-calibration")
lab = quantum_lab(workspace=workspace)
system = lab.system
assert system is not None
compiler = system.domain_compiler
assert isinstance(compiler, QuantumLabCompiler)
parameter_scan = sc.param_axis(
    BETA,
    q0_drag_beta_row(),
    DRAG_BETA_PARAMETER_COLUMN,
    span=DRAG_BETA_SPAN,
    points=DRAG_BETA_POINTS,
)
experiment = lab.prepare(drag_beta_template).scan(parameter_scan)

# %%
preview = experiment.preview()
completed_run = experiment.run(
    name="DRAG beta rough calibration",
    tags=("reference", "calibration", "gate-pulse"),
)

# %%
# The fit produces native Analysis evidence and, only when its explicit quality
# guardrails pass, a standard parameter proposal. Saving publishes both under
# the source run; it still does not change active configuration.
result = analyze_drag_beta_run(completed_run)
saved_analysis = result.analysis.save()
if result.proposal_id is None:
    msg = "the reference DRAG fit should clear its proposal guardrails"
    raise RuntimeError(msg)
candidate = result.analysis.candidate_config()
candidate_config = lab.resolve_config(config=candidate)

# Candidate configs can be previewed before review without changing the active
# registry state. A reviewer may instead choose ``decision='rejected'``; the
# registry will then refuse to activate that proposal.
candidate_preview = (
    lab.prepare(
        drag_beta_template,
        config=candidate,
    )
    .scan(parameter_scan)
    .preview()
)

# %%
# This dedicated demo workspace first installs the source config as its rollback
# point. In a shared lab, preserve the pre-existing active entry instead of
# assuming that installing the source snapshot is a side-effect-free baseline.
# Before selecting the candidate, execute the same production-gate template
# against this active baseline. This gives the later provenance verification a
# compiled-and-executed reference instead of comparing only scan coordinates.
baseline_activation = lab.activate_config(
    completed_run.config,
    entry_id=f"drag-beta-baseline-{completed_run.id}",
)
baseline_production_run = lab.prepare(
    production_drag_template,
    config="active",
).run(
    name="Production X90 with baseline DRAG beta",
    tags=("reference", "production-gate", "baseline"),
)

# The approval and candidate selection are append-only, atomic transitions.
review = lab.review_parameter_proposal(
    completed_run,
    result.proposal_id,
    decision="approved",
    note="fit evidence and scan coverage reviewed",
)
activation = lab.activate(
    candidate,
    entry_id=f"drag-beta-candidate-{completed_run.id}",
    expected_generation=baseline_activation.active_state.generation,
    activation_note="select reviewed q0 DRAG beta",
)

# %%
# ``config='active'`` now drives two first-class uses of the same parameter. It
# recenters a possible follow-up scan and binds the production X90 ProgramInput.
# The Xm90 catalog contains only a fixed trusted reference, so it cannot move
# with the DUT and hide a correlated implementation error.
active_preview = (
    lab.prepare(
        drag_beta_template,
        config="active",
    )
    .scan(parameter_scan)
    .preview()
)
active_production_run = lab.prepare(
    production_drag_template,
    config="active",
).run(
    name="Production X90 with accepted DRAG beta",
    tags=("reference", "production-gate", "active-config", "provenance"),
)
active_config = lab.resolve_config(config="active")

# %%
# Rollback is another atomic, generation-checked registry transition. It keeps
# the proposal, review, activation, production execution, and rollback as
# durable evidence while restoring both scan and compiled production behavior.
rollback = lab.rollback(
    expected_generation=activation.active_state.generation,
    note="restore baseline after production-gate provenance verification",
)
restored_preview = (
    lab.prepare(
        drag_beta_template,
        config="active",
    )
    .scan(parameter_scan)
    .preview()
)
restored_production_run = lab.prepare(
    production_drag_template,
    config="active",
).run(
    name="Production X90 after DRAG beta rollback",
    tags=("reference", "production-gate", "rollback"),
)
restored_config = lab.resolve_config(config="active")


def _scan_center(prepared_preview: sc.ExperimentPreview) -> float:
    beta_values = sorted(
        {
            _quantity_in_unit(point.coordinates["beta"], "ns")
            for point in prepared_preview.points
        }
    )
    return beta_values[len(beta_values) // 2]


def _quantity_in_unit(value: object, unit: str) -> float:
    assert isinstance(value, sc.Quantity)
    return float(value.to(unit).value)


[calibration_batch] = compiler.trace.preparations(drag_beta_program.id)
compiler_beta_values = tuple(
    sorted(
        {
            _quantity_in_unit(point.value("beta"), "ns")
            for point in calibration_batch.points
        }
    )
)
baseline_gate, active_gate, restored_gate = compiler.trace.preparations(
    production_drag_program.id
)
baseline_entry, active_entry, restored_entry = (
    batch.entries[0] for batch in (baseline_gate, active_gate, restored_gate)
)
baseline_production_samples = baseline_gate.event_samples(
    baseline_entry,
    production_x90_event_id(baseline_entry),
)
active_production_samples = active_gate.event_samples(
    active_entry,
    production_x90_event_id(active_entry),
)
restored_production_samples = restored_gate.event_samples(
    restored_entry,
    production_x90_event_id(restored_entry),
)
baseline_reference_samples = baseline_gate.event_samples(
    baseline_entry,
    trusted_xm90_event_id(baseline_entry),
)
active_reference_samples = active_gate.event_samples(
    active_entry,
    trusted_xm90_event_id(active_entry),
)
restored_reference_samples = restored_gate.event_samples(
    restored_entry,
    trusted_xm90_event_id(restored_entry),
)
baseline_source = baseline_production_run.manifest.config_source
active_source = active_production_run.manifest.config_source
restored_source = restored_production_run.manifest.config_source
if baseline_source is None or active_source is None or restored_source is None:
    msg = "production runs should retain registry provenance"
    raise RuntimeError(msg)
production_waveform_changed = baseline_production_samples != active_production_samples
trusted_reference_unchanged = (
    baseline_reference_samples == active_reference_samples == restored_reference_samples
)
rollback_restored_waveform = restored_production_samples == baseline_production_samples
active_artifact_changed = (
    active_gate.artifact_fingerprint != baseline_gate.artifact_fingerprint
)
rollback_restored_artifact = (
    restored_gate.artifact_fingerprint == baseline_gate.artifact_fingerprint
)
baseline_config_hash_matches = (
    baseline_production_run.manifest.config_content_hash
    == baseline_source.content_hash
    == baseline_activation.entry.content_hash
)
active_config_hash_matches = (
    active_production_run.manifest.config_content_hash
    == active_source.content_hash
    == activation.entry.content_hash
)
restored_config_hash_matches = (
    restored_production_run.manifest.config_content_hash
    == restored_source.content_hash
    == baseline_activation.entry.content_hash
)
baseline_source_matches = (
    baseline_production_run.manifest.status == "completed"
    and baseline_source.entry_id == baseline_activation.entry.id
    and baseline_source.registry_generation
    == baseline_activation.active_state.generation
)
active_source_matches = (
    active_production_run.manifest.status == "completed"
    and active_source.entry_id == activation.entry.id
    and active_source.registry_generation == activation.active_state.generation
)
restored_source_matches = (
    restored_production_run.manifest.status == "completed"
    and restored_source.entry_id == baseline_activation.entry.id
    and restored_source.registry_generation == rollback.active_state.generation
)
production_evidence_checks = {
    "production_waveform_changed": production_waveform_changed,
    "trusted_reference_unchanged": trusted_reference_unchanged,
    "rollback_restored_waveform": rollback_restored_waveform,
    "active_artifact_changed": active_artifact_changed,
    "rollback_restored_artifact": rollback_restored_artifact,
    "baseline_config_hash_matches": baseline_config_hash_matches,
    "active_config_hash_matches": active_config_hash_matches,
    "restored_config_hash_matches": restored_config_hash_matches,
    "baseline_source_matches": baseline_source_matches,
    "active_source_matches": active_source_matches,
    "restored_source_matches": restored_source_matches,
}
failed_evidence_checks = tuple(
    name for name, passed in production_evidence_checks.items() if not passed
)
if failed_evidence_checks:
    msg = "production DRAG provenance evidence failed: " + ", ".join(
        failed_evidence_checks
    )
    raise RuntimeError(msg)

drag_beta_summary = {
    "status": completed_run.manifest.status,
    "point_count": preview.point_count,
    "physical_executions": compiler.trace.physical_execution_count,
    "beta_hat": result.fit.beta_hat,
    "fit_rmse": result.fit.rmse,
    "quality": {
        "score": result.assessment.quality_score,
        "kind": result.assessment.score_kind,
        "recommendation": result.assessment.recommendation,
    },
    "analysis_record_id": saved_analysis.record.id,
    "proposal_id": result.proposal_id,
    "review": review.decision,
    "registry_generations": {
        "baseline": baseline_activation.active_state.generation,
        "candidate": activation.active_state.generation,
        "rollback": rollback.active_state.generation,
    },
    "candidate_preview_center_ns": _scan_center(candidate_preview),
    "parameter_flow": {
        "stages": (
            "ParameterSnapshot",
            "parameter_lookup",
            "param_axis overlay",
            "QuantumLabCompiler input",
            "proposal",
            "active",
            "rollback",
        ),
        "source_snapshot_id": completed_run.config.parameter_snapshot.id,
        "scan": {
            "table": QUBIT_PARAMETER_TABLE,
            "row": {"qubit": "q0"},
            "column": DRAG_BETA_PARAMETER_COLUMN,
            "center_ns": _scan_center(preview),
        },
        "compiler_input": {
            "program_input": "beta",
            "values_ns": compiler_beta_values,
        },
        "proposal": {
            "id": result.proposal_id,
            "candidate_snapshot_id": candidate_config.parameter_snapshot.id,
            "beta_ns": float(result.fit.beta_hat.to("ns").value),
        },
        "active_snapshot_id": active_config.parameter_snapshot.id,
        "rollback_snapshot_id": restored_config.parameter_snapshot.id,
    },
    "production_baseline": {
        "run_status": baseline_production_run.manifest.status,
        "run_config_entry_id": baseline_source.entry_id,
        "run_registry_generation": baseline_source.registry_generation,
        "production_beta_ns": _quantity_in_unit(
            baseline_gate.points[0].value("drag_beta"),
            "ns",
        ),
        "config_hash_matches": baseline_config_hash_matches,
    },
    "active": {
        "entry_id": activation.entry.id,
        "generation": activation.active_state.generation,
        "run_status": active_production_run.manifest.status,
        "run_config_entry_id": active_source.entry_id,
        "run_registry_generation": active_source.registry_generation,
        "scan_center_ns": _scan_center(active_preview),
        "production_beta_ns": _quantity_in_unit(
            active_gate.points[0].value("drag_beta"),
            "ns",
        ),
        "production_waveform_changed": production_waveform_changed,
        "trusted_reference_unchanged": trusted_reference_unchanged,
        "artifact_changed": active_artifact_changed,
        "config_hash_matches": active_config_hash_matches,
    },
    "rollback": {
        "generation": rollback.active_state.generation,
        "entry_id": rollback.active_state.active_entry_id,
        "run_status": restored_production_run.manifest.status,
        "run_config_entry_id": restored_source.entry_id,
        "run_registry_generation": restored_source.registry_generation,
        "scan_center_ns": _scan_center(restored_preview),
        "production_beta_ns": _quantity_in_unit(
            restored_gate.points[0].value("drag_beta"),
            "ns",
        ),
        "production_waveform_restored": rollback_restored_waveform,
        "artifact_restored": rollback_restored_artifact,
        "config_hash_matches": restored_config_hash_matches,
    },
}
print(drag_beta_summary)
