"""Build durable run evidence from local effect results."""

from __future__ import annotations

from scopecat.execution.effect_result import RunEffectResult
from scopecat.kernel.content_identity import model_wire_content_hash
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.measurements.datasets import (
    MEASUREMENT_DATASET_KIND,
    RAW_MEASUREMENTS_DATASET_ID,
)
from scopecat.records.content import ContentEntry
from scopecat.records.execution import (
    InstrumentStateEvidence,
    summarize_instrument_state_evidence,
)
from scopecat.records.measurement import MeasurementDatasetSchema
from scopecat.runs.refs import record_content_ref

INSTRUMENT_STATE_EVIDENCE_ID = "instrument-state-evidence"
INSTRUMENT_STATE_EVIDENCE_KIND = "instrument_state_evidence"


def instrument_state_evidence_ref() -> str:
    return record_content_ref(
        record_id=INSTRUMENT_STATE_EVIDENCE_ID,
        kind=INSTRUMENT_STATE_EVIDENCE_KIND,
    )


def build_terminal_contents(
    *,
    outcome: RunOutcome,
    measurement_count: int,
    dataset_content_hash: str | None,
    dataset_schema: MeasurementDatasetSchema | None,
    expected_record_count: int | None,
    instrument_state: InstrumentStateEvidence | None,
) -> tuple[ContentEntry, ...]:
    incomplete_run = outcome.result != "succeeded"
    partial = incomplete_run and (
        expected_record_count is None or expected_record_count != measurement_count
    )
    datasets: list[ContentEntry] = []
    if dataset_content_hash is not None:
        if dataset_schema is None:
            raise ValueError("recorded measurements require a sealed dataset contract")
        datasets.append(
            ContentEntry(
                role="dataset",
                id=RAW_MEASUREMENTS_DATASET_ID,
                kind=MEASUREMENT_DATASET_KIND,
                media_type="application/x-ndjson",
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
    elif measurement_count:
        raise ValueError("recorded measurements require a sealed dataset contract")
    records = (
        ()
        if instrument_state is None
        else (
            ContentEntry(
                role="record",
                id=INSTRUMENT_STATE_EVIDENCE_ID,
                kind=INSTRUMENT_STATE_EVIDENCE_KIND,
                media_type="application/json",
                content_hash=model_wire_content_hash(instrument_state),
                metadata={
                    "summary": summarize_instrument_state_evidence(
                        instrument_state
                    ).model_dump(mode="json")
                },
            ),
        )
    )
    return (*records, *datasets)


def build_instrument_state_evidence(
    run_id: str,
    result: RunEffectResult,
) -> InstrumentStateEvidence:
    return InstrumentStateEvidence(
        run_id=run_id,
        observed_state=list(result.observed_state),
        baseline_state=list(result.baseline_state),
        final_state=list(result.final_state),
    )
