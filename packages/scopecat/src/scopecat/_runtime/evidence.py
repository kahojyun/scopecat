"""Runtime evidence manifest and execution summary helpers."""

from __future__ import annotations

from scopecat._execution import (
    build_raw_measurement_dataset,
    build_run_manifest,
    ref_for_dataset,
)
from scopecat._storage.refs import record_content_ref
from scopecat.diagnostics import Diagnostic
from scopecat.instruments.sdk import InstrumentStateSnapshot
from scopecat.models.artifact import RunDatasetEntry, RunRecordEntry
from scopecat.models.execution import (
    ComputeExecutionSummary,
    ExecutionSummary,
    InstrumentStateEvidence,
    StateExecutionSummary,
)
from scopecat.models.run import RunConfigSource, RunManifest, RunStatus
from scopecat.results import MeasurementDatasetSchema, MeasurementRecord

RAW_MEASUREMENTS_DATASET_ID = "raw-measurements"
EXECUTION_SUMMARY_ID = "execution-summary"
EXECUTION_SUMMARY_KIND = "execution_summary"
INSTRUMENT_STATE_EVIDENCE_ID = "instrument-state-evidence"
INSTRUMENT_STATE_EVIDENCE_KIND = "instrument_state_evidence"


def execution_summary_ref() -> str:
    return record_content_ref(
        record_id=EXECUTION_SUMMARY_ID,
        kind=EXECUTION_SUMMARY_KIND,
    )


def instrument_state_evidence_ref() -> str:
    return record_content_ref(
        record_id=INSTRUMENT_STATE_EVIDENCE_ID,
        kind=INSTRUMENT_STATE_EVIDENCE_KIND,
    )


def raw_measurements_ref() -> str:
    return ref_for_dataset(RAW_MEASUREMENTS_DATASET_ID)


def raw_measurement_schema(
    expected_schema: MeasurementDatasetSchema | None,
) -> MeasurementDatasetSchema | None:
    if expected_schema is None:
        return None
    return expected_schema.model_copy(
        update={"dataset_id": RAW_MEASUREMENTS_DATASET_ID}
    )


def build_execution_manifest(
    *,
    run_id: str,
    status: RunStatus,
    measurements: list[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None,
    config_source: RunConfigSource | None,
) -> RunManifest:
    return build_run_manifest(
        run_id=run_id,
        status=status,
        config_source=config_source,
        records=_records(),
        datasets=_datasets(
            measurements=measurements,
            expected_schema=expected_schema,
        ),
    )


def build_execution_summary(
    *,
    run_id: str,
    experiment_id: str,
    status: RunStatus,
    instrument_ids: list[str],
    point_count: int,
    measurement_count: int,
    diagnostics: list[Diagnostic],
    completed_point_count: int,
    changed_field_count: int,
    skipped_field_count: int,
    state_command_count: int,
    state_payload_count: int,
    compute_evaluated_node_count: int,
    compute_reused_node_count: int,
    compute_payload_count: int,
) -> ExecutionSummary:
    return ExecutionSummary(
        run_id=run_id,
        experiment_id=experiment_id,
        status=status,
        instrument_ids=instrument_ids,
        point_count=point_count,
        completed_point_count=completed_point_count,
        measurement_count=measurement_count,
        diagnostic_count=len(diagnostics),
        diagnostics=diagnostics,
        state=StateExecutionSummary(
            changed_field_count=changed_field_count,
            skipped_field_count=skipped_field_count,
            state_command_count=state_command_count,
            payload_count=state_payload_count,
        ),
        compute=ComputeExecutionSummary(
            evaluated_node_count=compute_evaluated_node_count,
            reused_node_count=compute_reused_node_count,
            payload_count=compute_payload_count,
        ),
    )


def build_instrument_state_evidence(
    *,
    run_id: str,
    initial_state: list[InstrumentStateSnapshot],
    final_state: list[InstrumentStateSnapshot],
) -> InstrumentStateEvidence:
    return InstrumentStateEvidence(
        run_id=run_id,
        initial_state=initial_state,
        final_state=final_state,
    )


def _records() -> list[RunRecordEntry]:
    return [
        RunRecordEntry(
            id=EXECUTION_SUMMARY_ID,
            kind=EXECUTION_SUMMARY_KIND,
            media_type="application/json",
        ),
        RunRecordEntry(
            id=INSTRUMENT_STATE_EVIDENCE_ID,
            kind=INSTRUMENT_STATE_EVIDENCE_KIND,
            media_type="application/json",
        ),
    ]


def _datasets(
    *,
    measurements: list[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None,
) -> list[RunDatasetEntry]:
    return [
        build_raw_measurement_dataset(
            dataset_id=RAW_MEASUREMENTS_DATASET_ID,
            records=measurements,
            expected_schema=expected_schema,
        ),
    ]


__all__ = [
    "EXECUTION_SUMMARY_ID",
    "EXECUTION_SUMMARY_KIND",
    "INSTRUMENT_STATE_EVIDENCE_ID",
    "INSTRUMENT_STATE_EVIDENCE_KIND",
    "RAW_MEASUREMENTS_DATASET_ID",
    "build_execution_manifest",
    "build_execution_summary",
    "build_instrument_state_evidence",
    "execution_summary_ref",
    "instrument_state_evidence_ref",
    "raw_measurement_schema",
    "raw_measurements_ref",
]
