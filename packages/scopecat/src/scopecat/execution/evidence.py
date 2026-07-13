"""Build durable run evidence from execution engine results."""

from __future__ import annotations

from scopecat.execution.local.engine import ExecutionEngineResult
from scopecat.execution.persistence import (
    build_raw_measurement_dataset,
    build_run_manifest,
    ref_for_dataset,
)
from scopecat.kernel.problems import Problem
from scopecat.measurements.results import MeasurementDatasetSchema, MeasurementRecord
from scopecat.records.artifact import RunDatasetEntry, RunRecordEntry
from scopecat.records.execution import (
    ComputeExecutionSummary,
    ExecutionSummary,
    InstrumentStateEvidence,
    StateExecutionSummary,
)
from scopecat.records.run import RunConfigSource, RunManifest, RunOutcome
from scopecat.runs.refs import record_content_ref

RAW_MEASUREMENTS_DATASET_ID = "raw-measurements"
EXECUTION_SUMMARY_ID = "execution-summary"
EXECUTION_SUMMARY_KIND = "execution_summary"
INSTRUMENT_STATE_EVIDENCE_ID = "instrument-state-evidence"
INSTRUMENT_STATE_EVIDENCE_KIND = "instrument_state_evidence"
RUN_OUTCOME_ID = "run-outcome"
RUN_OUTCOME_KIND = "run_outcome"


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


def run_outcome_ref() -> str:
    return record_content_ref(record_id=RUN_OUTCOME_ID, kind=RUN_OUTCOME_KIND)


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
    outcome: RunOutcome,
    measurements: list[MeasurementRecord],
    expected_schema: MeasurementDatasetSchema | None,
    config_source: RunConfigSource | None,
    include_instrument_state: bool = True,
) -> RunManifest:
    incomplete_run = outcome.result != "succeeded"
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
                        "run_result": outcome.result,
                        "run_certainty": outcome.certainty,
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
        lifecycle="terminal",
        outcome=outcome,
        config_source=config_source,
        records=_records(include_instrument_state=include_instrument_state),
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
    outcome: RunOutcome,
    instrument_ids: list[str],
    point_count: int,
    problems: list[Problem],
) -> ExecutionSummary:
    return ExecutionSummary(
        run_id=result.run_id,
        experiment_id=result.experiment_id,
        outcome=outcome,
        instrument_ids=instrument_ids,
        point_count=point_count,
        completed_point_count=result.completed_point_count,
        measurement_count=len(result.measurements),
        problem_count=len(problems),
        problems=tuple(problems),
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


def _records(*, include_instrument_state: bool) -> list[RunRecordEntry]:
    records = [
        RunRecordEntry(
            id=RUN_OUTCOME_ID,
            kind=RUN_OUTCOME_KIND,
            media_type="application/json",
        ),
        RunRecordEntry(
            id=EXECUTION_SUMMARY_ID,
            kind=EXECUTION_SUMMARY_KIND,
            media_type="application/json",
        ),
    ]
    if include_instrument_state:
        records.append(
            RunRecordEntry(
                id=INSTRUMENT_STATE_EVIDENCE_ID,
                kind=INSTRUMENT_STATE_EVIDENCE_KIND,
                media_type="application/json",
            )
        )
    return records


__all__ = [
    "EXECUTION_SUMMARY_ID",
    "EXECUTION_SUMMARY_KIND",
    "INSTRUMENT_STATE_EVIDENCE_ID",
    "INSTRUMENT_STATE_EVIDENCE_KIND",
    "RAW_MEASUREMENTS_DATASET_ID",
    "RUN_OUTCOME_ID",
    "RUN_OUTCOME_KIND",
    "build_execution_manifest",
    "build_execution_summary",
    "build_instrument_state_evidence",
    "execution_summary_ref",
    "instrument_state_evidence_ref",
    "raw_measurement_schema",
    "raw_measurements_ref",
    "run_outcome_ref",
]
