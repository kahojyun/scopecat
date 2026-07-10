"""Build persistent run evidence from transient runtime execution state."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scopecat._execution import (
    validate_measurement_index_shape,
    validate_raw_measurement_dataset,
)
from scopecat._measurement_storage import write_measurement_records_path
from scopecat._runtime.cursor import ExecutionCursor
from scopecat._runtime.evidence import (
    RAW_MEASUREMENTS_DATASET_ID,
    build_execution_manifest,
    build_execution_summary,
    build_instrument_state_evidence,
    execution_summary_ref,
    instrument_state_evidence_ref,
    raw_measurements_ref,
)
from scopecat._runtime.graph import RuntimeGraph
from scopecat._storage.local import LocalRunStore
from scopecat.diagnostics import Diagnostic
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.execution import ExecutionSummary, InstrumentStateEvidence
from scopecat.models.run import RunConfigSource, RunManifest, RunStatus
from scopecat.models.run_plan import RunPlanRecord
from scopecat.models.run_request import RunRequest
from scopecat.planning.validation import has_blocking_diagnostics
from scopecat.results import MeasurementDatasetSchema, MeasurementRecord


@dataclass(frozen=True)
class RuntimeExecutionOutcome:
    """Persistent-facing result derived from a transient execution cursor."""

    status: RunStatus
    diagnostics: list[Diagnostic]
    measurements: list[MeasurementRecord]
    manifest: RunManifest
    summary: ExecutionSummary
    instrument_state: InstrumentStateEvidence

    @property
    def success(self) -> bool:
        return self.status == "completed"


def build_runtime_execution_outcome(
    *,
    run_id: str,
    experiment_id: str,
    graph: RuntimeGraph,
    instrument_ids: list[str],
    setup_diagnostics: list[Diagnostic],
    cursor: ExecutionCursor,
    raw_measurement_schema: MeasurementDatasetSchema | None,
    config_source: RunConfigSource | None,
) -> RuntimeExecutionOutcome:
    measurements = list(cursor.measurements)
    diagnostics = _execution_diagnostics(
        setup_diagnostics=setup_diagnostics,
        cursor=cursor,
        measurements=measurements,
        graph=graph,
        raw_measurement_schema=raw_measurement_schema,
    )
    status: RunStatus = (
        "failed" if has_blocking_diagnostics(diagnostics) else "completed"
    )
    manifest = build_execution_manifest(
        run_id=run_id,
        status=status,
        measurements=measurements,
        expected_schema=raw_measurement_schema,
        config_source=config_source,
    )
    summary = build_execution_summary(
        run_id=run_id,
        experiment_id=experiment_id,
        status=status,
        instrument_ids=instrument_ids,
        point_count=graph.point_count,
        measurement_count=len(measurements),
        diagnostics=diagnostics,
        completed_point_count=cursor.completed_point_count,
        changed_field_count=cursor.changed_field_count,
        skipped_field_count=cursor.skipped_field_count,
        state_command_count=cursor.state_command_count,
        state_payload_count=cursor.state_payload_count,
        compute_evaluated_node_count=cursor.compute_evaluated_node_count,
        compute_reused_node_count=cursor.compute_reused_node_count,
        compute_payload_count=cursor.compute_payload_count,
    )
    instrument_state = build_instrument_state_evidence(
        run_id=run_id,
        initial_state=cursor.initial_state,
        final_state=cursor.final_state,
    )
    return RuntimeExecutionOutcome(
        status=status,
        diagnostics=diagnostics,
        measurements=measurements,
        manifest=manifest,
        summary=summary,
        instrument_state=instrument_state,
    )


def persist_runtime_execution_outcome(
    *,
    workspace: str | Path,
    request: RunRequest | None,
    plan: RunPlanRecord,
    config: ConfigProfileSnapshot,
    outcome: RuntimeExecutionOutcome,
) -> None:
    storage = LocalRunStore(Path(workspace))
    storage.write_structured_run_inputs(
        manifest=outcome.manifest,
        request=request,
        plan=plan,
        config=config,
    )
    storage.write_model(
        outcome.manifest.run_id,
        execution_summary_ref(),
        outcome.summary,
    )
    storage.write_model(
        outcome.manifest.run_id,
        instrument_state_evidence_ref(),
        outcome.instrument_state,
    )
    write_measurement_records_path(
        path=storage.ref_path(outcome.manifest.run_id, raw_measurements_ref()),
        records=outcome.measurements,
    )


def _execution_diagnostics(
    *,
    setup_diagnostics: list[Diagnostic],
    cursor: ExecutionCursor,
    measurements: list[MeasurementRecord],
    graph: RuntimeGraph,
    raw_measurement_schema: MeasurementDatasetSchema | None,
) -> list[Diagnostic]:
    measurement_diagnostics = validate_measurement_index_shape(
        measurements=measurements,
        expected_indices=graph.expected_measurement_indices,
        duplicate_code="duplicate_measurement_index",
        duplicate_message="run recorded duplicate measurement",
        unknown_code="unknown_measurement_index",
        unknown_message="run recorded unknown measurement",
        missing_observables_code="missing_observables",
        missing_observables_message="measurement has no observables",
    )
    dataset_contract_diagnostics: list[Diagnostic] = []
    if not has_blocking_diagnostics([*setup_diagnostics, *cursor.diagnostics]):
        dataset_contract_diagnostics = validate_raw_measurement_dataset(
            records=measurements,
            expected_schema=raw_measurement_schema,
            dataset_id=RAW_MEASUREMENTS_DATASET_ID,
        )
    return [
        *setup_diagnostics,
        *cursor.diagnostics,
        *dataset_contract_diagnostics,
        *measurement_diagnostics,
    ]


__all__ = [
    "RuntimeExecutionOutcome",
    "build_runtime_execution_outcome",
    "persist_runtime_execution_outcome",
]
