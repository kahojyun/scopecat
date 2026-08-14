from __future__ import annotations

from typing import cast, override

import pytest
from scopecat_testkit.execution_fakes import FakeMeasurementDatasetRepository
from scopecat_testkit.measurement_assembly import (
    assembled_measurement_values_for_all_uses,
)

from scopecat.execution.measurement_recording import (
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
    MeasurementDatasetSeal,
    measurement_dataset_content_hash,
    measurement_record_content_hash,
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
    header: MeasurementDatasetHeader,
) -> MeasurementDatasetReceipt:
    return seal_measurement_dataset(
        run_id=projected.run_id,
        header=header,
        point_count=len(projected.records),
        record_content_hashes=tuple(
            measurement_record_content_hash(record) for record in projected.records
        ),
        writer=writer,
    )


def _header(projected: ProjectedMeasurementDataset) -> MeasurementDatasetHeader:
    schema = projected.projection.schema
    assert schema is not None
    return MeasurementDatasetHeader(
        run_id=projected.run_id,
        recording_contract_fingerprint=projected.recording_contract_fingerprint,
        dataset_schema=schema,
        expected_record_count=projected.projection.catalog.point_contract.point_count,
        record_count_limit=projected.projection.catalog.point_contract.point_limit,
    )


def test_recording_initializes_and_seals_one_canonical_dataset() -> None:
    projected = _projected()
    writer = FakeMeasurementDatasetRepository()
    header = _header(projected)

    header_receipt = initialize_measurement_dataset(header, writer)
    append_receipt = writer.append(
        MeasurementDatasetAppend(
            run_id=projected.run_id,
            header_content_hash=header.content_hash,
            start_index=0,
            records=projected.records,
        )
    )
    seal_receipt = _seal(projected, writer, header)

    [append] = writer.appends
    assert append.records == projected.records
    assert header_receipt.dataset_ref == CANONICAL_MEASUREMENT_DATASET_REF
    assert append_receipt.dataset_ref == CANONICAL_MEASUREMENT_DATASET_REF
    assert seal_receipt.dataset_ref == CANONICAL_MEASUREMENT_DATASET_REF


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


def test_dataset_identity_is_independent_of_append_chunk_boundaries() -> None:
    projected = _projected()
    header = _header(projected)
    records = projected.records
    whole = MeasurementDatasetAppend(
        run_id=projected.run_id,
        header_content_hash=header.content_hash,
        start_index=0,
        records=records,
    )
    split_at = len(records) // 2
    first = whole.model_copy(update={"records": records[:split_at]})
    second = whole.model_copy(
        update={
            "start_index": split_at,
            "records": records[split_at:],
        }
    )

    whole_hash = measurement_dataset_content_hash(
        header_content_hash=header.content_hash,
        record_content_hashes=whole.record_content_hashes,
    )
    split_hash = measurement_dataset_content_hash(
        header_content_hash=header.content_hash,
        record_content_hashes=(
            *first.record_content_hashes,
            *second.record_content_hashes,
        ),
    )

    assert whole_hash == split_hash


def test_header_and_append_content_hashes_cannot_change_after_construction() -> None:
    projected = _projected()
    header = _header(projected)
    append = MeasurementDatasetAppend(
        run_id=projected.run_id,
        header_content_hash=header.content_hash,
        start_index=0,
        records=projected.records,
    )
    header_hash = header.content_hash
    append_hash = append.content_hash

    with pytest.raises(TypeError, match="frozen mapping is immutable"):
        cast("dict[str, object]", header.dataset_schema.metadata)["revision"] = 2
    with pytest.raises(TypeError, match="frozen mapping is immutable"):
        cast("dict[str, object]", append.records[0].metadata)["changed"] = True

    assert header.content_hash == header_hash
    assert append.content_hash == append_hash


class _InvalidReceiptWriter(FakeMeasurementDatasetRepository):
    @override
    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt:
        return MeasurementDatasetReceipt(
            operation_id=seal.operation_id,
            dataset_content_hash="sha256:wrong",
        )


def test_invalid_seal_receipt_terminalizes_uncertain_operation() -> None:
    projected = _projected()
    header = _header(projected)
    writer = _InvalidReceiptWriter()
    initialize_measurement_dataset(header, writer)
    with pytest.raises(MeasurementRecordingError) as caught:
        _seal(projected, writer, header)
    assert caught.value.write_may_have_completed
    assert caught.value.receipt is not None


def test_initialize_and_seal_replay_are_idempotent() -> None:
    projected = _projected()
    writer = FakeMeasurementDatasetRepository()
    header = _header(projected)
    initialized = initialize_measurement_dataset(header, writer)
    repeated = initialize_measurement_dataset(header, writer)
    writer.append(
        MeasurementDatasetAppend(
            run_id=projected.run_id,
            header_content_hash=header.content_hash,
            start_index=0,
            records=projected.records,
        )
    )
    first_seal = _seal(projected, writer, header)
    repeated_seal = _seal(projected, writer, header)
    assert repeated == initialized
    assert repeated_seal == first_seal
    assert len(writer.appends) == 1
    assert writer.measurements() == projected.records
