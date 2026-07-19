"""Build durable run evidence from local effect results."""

from __future__ import annotations

from scopecat.execution.effect_interpreter import RunEffectResult
from scopecat.execution.persistence import (
    build_raw_measurement_dataset,
    build_run_manifest,
    ref_for_dataset,
)
from scopecat.measurements.results import MeasurementDatasetSchema, MeasurementRecord
from scopecat.records.artifact import RunDatasetEntry, RunRecordEntry
from scopecat.records.config import ConfigContentHash
from scopecat.records.execution import InstrumentStateEvidence
from scopecat.records.run import RunConfigSource, RunManifest, RunOutcome
from scopecat.runs.refs import record_content_ref

RAW_MEASUREMENTS_DATASET_ID = "raw-measurements"
INSTRUMENT_STATE_EVIDENCE_ID = "instrument-state-evidence"
INSTRUMENT_STATE_EVIDENCE_KIND = "instrument_state_evidence"
RUN_OUTCOME_ID = "run-outcome"
RUN_OUTCOME_KIND = "run_outcome"


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
    config_content_hash: ConfigContentHash,
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
        config_content_hash=config_content_hash,
        config_source=config_source,
        records=_records(include_instrument_state=include_instrument_state),
        datasets=datasets,
    )


def _expected_record_count(schema: MeasurementDatasetSchema) -> int | None:
    for dimension in schema.dimensions:
        if dimension.kind == "point" or dimension.id == "point":
            return dimension.size
    return None


def build_instrument_state_evidence(
    result: RunEffectResult,
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
        )
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
