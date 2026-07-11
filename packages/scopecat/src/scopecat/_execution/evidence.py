"""Build durable run evidence from execution engine results."""

from __future__ import annotations

from scopecat._execution.engine import ExecutionEngineResult
from scopecat._execution.persistence import (
    build_raw_measurement_dataset,
    build_run_manifest,
    ref_for_dataset,
)
from scopecat._storage.refs import record_content_ref
from scopecat.diagnostics import Diagnostic
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
    incomplete_run = status != "completed"
    expected_record_count = (
        _expected_record_count(expected_schema) if expected_schema is not None else None
    )
    partial = incomplete_run and (
        expected_record_count is None or expected_record_count != len(measurements)
    )
    datasets: list[RunDatasetEntry] = []
    if measurements:
        datasets.append(
            build_raw_measurement_dataset(
                dataset_id=RAW_MEASUREMENTS_DATASET_ID,
                records=measurements,
                expected_schema=None if incomplete_run else expected_schema,
                metadata=(
                    {
                        "partial": partial,
                        "run_status": status,
                        **(
                            {"expected_record_count": expected_record_count}
                            if expected_schema is not None
                            else {}
                        ),
                    }
                    if partial
                    else None
                ),
            )
        )
    return build_run_manifest(
        run_id=run_id,
        status=status,
        config_source=config_source,
        records=_records(),
        datasets=datasets,
    )


def _expected_record_count(schema: MeasurementDatasetSchema) -> int | None:
    for dimension in schema.dimensions:
        if dimension.kind == "point" or dimension.id == "point":
            return dimension.size
    return None


def build_execution_summary(
    *,
    result: ExecutionEngineResult,
    status: RunStatus,
    instrument_ids: list[str],
    point_count: int,
    diagnostics: list[Diagnostic],
) -> ExecutionSummary:
    return ExecutionSummary(
        run_id=result.run_id,
        experiment_id=result.experiment_id,
        status=status,
        instrument_ids=instrument_ids,
        point_count=point_count,
        completed_point_count=result.completed_point_count,
        measurement_count=len(result.measurements),
        diagnostic_count=len(diagnostics),
        diagnostics=diagnostics,
        state=StateExecutionSummary(
            changed_field_count=result.changed_field_count,
            skipped_field_count=result.skipped_field_count,
            state_command_count=result.state_command_count,
            payload_count=result.state_payload_count,
        ),
        compute=ComputeExecutionSummary(
            evaluated_node_count=result.compute_evaluated_node_count,
            reused_node_count=result.compute_reused_node_count,
            payload_count=result.compute_payload_count,
        ),
    )


def build_instrument_state_evidence(
    result: ExecutionEngineResult,
) -> InstrumentStateEvidence:
    return InstrumentStateEvidence(
        run_id=result.run_id,
        initial_state=list(result.initial_state),
        final_state=list(result.final_state),
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
