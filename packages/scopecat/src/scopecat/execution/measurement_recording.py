"""Initialize, ingest, and seal one daemon-owned measurement dataset."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from scopecat.execution.ports.measurement import (
    MeasurementDatasetLifecycleWriter,
    MeasurementDatasetWriter,
)
from scopecat.kernel.errors import MeasurementRecordingError
from scopecat.kernel.problems import Problem, ProblemPhase
from scopecat.measurements.datasets import RAW_MEASUREMENTS_DATASET_ID
from scopecat.measurements.projection import ProjectedMeasurementDataset
from scopecat.records.measurement_recording import (
    MeasurementDatasetBatch,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
    measurement_fragment_content_hash,
)
from scopecat.sdk.runtime_problems import problem_from_exception, runtime_problem


class _DatasetOperation(Protocol):
    run_id: str

    @property
    def operation_id(self) -> str: ...


def initialize_measurement_dataset(
    header: MeasurementDatasetHeader,
    writer: MeasurementDatasetLifecycleWriter,
) -> MeasurementDatasetReceipt:
    """Publish the canonical dataset contract before writing point records."""

    return _record_operation(
        header,
        recording_contract_fingerprint=header.recording_contract_fingerprint,
        expected_hash=header.content_hash,
        invoke=lambda: writer.initialize(header),
    )


def ingest_measurement_dataset(
    dataset: ProjectedMeasurementDataset,
    writer: MeasurementDatasetWriter,
    *,
    header: MeasurementDatasetHeader,
) -> tuple[MeasurementDatasetReceipt, ...]:
    """Offer records in acquisition order to the daemon-owned durable buffer."""

    records = dataset.records
    if not records:
        return ()
    batch = MeasurementDatasetBatch(
        run_id=dataset.run_id,
        header_content_hash=header.content_hash,
        records=records,
    )
    return writer.ingest(batch)


def seal_measurement_dataset(
    *,
    run_id: str,
    header: MeasurementDatasetHeader,
    record_count: int,
    record_content_hashes: tuple[str, ...],
    writer: MeasurementDatasetLifecycleWriter,
) -> MeasurementDatasetReceipt:
    """Seal the dataset after all admitted point ranges have been appended."""

    seal = MeasurementDatasetSeal(
        run_id=run_id,
        header_content_hash=header.content_hash,
        record_count=record_count,
        fragment_record_count=len(record_content_hashes),
        fragment_content_hash=measurement_fragment_content_hash(
            header_content_hash=header.content_hash,
            record_content_hashes=record_content_hashes,
        ),
    )
    return _record_operation(
        seal,
        recording_contract_fingerprint=header.recording_contract_fingerprint,
        expected_hash=None,
        invoke=lambda: writer.seal(seal),
    )


def _record_operation(
    operation: _DatasetOperation,
    *,
    recording_contract_fingerprint: str,
    expected_hash: str | None,
    invoke: Callable[[], MeasurementDatasetReceipt],
) -> MeasurementDatasetReceipt:
    try:
        receipt = invoke()
    except Exception as error:
        raise _error(
            operation,
            recording_contract_fingerprint=recording_contract_fingerprint,
            problems=(
                problem_from_exception(
                    "measurement_dataset_operation_raised",
                    "measurement dataset writer raised",
                    run_id=operation.run_id,
                    operation_id=operation.operation_id,
                    error=error,
                    phase=ProblemPhase.PERSISTENCE,
                ),
            ),
            receipt=None,
            uncertain=True,
        ) from error
    if receipt.operation_id != operation.operation_id or (
        expected_hash is not None and receipt.dataset_content_hash != expected_hash
    ):
        problem = runtime_problem(
            "measurement_dataset_receipt_invalid",
            "measurement dataset writer returned an invalid receipt",
            run_id=operation.run_id,
            operation_id=operation.operation_id,
            phase=ProblemPhase.PERSISTENCE,
        )
        raise _error(
            operation,
            recording_contract_fingerprint=recording_contract_fingerprint,
            problems=(problem,),
            receipt=receipt,
            uncertain=True,
        )
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
    "MeasurementDatasetHeader",
    "MeasurementDatasetReceipt",
    "MeasurementDatasetSeal",
    "MeasurementDatasetWriter",
    "ingest_measurement_dataset",
    "initialize_measurement_dataset",
    "seal_measurement_dataset",
]
