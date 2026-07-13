from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

import scopecat._storage.local.io as local_io
import scopecat._storage.local.run_repository as run_repository
from scopecat._execution.journal import (
    CollectionChunk,
    ExecutionJournalEntry,
    ExecutionJournalError,
)
from scopecat._measurement_storage import write_measurement_records_path
from scopecat._storage.local import (
    LocalCollectionCommitter,
    LocalExecutionJournal,
    LocalMeasurementCommitter,
    LocalRunLayout,
    LocalRunStore,
)
from scopecat.errors import CheckFailed, DataIntegrityError, NotFound, StorageError
from scopecat.instruments import InstrumentReadback
from scopecat.models.parameter import Quantity
from scopecat.models.run import RunManifest, RunOutcome
from scopecat.problems import ProblemCategory, StorageLocation
from scopecat.results import MeasurementRecord


class JsonlRecord(BaseModel):
    message: str


def test_local_run_layout_resolves_run_relative_refs(tmp_path) -> None:
    layout = LocalRunLayout.from_workspace(tmp_path)

    assert layout.ref_path("run-000001", "artifacts/result.json") == (
        tmp_path / "runs" / "run-000001" / "artifacts" / "result.json"
    )

    with pytest.raises(CheckFailed) as relative_escape:
        layout.ref_path("run-000001", "../outside.json")
    assert relative_escape.value.problems[0].code == "run.ref_path_escape"

    with pytest.raises(CheckFailed) as absolute_escape:
        layout.ref_path("run-000001", "/outside.json")
    assert absolute_escape.value.problems[0].code == "run.ref_path_escape"

    with pytest.raises(CheckFailed) as run_escape:
        layout.ref_path("../outside", "manifest.json")
    assert run_escape.value.problems[0].code == "run.id_invalid"


def test_local_run_store_round_trips_model_text_and_jsonl(tmp_path) -> None:
    store = LocalRunStore(tmp_path)
    run_id = "run-000001"
    manifest = _manifest(run_id, datetime(2026, 1, 1, tzinfo=UTC))
    records = [
        JsonlRecord(message="Started."),
        JsonlRecord(message="Completed."),
    ]

    store.write_manifest(manifest)
    store.write_text(run_id, "artifacts/summary.md", "# Summary")
    store.write_jsonl(run_id, "records.jsonl", records)

    assert store.read_manifest(run_id) == manifest
    assert store.read_text(run_id, "artifacts/summary.md") == "# Summary\n"
    assert store.read_jsonl(run_id, "records.jsonl", JsonlRecord) == records


def test_local_run_store_lists_runs_by_created_at(tmp_path) -> None:
    store = LocalRunStore(tmp_path)
    later = _manifest("run-000002", datetime(2026, 1, 2, tzinfo=UTC))
    earlier = _manifest("run-000001", datetime(2026, 1, 1, tzinfo=UTC))

    store.write_manifest(later)
    store.write_manifest(earlier)

    assert [manifest.run_id for manifest in store.list_runs()] == [
        "run-000001",
        "run-000002",
    ]


def test_local_run_store_writes_manifest_atomically(tmp_path) -> None:
    store = LocalRunStore(tmp_path)
    run_id = "run-000001"
    store.write_manifest(_manifest(run_id, datetime(2026, 1, 1, tzinfo=UTC)))

    updated = RunManifest(
        run_id=run_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        lifecycle="running",
    )
    store.write_manifest(updated)

    assert store.read_manifest(run_id).status == "running"
    assert not store.ref_path(run_id, "manifest.json.tmp").exists()


def test_local_run_store_maps_missing_run_to_not_found(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path)

    with pytest.raises(NotFound) as captured:
        store.read_manifest("run-missing")

    problem = captured.value.problems[0]
    assert problem.code == "run.not_found"
    assert problem.category is ProblemCategory.NOT_FOUND
    assert problem.location == StorageLocation(
        run_id="run-missing",
        ref="manifest.json",
    )
    assert isinstance(captured.value.__cause__, FileNotFoundError)


def test_local_run_store_rejects_run_namespace_symlink_escape(
    tmp_path: Path,
) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    run_link = tmp_path / "runs" / "run-link"
    run_link.parent.mkdir()
    run_link.symlink_to(outside, target_is_directory=True)

    store = LocalRunStore(tmp_path)
    with pytest.raises(DataIntegrityError) as captured:
        store.ref_path("run-link", "manifest.json")

    assert captured.value.problems[0].code == "storage.namespace_escape"


def test_local_run_store_maps_invalid_manifest_to_data_integrity(
    tmp_path: Path,
) -> None:
    store = LocalRunStore(tmp_path)
    manifest_path = store.ref_path("run-invalid", "manifest.json")
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text("{}")

    with pytest.raises(DataIntegrityError) as captured:
        store.read_manifest("run-invalid")

    assert captured.value.problems[0].code == "run.manifest_invalid"
    assert captured.value.problems[0].category is ProblemCategory.DATA_INTEGRITY
    assert captured.value.__cause__ is not None


def test_local_run_store_maps_io_failure_without_exposing_raw_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalRunStore(tmp_path)
    storage_cause = PermissionError("private filesystem details")

    def fail_read_model(*_args: object, **_kwargs: object) -> RunManifest:
        raise storage_cause

    monkeypatch.setattr(run_repository, "_read_model", fail_read_model)

    with pytest.raises(StorageError) as captured:
        store.read_manifest("run-private")

    assert captured.value.__cause__ is storage_cause
    assert captured.value.problems[0].category is ProblemCategory.STORAGE
    assert "private filesystem details" not in str(captured.value)


def test_atomic_models_and_journal_fsync_file_and_parent(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LocalRunStore(tmp_path)
    run_id = "run-durable"
    store.ref_path(run_id, "manifest.json").parent.mkdir(parents=True)
    store.ref_path(run_id, "records/immutable.json").parent.mkdir(parents=True)
    (tmp_path / "runs" / run_id / "execution" / "journal").mkdir(parents=True)
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(file_descriptor: int) -> None:
        fsync_calls.append(file_descriptor)
        real_fsync(file_descriptor)

    monkeypatch.setattr(
        "scopecat._storage.local.io.os.fsync",
        recording_fsync,
    )
    store.write_manifest(_manifest(run_id, datetime(2026, 1, 1, tzinfo=UTC)))
    assert len(fsync_calls) == 2

    fsync_calls.clear()
    assert store.write_model_if_absent(
        run_id,
        "records/immutable.json",
        JsonlRecord(message="durable"),
    )
    assert len(fsync_calls) == 2

    fsync_calls.clear()
    journal = LocalExecutionJournal(tmp_path, run_id=run_id)
    journal.append(
        ExecutionJournalEntry(
            run_id=run_id,
            operation_id="test.operation",
            stage="point",
            effect="pure",
            state="completed",
        )
    )
    assert len(fsync_calls) == 2


def test_immutable_publish_durably_creates_each_nested_directory(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synced_directories: list[Path] = []
    real_fsync_directory = local_io._fsync_directory

    def recording_fsync_directory(path: Path) -> None:
        synced_directories.append(path)
        real_fsync_directory(path)

    monkeypatch.setattr(local_io, "_fsync_directory", recording_fsync_directory)
    first = tmp_path / "first"
    second = first / "second"
    path = second / "immutable.json"

    assert local_io.write_model_if_absent(
        path,
        JsonlRecord(message="durable nested link"),
    )

    assert synced_directories == [
        first,
        tmp_path,
        second,
        first,
        second,
    ]


def test_collection_chunk_hashes_and_replays_non_finite_readbacks(tmp_path) -> None:
    chunk = CollectionChunk(
        run_id="run-non-finite",
        operation_id="point-0.collect.source",
        point_index=0,
        instrument_id="source",
        readback=InstrumentReadback(
            values={
                "nan": Quantity(value=float("nan"), unit="ratio"),
                "positive-infinity": Quantity(value=float("inf"), unit="ratio"),
                "negative-infinity": Quantity(
                    value=float("-inf"),
                    unit="ratio",
                ),
            },
            metadata={
                "nested": {"values": [1, None, True]},
                "non-finite": float("nan"),
            },
        ),
    )
    committer = LocalCollectionCommitter(tmp_path, run_id=chunk.run_id)

    first = committer.commit(chunk)
    second = committer.commit(chunk.model_copy(deep=True))
    stored = local_io.read_model(
        LocalRunStore(tmp_path).ref_path(chunk.run_id, first.ref),
        CollectionChunk,
    )

    assert first == second
    assert first.content_hash == chunk.content_hash == stored.content_hash


@pytest.mark.parametrize("value", [(1, 2), {1, 2}, object()])
def test_instrument_readback_rejects_non_json_metadata(value: object) -> None:
    with pytest.raises(ValidationError):
        InstrumentReadback(metadata={"value": value})  # type: ignore[dict-item]


def test_local_measurement_commit_is_canonical_and_nan_idempotent(tmp_path) -> None:
    measurement = MeasurementRecord(
        run_id="run-measurement-replay",
        point_index=0,
        coordinates={},
        observables={"signal": Quantity(value=float("nan"), unit="ratio")},
        metadata={"stable": ["json", 1]},
    )
    committer = LocalMeasurementCommitter(tmp_path, run_id=measurement.run_id)

    committer.commit(measurement)
    committer.commit(measurement.model_copy(deep=True))

    assert len(committer.measurements()) == 1
    assert committer.measurements()[0].metadata == {"stable": ["json", 1]}
    different = measurement.model_copy(
        update={"observables": {"signal": Quantity(value=float("inf"), unit="ratio")}}
    )
    with pytest.raises(ExecutionJournalError, match="different committed"):
        committer.commit(different)


@pytest.mark.parametrize("value", [(1, 2), {1, 2}, object()])
def test_measurement_record_rejects_non_json_metadata(value: object) -> None:
    with pytest.raises(ValidationError):
        MeasurementRecord(
            run_id="run-invalid-metadata",
            point_index=0,
            coordinates={},
            observables={},
            metadata={"value": value},  # type: ignore[dict-item]
        )


def test_collection_chunk_digest_failure_precedes_publish(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk = CollectionChunk(
        run_id="run-hash-failure",
        operation_id="point-0.collect.source",
        point_index=0,
        instrument_id="source",
        readback=InstrumentReadback(),
    )

    def fail_hash(value: object) -> str:
        del value
        raise ValueError("hash failed")

    monkeypatch.setattr(
        "scopecat._content_identity.stable_content_hash",
        fail_hash,
    )

    with pytest.raises(ValueError, match="hash failed"):
        LocalCollectionCommitter(tmp_path, run_id=chunk.run_id).commit(chunk)

    assert not (tmp_path / "runs" / chunk.run_id).exists()


def test_measurement_dataset_fsyncs_file_and_parent(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(file_descriptor: int) -> None:
        fsync_calls.append(file_descriptor)
        real_fsync(file_descriptor)

    monkeypatch.setattr(
        "scopecat._measurement_storage.os.fsync",
        recording_fsync,
    )
    write_measurement_records_path(
        path=tmp_path / "measurements.ndjson",
        records=[
            MeasurementRecord(
                run_id="run-durable",
                point_index=0,
                coordinates={},
                observables={},
            )
        ],
    )

    assert len(fsync_calls) == 2


def _manifest(run_id: str, created_at: datetime) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        created_at=created_at,
        lifecycle="terminal",
        outcome=RunOutcome(
            run_id=run_id,
            result="succeeded",
            certainty="known",
            termination_reason="completed",
        ),
    )
