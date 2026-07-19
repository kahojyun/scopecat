from __future__ import annotations

from typing import override

import pytest

from scopecat.adapters.memory import (
    MemoryExecutionJournal,
    MemoryMeasurementDatasetRepository,
)
from scopecat.kernel.errors import MeasurementRecordingError
from scopecat.measurements.projection import (
    ProjectedMeasurementDataset,
    project_measurement_records,
    select_measurement_projection,
)
from scopecat.measurements.recording import (
    append_measurement_dataset,
    seal_measurement_dataset,
)
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
)
from tests.testkit.measurement_assembly import assembled_measurement_values_for_all_uses


def _projected(*, run_id: str = "recording-run") -> ProjectedMeasurementDataset:
    scenario, _, assembled = assembled_measurement_values_for_all_uses()
    projection = select_measurement_projection(scenario.catalog, scenario.records)
    return project_measurement_records(
        projection, assembled, run_id=run_id, points=scenario.points
    )


def _seal(
    projected: ProjectedMeasurementDataset,
    writer: MemoryMeasurementDatasetRepository,
    journal: MemoryExecutionJournal,
    append_receipt: MeasurementDatasetReceipt,
) -> MeasurementDatasetReceipt:
    assert projected.schema is not None
    return seal_measurement_dataset(
        run_id=projected.run_id,
        dataset_id=projected.schema.dataset_id,
        recording_contract_fingerprint=projected.recording_contract_fingerprint,
        point_count=len(projected.records),
        append_content_hashes=(append_receipt.dataset_content_hash,),
        writer=writer,
        journal=journal,
    )


def test_recording_appends_and_seals_one_canonical_dataset() -> None:
    projected = _projected()
    writer = MemoryMeasurementDatasetRepository()
    journal = MemoryExecutionJournal()

    append_receipt = append_measurement_dataset(projected, writer, journal)
    assert append_receipt is not None
    _seal(projected, writer, journal, append_receipt)

    [append] = writer.appends
    assert append.records == projected.records
    assert [(entry.stage, entry.state) for entry in journal.entries] == [
        ("append_measurement", "started"),
        ("append_measurement", "completed"),
        ("seal_measurement", "started"),
        ("seal_measurement", "completed"),
    ]


def test_append_identity_is_stable_and_content_detects_conflict() -> None:
    projected = _projected()
    assert projected.schema is not None
    append = MeasurementDatasetAppend(
        run_id=projected.run_id,
        dataset_id=projected.schema.dataset_id,
        recording_contract_fingerprint=projected.recording_contract_fingerprint,
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
    assert changed.operation_id == append.operation_id
    assert changed.content_hash != append.content_hash


class _InvalidReceiptWriter(MemoryMeasurementDatasetRepository):
    @override
    def append(self, append: MeasurementDatasetAppend) -> MeasurementDatasetReceipt:
        return MeasurementDatasetReceipt(
            operation_id=append.operation_id,
            dataset_content_hash="sha256:wrong",
            dataset_ref="memory/wrong.json",
        )


def test_invalid_append_receipt_terminalizes_uncertain_operation() -> None:
    with pytest.raises(MeasurementRecordingError) as caught:
        append_measurement_dataset(
            _projected(),
            _InvalidReceiptWriter(),
            MemoryExecutionJournal(),
        )
    assert caught.value.write_may_have_completed
    assert caught.value.receipt is not None


def test_append_and_seal_replay_are_idempotent() -> None:
    projected = _projected()
    writer = MemoryMeasurementDatasetRepository()
    receipt = append_measurement_dataset(projected, writer, MemoryExecutionJournal())
    assert receipt is not None
    repeated = append_measurement_dataset(projected, writer, MemoryExecutionJournal())
    assert repeated == receipt
    _seal(projected, writer, MemoryExecutionJournal(), receipt)
    _seal(projected, writer, MemoryExecutionJournal(), receipt)
    assert len(writer.appends) == 1
    assert writer.measurements() == projected.records
