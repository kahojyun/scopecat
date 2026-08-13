"""Journaled append and seal operations for one measurement dataset."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol, cast

from pydantic import JsonValue

from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.execution.ports.measurement import (
    DurableMeasurementDatasetWriter,
    MeasurementDatasetLifecycleWriter,
    MeasurementDatasetWriter,
)
from scopecat.kernel.errors import MeasurementRecordingError
from scopecat.kernel.problems import Problem, ProblemPhase
from scopecat.measurements.datasets import RAW_MEASUREMENTS_DATASET_ID
from scopecat.measurements.projection import ProjectedMeasurementDataset
from scopecat.records.execution_journal import ExecutionStage
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetBatch,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.sdk.journal import ExecutionJournal


class _DatasetOperation(Protocol):
    run_id: str

    @property
    def operation_id(self) -> str: ...


def initialize_measurement_dataset(
    header: MeasurementDatasetHeader,
    writer: MeasurementDatasetLifecycleWriter,
    journal: ExecutionJournal,
) -> MeasurementDatasetReceipt:
    """Publish the canonical dataset contract before writing point records."""

    return _record_operation(
        header,
        recording_contract_fingerprint=header.recording_contract_fingerprint,
        expected_hash=header.content_hash,
        stage="initialize_measurement",
        evidence={
            "expected_record_count": header.expected_record_count,
            "record_count_limit": header.record_count_limit,
            "header_content_hash": header.content_hash,
        },
        invoke=lambda: writer.initialize(header),
        journal=journal,
    )


def append_measurement_dataset(
    dataset: ProjectedMeasurementDataset,
    writer: DurableMeasurementDatasetWriter,
    journal: ExecutionJournal,
    *,
    header: MeasurementDatasetHeader,
) -> MeasurementDatasetReceipt | None:
    """Append one contiguous projected point range."""

    records = dataset.records
    if not records:
        return None
    append = MeasurementDatasetAppend(
        run_id=dataset.run_id,
        header_content_hash=header.content_hash,
        start_index=records[0].point_index,
        records=records,
    )
    return _record_operation(
        append,
        recording_contract_fingerprint=header.recording_contract_fingerprint,
        expected_hash=append.content_hash,
        stage="append_measurement",
        evidence={
            "start_index": append.start_index,
            "record_count": len(append.records),
            "append_content_hash": append.content_hash,
        },
        invoke=lambda: writer.append(append),
        journal=journal,
    )


def ingest_measurement_dataset(
    dataset: ProjectedMeasurementDataset,
    writer: MeasurementDatasetWriter,
    *,
    header: MeasurementDatasetHeader,
) -> tuple[MeasurementDatasetReceipt, ...]:
    """Offer one contiguous live range to the daemon-owned durable buffer."""

    records = dataset.records
    if not records:
        return ()
    batch = MeasurementDatasetBatch(
        run_id=dataset.run_id,
        header_content_hash=header.content_hash,
        start_index=records[0].point_index,
        records=records,
    )
    return writer.ingest(batch)


def seal_measurement_dataset(
    *,
    run_id: str,
    header: MeasurementDatasetHeader,
    point_count: int,
    record_content_hashes: tuple[str, ...],
    writer: MeasurementDatasetLifecycleWriter,
    journal: ExecutionJournal,
) -> MeasurementDatasetReceipt:
    """Seal the dataset after all admitted point ranges have been appended."""

    seal = MeasurementDatasetSeal(
        run_id=run_id,
        header_content_hash=header.content_hash,
        point_count=point_count,
        dataset_content_hash=measurement_dataset_content_hash(
            header_content_hash=header.content_hash,
            record_content_hashes=record_content_hashes,
        ),
    )
    return _record_operation(
        seal,
        recording_contract_fingerprint=header.recording_contract_fingerprint,
        expected_hash=seal.dataset_content_hash,
        stage="seal_measurement",
        evidence={
            "point_count": seal.point_count,
            "dataset_content_hash": seal.dataset_content_hash,
        },
        invoke=lambda: writer.seal(seal),
        journal=journal,
    )


def _record_operation(
    operation: _DatasetOperation,
    *,
    recording_contract_fingerprint: str,
    expected_hash: str,
    stage: ExecutionStage,
    evidence: dict[str, JsonValue],
    invoke: Callable[[], MeasurementDatasetReceipt],
    journal: ExecutionJournal,
) -> MeasurementDatasetReceipt:
    boundary = JournaledEffectBoundary(run_id=operation.run_id, journal=journal)
    started = boundary.entry(
        operation_id=operation.operation_id,
        stage=stage,
        effect="persistence",
        state="started",
        evidence=evidence,
    )
    invoked = False

    def invoke_once() -> MeasurementDatasetReceipt:
        nonlocal invoked
        result = invoke()
        invoked = True
        return result

    try:
        receipt = cast(
            "MeasurementDatasetReceipt",
            boundary.invoke(
                started,
                invoke_once,
                unknown_code="measurement_dataset_operation_raised",
                unknown_message="measurement dataset writer raised",
                phase=ProblemPhase.PERSISTENCE,
            ),
        )
    except Exception as error:
        raise _error(
            operation,
            recording_contract_fingerprint=recording_contract_fingerprint,
            problems=(
                boundary.problem_from_exception(
                    "measurement_dataset_intent_persistence_failed",
                    "failed to persist measurement dataset intent",
                    error,
                    operation_id=operation.operation_id,
                    phase=ProblemPhase.PERSISTENCE,
                ),
            ),
            receipt=None,
            uncertain=False,
        ) from error
    if boundary.interruption is not None:
        raise boundary.interruption
    if not invoked:
        raise _error(
            operation,
            recording_contract_fingerprint=recording_contract_fingerprint,
            problems=tuple(boundary.problems),
            receipt=None,
            uncertain=True,
        )
    if (
        receipt.operation_id != operation.operation_id
        or receipt.dataset_content_hash != expected_hash
    ):
        problem = boundary.problem(
            "measurement_dataset_receipt_invalid",
            "measurement dataset writer returned an invalid receipt",
            operation_id=operation.operation_id,
            phase=ProblemPhase.PERSISTENCE,
        )
        boundary.commit_best_effort(
            started.model_copy(
                update={
                    "state": "unknown",
                    "problems": (problem,),
                    "evidence": {
                        **evidence,
                        "receipt": receipt.model_dump(mode="json"),
                    },
                }
            )
        )
        raise _error(
            operation,
            recording_contract_fingerprint=recording_contract_fingerprint,
            problems=(problem,),
            receipt=receipt,
            uncertain=True,
        )
    completed = started.model_copy(
        update={
            "state": "completed",
            "evidence": {
                **evidence,
                "receipt": receipt.model_dump(mode="json"),
            },
        }
    )
    try:
        boundary.commit_after_effect(completed)
    except Exception as error:
        raise _error(
            operation,
            recording_contract_fingerprint=recording_contract_fingerprint,
            problems=(
                boundary.problem_from_exception(
                    "measurement_dataset_receipt_persistence_failed",
                    "failed to persist measurement dataset receipt",
                    error,
                    operation_id=operation.operation_id,
                    phase=ProblemPhase.PERSISTENCE,
                ),
            ),
            receipt=receipt,
            uncertain=True,
        ) from error
    return receipt


def _error(
    operation: _DatasetOperation,
    *,
    recording_contract_fingerprint: str,
    problems: Sequence[Problem],
    receipt: MeasurementDatasetReceipt | None,
    uncertain: bool,
) -> MeasurementRecordingError:
    return MeasurementRecordingError(
        problems,
        run_id=operation.run_id,
        dataset_id=RAW_MEASUREMENTS_DATASET_ID,
        recording_contract_fingerprint=recording_contract_fingerprint,
        operation_id=operation.operation_id,
        receipt=receipt,
        write_may_have_completed=uncertain,
    )


__all__ = [
    "MeasurementDatasetAppend",
    "MeasurementDatasetHeader",
    "MeasurementDatasetReceipt",
    "MeasurementDatasetSeal",
    "MeasurementDatasetWriter",
    "append_measurement_dataset",
    "ingest_measurement_dataset",
    "initialize_measurement_dataset",
    "seal_measurement_dataset",
]
