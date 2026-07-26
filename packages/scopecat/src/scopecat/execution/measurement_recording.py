"""Journaled append and seal operations for one measurement dataset."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from pydantic import JsonValue

from scopecat.execution.effects.journaled import JournaledEffectBoundary
from scopecat.execution.ports.measurement import MeasurementDatasetWriter
from scopecat.kernel.errors import MeasurementRecordingError
from scopecat.kernel.problems import Problem, ProblemPhase
from scopecat.measurements.datasets import RAW_MEASUREMENTS_DATASET_ID
from scopecat.measurements.projection import ProjectedMeasurementDataset
from scopecat.records.execution_journal import ExecutionStage
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.sdk.journal import ExecutionJournal


class _DatasetOperation(Protocol):
    run_id: str
    recording_contract_fingerprint: str

    @property
    def operation_id(self) -> str: ...


def append_measurement_dataset(
    dataset: ProjectedMeasurementDataset,
    writer: MeasurementDatasetWriter,
    journal: ExecutionJournal,
) -> MeasurementDatasetReceipt | None:
    """Append one contiguous projected point range."""

    records = dataset.records
    if not records:
        return None
    if dataset.schema is None:
        raise ValueError("projected measurement records require a dataset schema")
    append = MeasurementDatasetAppend(
        run_id=dataset.run_id,
        recording_contract_fingerprint=dataset.recording_contract_fingerprint,
        start_index=records[0].point_index,
        records=records,
    )
    return _record_operation(
        append,
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


def seal_measurement_dataset(
    *,
    run_id: str,
    recording_contract_fingerprint: str,
    point_count: int,
    append_content_hashes: tuple[str, ...],
    writer: MeasurementDatasetWriter,
    journal: ExecutionJournal,
) -> MeasurementDatasetReceipt:
    """Seal the dataset after all admitted point ranges have been appended."""

    seal = MeasurementDatasetSeal(
        run_id=run_id,
        recording_contract_fingerprint=recording_contract_fingerprint,
        point_count=point_count,
        dataset_content_hash=measurement_dataset_content_hash(
            recording_contract_fingerprint=recording_contract_fingerprint,
            append_content_hashes=append_content_hashes,
        ),
    )
    return _record_operation(
        seal,
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
    expected_hash: str,
    stage: ExecutionStage,
    evidence: dict[str, JsonValue],
    invoke: Callable[[], object],
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

    def invoke_once() -> object:
        nonlocal invoked
        result = invoke()
        invoked = True
        return result

    try:
        raw_receipt = boundary.invoke(
            started,
            invoke_once,
            unknown_code="measurement_dataset_operation_raised",
            unknown_message="measurement dataset writer raised",
            phase=ProblemPhase.PERSISTENCE,
        )
    except Exception as error:
        raise _error(
            operation,
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
            problems=tuple(boundary.problems),
            receipt=None,
            uncertain=True,
        )
    receipt: MeasurementDatasetReceipt | None = None
    try:
        if not isinstance(raw_receipt, MeasurementDatasetReceipt):
            raise TypeError("measurement writer must return MeasurementDatasetReceipt")
        receipt = MeasurementDatasetReceipt.model_validate(
            raw_receipt.model_dump(mode="json")
        )
        if (
            receipt.operation_id != operation.operation_id
            or receipt.dataset_content_hash != expected_hash
        ):
            raise ValueError("measurement dataset receipt does not correlate")
    except Exception as error:
        problem = boundary.problem(
            "measurement_dataset_receipt_invalid",
            "measurement dataset writer returned an invalid receipt",
            operation_id=operation.operation_id,
            phase=ProblemPhase.PERSISTENCE,
            details={
                "error_type": f"{type(error).__module__}.{type(error).__qualname__}"
            },
        )
        unknown_evidence = dict(evidence)
        if receipt is not None:
            unknown_evidence["receipt"] = receipt.model_dump(mode="json")
        boundary.commit_best_effort(
            started.model_copy(
                update={
                    "state": "unknown",
                    "problems": (problem,),
                    "evidence": unknown_evidence,
                }
            )
        )
        raise _error(
            operation,
            problems=(problem,),
            receipt=receipt,
            uncertain=True,
        ) from error
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
    problems: Sequence[Problem],
    receipt: MeasurementDatasetReceipt | None,
    uncertain: bool,
) -> MeasurementRecordingError:
    return MeasurementRecordingError(
        problems,
        run_id=operation.run_id,
        dataset_id=RAW_MEASUREMENTS_DATASET_ID,
        recording_contract_fingerprint=operation.recording_contract_fingerprint,
        operation_id=operation.operation_id,
        receipt=receipt,
        write_may_have_completed=uncertain,
    )


__all__ = [
    "MeasurementDatasetAppend",
    "MeasurementDatasetReceipt",
    "MeasurementDatasetSeal",
    "MeasurementDatasetWriter",
    "append_measurement_dataset",
    "seal_measurement_dataset",
]
