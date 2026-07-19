"""Build durable run evidence from local effect results."""

from __future__ import annotations

from scopecat.execution.effect_interpreter import RunEffectResult
from scopecat.execution.persistence import build_run_manifest, ref_for_dataset
from scopecat.kernel.content_identity import model_wire_content_hash
from scopecat.measurements.datasets import MEASUREMENT_DATASET_KIND
from scopecat.measurements.results import MeasurementDatasetSchema
from scopecat.records.artifact import RunContentEntry
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
    measurement_count: int,
    dataset_content_hash: str | None,
    dataset_schema: MeasurementDatasetSchema | None,
    expected_record_count: int | None,
    config_content_hash: ConfigContentHash,
    config_source: RunConfigSource | None,
    instrument_state: InstrumentStateEvidence | None,
) -> RunManifest:
    incomplete_run = outcome.result != "succeeded"
    partial = incomplete_run and (
        expected_record_count is None or expected_record_count != measurement_count
    )
    datasets: list[RunContentEntry] = []
    if measurement_count:
        if dataset_content_hash is None or dataset_schema is None:
            raise ValueError("recorded measurements require a sealed dataset contract")
        datasets.append(
            RunContentEntry(
                role="dataset",
                id=RAW_MEASUREMENTS_DATASET_ID,
                kind=MEASUREMENT_DATASET_KIND,
                media_type="application/x-ndjson",
                dataset_role="raw",
                schema=dataset_schema.model_dump(mode="json"),
                content_hash=dataset_content_hash,
                metadata=(
                    {
                        "partial": partial,
                        "run_result": outcome.result,
                        "run_certainty": outcome.certainty,
                        **(
                            {"expected_record_count": expected_record_count}
                            if expected_record_count is not None
                            else {}
                        ),
                    }
                    if partial
                    else {}
                ),
            )
        )
    return build_run_manifest(
        run_id=run_id,
        lifecycle="terminal",
        outcome=outcome,
        config_content_hash=config_content_hash,
        config_source=config_source,
        contents=(
            *_records(outcome=outcome, instrument_state=instrument_state),
            *datasets,
        ),
    )


def build_instrument_state_evidence(
    result: RunEffectResult,
) -> InstrumentStateEvidence:
    return InstrumentStateEvidence(
        run_id=result.run_id,
        initial_state=list(result.initial_state),
        final_state=list(result.final_state),
    )


def _records(
    *,
    outcome: RunOutcome,
    instrument_state: InstrumentStateEvidence | None,
) -> list[RunContentEntry]:
    records = [
        RunContentEntry(
            role="record",
            id=RUN_OUTCOME_ID,
            kind=RUN_OUTCOME_KIND,
            media_type="application/json",
            content_hash=model_wire_content_hash(outcome),
        )
    ]
    if instrument_state is not None:
        records.append(
            RunContentEntry(
                role="record",
                id=INSTRUMENT_STATE_EVIDENCE_ID,
                kind=INSTRUMENT_STATE_EVIDENCE_KIND,
                media_type="application/json",
                content_hash=model_wire_content_hash(instrument_state),
            )
        )
    return records
