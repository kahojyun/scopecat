"""Unified gate/pulse UX: run, review, activate, and roll back DRAG beta."""

from __future__ import annotations

# %%
import scopecat as sc
from quantum_lab_demo import notebook_workspace, quantum_lab
from quantum_lab_demo.reference_experiments import (
    DRAG_BETA_TEMPLATE,
    PRODUCTION_DRAG_GATE_TEMPLATE,
    DragBetaDomainExecutionAdapter,
    ProductionDragGateExecutionAdapter,
    analyze_drag_beta_run,
)

# %%
# One Workspace experiment carries both levels of intent:
#
# baseline X90 gate -> N * [PulseTemplate DRAG X90, PulseTemplate DRAG Xm90]
# -> baseline Xm90 gate -> parallel(readout play, explicit acquire).
#
# ``beta`` binds the pulse envelopes while ``amplification`` binds the repeat
# count in that same Program declaration. The accepted ``drag_beta``
# configuration value centers later scans.
workspace = notebook_workspace("13-drag-beta-calibration")
lab = quantum_lab(workspace=workspace)
adapter = DragBetaDomainExecutionAdapter()
experiment = lab.prepare(
    DRAG_BETA_TEMPLATE,
    execution_backend=sc.ExecutionBackend(domain_adapters=(adapter,)),
)

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

# Candidate configs can be previewed before review without changing the active
# registry state. A reviewer may instead choose ``decision='rejected'``; the
# registry will then refuse to activate that proposal.
candidate_preview = lab.prepare(
    DRAG_BETA_TEMPLATE,
    config=candidate,
    execution_backend=sc.ExecutionBackend(
        domain_adapters=(DragBetaDomainExecutionAdapter(),)
    ),
).preview()

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
baseline_production_adapter = ProductionDragGateExecutionAdapter()
baseline_production_run = lab.prepare(
    PRODUCTION_DRAG_GATE_TEMPLATE,
    config="active",
    execution_backend=sc.ExecutionBackend(
        domain_adapters=(baseline_production_adapter,)
    ),
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
active_preview = lab.prepare(
    DRAG_BETA_TEMPLATE,
    config="active",
    execution_backend=sc.ExecutionBackend(
        domain_adapters=(DragBetaDomainExecutionAdapter(),)
    ),
).preview()
active_production_adapter = ProductionDragGateExecutionAdapter()
active_production_run = lab.prepare(
    PRODUCTION_DRAG_GATE_TEMPLATE,
    config="active",
    execution_backend=sc.ExecutionBackend(domain_adapters=(active_production_adapter,)),
).run(
    name="Production X90 with accepted DRAG beta",
    tags=("reference", "production-gate", "active-config", "provenance"),
)

# %%
# Rollback is another atomic, generation-checked registry transition. It keeps
# the proposal, review, activation, production execution, and rollback as
# durable evidence while restoring both scan and compiled production behavior.
rollback = lab.rollback(
    expected_generation=activation.active_state.generation,
    note="restore baseline after production-gate provenance verification",
)
restored_preview = lab.prepare(
    DRAG_BETA_TEMPLATE,
    config="active",
    execution_backend=sc.ExecutionBackend(
        domain_adapters=(DragBetaDomainExecutionAdapter(),)
    ),
).preview()
restored_production_adapter = ProductionDragGateExecutionAdapter()
restored_production_run = lab.prepare(
    PRODUCTION_DRAG_GATE_TEMPLATE,
    config="active",
    execution_backend=sc.ExecutionBackend(
        domain_adapters=(restored_production_adapter,)
    ),
).run(
    name="Production X90 after DRAG beta rollback",
    tags=("reference", "production-gate", "rollback"),
)


def _scan_center(prepared_preview: sc.PreviewExperimentResult) -> float:
    beta_values = sorted(
        {
            float(point.coordinates["beta"].to("ns").value)  # type: ignore[union-attr]
            for point in prepared_preview.points
        }
    )
    return beta_values[len(beta_values) // 2]


def _domain_artifact_fingerprint(run: sc.RunHandle) -> str:
    [execution] = tuple(
        unit for unit in run.plan.execution_units if unit.kind == "domain_program"
    )
    [batch] = execution.batches
    return batch.artifact_fingerprint


[baseline_gate] = baseline_production_adapter.preparations
[active_gate] = active_production_adapter.preparations
[restored_gate] = restored_production_adapter.preparations
baseline_source = baseline_production_run.manifest.config_source
active_source = active_production_run.manifest.config_source
restored_source = restored_production_run.manifest.config_source
if baseline_source is None or active_source is None or restored_source is None:
    msg = "production runs should retain registry provenance"
    raise RuntimeError(msg)
[active_execution] = tuple(
    unit
    for unit in active_production_run.plan.execution_units
    if unit.kind == "domain_program"
)
[active_config_binding] = active_execution.config_input_bindings
active_binding_key = active_config_binding.key.get("qubit")
active_binding_value = active_config_binding.resolved_value

production_waveform_changed = (
    baseline_gate.production_samples != active_gate.production_samples
)
trusted_reference_unchanged = (
    baseline_gate.trusted_reference_samples
    == active_gate.trusted_reference_samples
    == restored_gate.trusted_reference_samples
)
rollback_restored_waveform = (
    restored_gate.production_samples == baseline_gate.production_samples
)
active_artifact_changed = (
    active_gate.artifact_fingerprint != baseline_gate.artifact_fingerprint
)
rollback_restored_artifact = (
    restored_gate.artifact_fingerprint == baseline_gate.artifact_fingerprint
)
active_plan_artifact_matches = (
    _domain_artifact_fingerprint(active_production_run)
    == active_gate.artifact_fingerprint
)
baseline_plan_artifact_matches = (
    _domain_artifact_fingerprint(baseline_production_run)
    == baseline_gate.artifact_fingerprint
)
restored_plan_artifact_matches = (
    _domain_artifact_fingerprint(restored_production_run)
    == restored_gate.artifact_fingerprint
)
baseline_config_hash_matches = (
    baseline_production_run.plan.config_content_hash
    == baseline_source.content_hash
    == baseline_activation.entry.content_hash
)
active_config_hash_matches = (
    active_production_run.plan.config_content_hash
    == active_source.content_hash
    == activation.entry.content_hash
)
restored_config_hash_matches = (
    restored_production_run.plan.config_content_hash
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
active_config_binding_matches = (
    active_config_binding.input_id == "drag_beta"
    and active_config_binding.point_index == 0
    and active_config_binding.table_id == "qubits"
    and active_config_binding.column_id == "drag_beta"
    and isinstance(active_binding_key, sc.EntityRef)
    and active_binding_key.id == "q0"
    and isinstance(active_binding_value, sc.Quantity)
    and active_binding_value.to("ns") == active_gate.resolved_drag_beta
)
production_evidence_checks = {
    "production_waveform_changed": production_waveform_changed,
    "trusted_reference_unchanged": trusted_reference_unchanged,
    "rollback_restored_waveform": rollback_restored_waveform,
    "active_artifact_changed": active_artifact_changed,
    "rollback_restored_artifact": rollback_restored_artifact,
    "active_plan_artifact_matches": active_plan_artifact_matches,
    "baseline_plan_artifact_matches": baseline_plan_artifact_matches,
    "restored_plan_artifact_matches": restored_plan_artifact_matches,
    "baseline_config_hash_matches": baseline_config_hash_matches,
    "active_config_hash_matches": active_config_hash_matches,
    "restored_config_hash_matches": restored_config_hash_matches,
    "baseline_source_matches": baseline_source_matches,
    "active_source_matches": active_source_matches,
    "restored_source_matches": restored_source_matches,
    "active_config_binding_matches": active_config_binding_matches,
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
    "physical_executions": adapter.physical_execution_count,
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
    "production_baseline": {
        "run_status": baseline_production_run.manifest.status,
        "run_config_entry_id": baseline_source.entry_id,
        "run_registry_generation": baseline_source.registry_generation,
        "production_beta_ns": float(baseline_gate.resolved_drag_beta.to("ns").value),
        "plan_artifact_matches": baseline_plan_artifact_matches,
        "config_hash_matches": baseline_config_hash_matches,
    },
    "active": {
        "entry_id": activation.entry.id,
        "generation": activation.active_state.generation,
        "run_status": active_production_run.manifest.status,
        "run_config_entry_id": active_source.entry_id,
        "run_registry_generation": active_source.registry_generation,
        "scan_center_ns": _scan_center(active_preview),
        "production_beta_ns": float(active_gate.resolved_drag_beta.to("ns").value),
        "production_waveform_changed": production_waveform_changed,
        "trusted_reference_unchanged": trusted_reference_unchanged,
        "artifact_changed": active_artifact_changed,
        "plan_artifact_matches": active_plan_artifact_matches,
        "config_hash_matches": active_config_hash_matches,
        "config_binding": {
            "input_id": active_config_binding.input_id,
            "selector": "qubits[q0].drag_beta",
            "value_ns": float(active_gate.resolved_drag_beta.to("ns").value),
        },
    },
    "rollback": {
        "generation": rollback.active_state.generation,
        "entry_id": rollback.active_state.active_entry_id,
        "run_status": restored_production_run.manifest.status,
        "run_config_entry_id": restored_source.entry_id,
        "run_registry_generation": restored_source.registry_generation,
        "scan_center_ns": _scan_center(restored_preview),
        "production_beta_ns": float(restored_gate.resolved_drag_beta.to("ns").value),
        "production_waveform_restored": rollback_restored_waveform,
        "artifact_restored": rollback_restored_artifact,
        "plan_artifact_matches": restored_plan_artifact_matches,
        "config_hash_matches": restored_config_hash_matches,
    },
}
print(drag_beta_summary)
