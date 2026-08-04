from __future__ import annotations

from typing import override

import pytest

from scopecat.execution.measurement_recording import (
    append_measurement_dataset,
    initialize_measurement_dataset,
    seal_measurement_dataset,
)
from scopecat.kernel.errors import MeasurementRecordingError
from scopecat.measurements.projection import (
    ProjectedMeasurementDataset,
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.records.measurement_recording import (
    CANONICAL_MEASUREMENT_DATASET_REF,
    MeasurementDatasetAppend,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
)
from scopecat.sdk.journal import ExecutionJournal
from tests.testkit.measurement_assembly import assembled_measurement_values_for_all_uses
from tests.testkit.runtime import (
    FakeExecutionJournal,
    FakeMeasurementDatasetRepository,
)


def _projected(*, run_id: str = "recording-run") -> ProjectedMeasurementDataset:
    scenario, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.catalog, scenario.records)
    return project_measurement_records(
        projection, assembled, run_id=run_id, points=scenario.points
    )


def _seal(
    projected: ProjectedMeasurementDataset,
    writer: FakeMeasurementDatasetRepository,
    journal: ExecutionJournal,
    append_receipt: MeasurementDatasetReceipt,
    header: MeasurementDatasetHeader,
) -> MeasurementDatasetReceipt:
    return seal_measurement_dataset(
        run_id=projected.run_id,
        header=header,
        point_count=len(projected.records),
        append_content_hashes=(append_receipt.dataset_content_hash,),
        writer=writer,
        journal=journal,
    )


def _header(projected: ProjectedMeasurementDataset) -> MeasurementDatasetHeader:
    assert projected.schema is not None
    return MeasurementDatasetHeader(
        run_id=projected.run_id,
        recording_contract_fingerprint=projected.recording_contract_fingerprint,
        dataset_schema=projected.schema,
        expected_record_count=len(projected.records),
    )


def test_recording_appends_and_seals_one_canonical_dataset() -> None:
    projected = _projected()
    assert projected.schema is not None
    writer = FakeMeasurementDatasetRepository()
    journal = FakeExecutionJournal()
    header = _header(projected)

    initialize_measurement_dataset(header, writer, journal)
    append_receipt = append_measurement_dataset(
        projected,
        writer,
        journal,
        header=header,
    )
    assert append_receipt is not None
    seal_receipt = _seal(projected, writer, journal, append_receipt, header)

    [append] = writer.appends
    assert append.records == projected.records
    assert append_receipt.dataset_ref == CANONICAL_MEASUREMENT_DATASET_REF
    assert seal_receipt.dataset_ref == CANONICAL_MEASUREMENT_DATASET_REF
    assert [(entry.stage, entry.state) for entry in journal.entries] == [
        ("initialize_measurement", "started"),
        ("initialize_measurement", "completed"),
        ("append_measurement", "started"),
        ("append_measurement", "completed"),
        ("seal_measurement", "started"),
        ("seal_measurement", "completed"),
    ]


def test_append_identity_is_stable_and_content_detects_conflict() -> None:
    projected = _projected()
    header = _header(projected)
    append = MeasurementDatasetAppend(
        run_id=projected.run_id,
        header_content_hash=header.content_hash,
        start_index=0,
        records=projected.records,
    )
    changed = append.model_copy(
        update={
            "records": (
                *append.records[:-1],
                append.records[-1].model_copy(update={"metadata": {"changed": True}}),
            )
        }
    )
    changed_header = header.model_copy(
        update={
            "dataset_schema": header.dataset_schema.model_copy(
                update={"metadata": {"revision": 2}}
            )
        }
    )
    assert changed.operation_id == append.operation_id
    assert changed.content_hash != append.content_hash
    assert changed_header.operation_id == header.operation_id
    assert changed_header.content_hash != header.content_hash


class _InvalidReceiptWriter(FakeMeasurementDatasetRepository):
    @override
    def append(self, append: MeasurementDatasetAppend) -> MeasurementDatasetReceipt:
        return MeasurementDatasetReceipt(
            operation_id=append.operation_id,
            dataset_content_hash="sha256:wrong",
        )


def test_invalid_append_receipt_terminalizes_uncertain_operation() -> None:
    projected = _projected()
    header = _header(projected)
    writer = _InvalidReceiptWriter()
    initialize_measurement_dataset(header, writer, FakeExecutionJournal())
    with pytest.raises(MeasurementRecordingError) as caught:
        append_measurement_dataset(
            projected,
            writer,
            FakeExecutionJournal(),
            header=header,
        )
    assert caught.value.write_may_have_completed
    assert caught.value.receipt is not None


def test_append_and_seal_replay_are_idempotent() -> None:
    projected = _projected()
    assert projected.schema is not None
    writer = FakeMeasurementDatasetRepository()
    header = _header(projected)
    initialize_measurement_dataset(header, writer, FakeExecutionJournal())
    receipt = append_measurement_dataset(
        projected,
        writer,
        FakeExecutionJournal(),
        header=header,
    )
    assert receipt is not None
    repeated = append_measurement_dataset(
        projected,
        writer,
        FakeExecutionJournal(),
        header=header,
    )
    assert repeated == receipt
    _seal(projected, writer, FakeExecutionJournal(), receipt, header)
    _seal(projected, writer, FakeExecutionJournal(), receipt, header)
    assert len(writer.appends) == 1
    assert writer.measurements() == projected.records
