"""Journaled append and seal operations for one measurement dataset."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Literal, Protocol

from pydantic import JsonValue

from scopecat.execution.ports.measurement import MeasurementDatasetWriter
from scopecat.kernel.errors import MeasurementRecordingError
from scopecat.kernel.problems import Problem, ProblemPhase
from scopecat.measurements.datasets import RAW_MEASUREMENTS_DATASET_ID
from scopecat.measurements.projection import ProjectedMeasurementDataset
from scopecat.records.execution_journal import ExecutionStage, ExecutionTransition
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
)
from scopecat.sdk.journal import ExecutionJournal, commit_transition
from scopecat.sdk.runtime_problems import problem_from_exception, runtime_problem


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
    started = _transition(
        operation,
        stage=stage,
        state="started",
        evidence=evidence,
    )
    try:
        commit_transition(journal, started)
    except Exception as error:
        raise _error(
            operation,
            problems=(
                _problem(
                    operation,
                    "measurement_dataset_intent_persistence_failed",
                    "failed to persist measurement dataset intent",
                    error,
                ),
            ),
            receipt=None,
            uncertain=False,
        ) from error
    try:
        raw_receipt = invoke()
    except Exception as error:
        problem = _problem(
            operation,
            "measurement_dataset_operation_raised",
            "measurement dataset writer raised",
            error,
        )
        _append_unknown(journal, started, operation, stage, (problem,), None)
        raise _error(
            operation,
            problems=(problem,),
            receipt=None,
            uncertain=True,
        ) from error
    except BaseException:
        problem = runtime_problem(
            "measurement_dataset_operation_interrupted",
            "measurement dataset operation was interrupted",
            run_id=operation.run_id,
            operation_id=operation.operation_id,
            phase=ProblemPhase.PERSISTENCE,
        )
        _append_unknown(journal, started, operation, stage, (problem,), None)
        raise
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
        problem = runtime_problem(
            "measurement_dataset_receipt_invalid",
            "measurement dataset writer returned an invalid receipt",
            run_id=operation.run_id,
            operation_id=operation.operation_id,
            phase=ProblemPhase.PERSISTENCE,
            details={
                "error_type": f"{type(error).__module__}.{type(error).__qualname__}"
            },
        )
        _append_unknown(journal, started, operation, stage, (problem,), receipt)
        raise _error(
            operation,
            problems=(problem,),
            receipt=receipt,
            uncertain=True,
        ) from error
    completed = _transition(
        operation,
        stage=stage,
        state="completed",
        evidence={
            **evidence,
            "receipt": receipt.model_dump(mode="json"),
        },
    )
    try:
        commit_transition(journal, completed)
    except Exception as error:
        raise _error(
            operation,
            problems=(
                _problem(
                    operation,
                    "measurement_dataset_receipt_persistence_failed",
                    "failed to persist measurement dataset receipt",
                    error,
                ),
            ),
            receipt=receipt,
            uncertain=True,
        ) from error
    return receipt


def _transition(
    operation: _DatasetOperation,
    *,
    stage: ExecutionStage,
    state: Literal["started", "completed", "unknown"],
    evidence: dict[str, JsonValue],
    problems: Sequence[Problem] = (),
) -> ExecutionTransition:
    return ExecutionTransition(
        run_id=operation.run_id,
        operation_id=operation.operation_id,
        stage=stage,
        effect="persistence",
        state=state,
        point_index=None,
        problems=tuple(problems),
        evidence=evidence,
    )


def _append_unknown(
    journal: ExecutionJournal,
    started: ExecutionTransition,
    operation: _DatasetOperation,
    stage: ExecutionStage,
    problems: tuple[Problem, ...],
    receipt: MeasurementDatasetReceipt | None,
) -> None:
    """Best-effort journal-only closure for an uncertain dataset effect."""

    evidence = dict(started.evidence)
    if receipt is not None:
        evidence["receipt"] = receipt.model_dump(mode="json")
    try:
        commit_transition(
            journal,
            _transition(
                operation,
                stage=stage,
                state="unknown",
                evidence=evidence,
                problems=problems,
            ),
        )
    except Exception:
        return


def _problem(
    operation: _DatasetOperation,
    code: str,
    message: str,
    error: Exception,
) -> Problem:
    return problem_from_exception(
        code,
        message,
        run_id=operation.run_id,
        operation_id=operation.operation_id,
        error=error,
        phase=ProblemPhase.PERSISTENCE,
    )


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
