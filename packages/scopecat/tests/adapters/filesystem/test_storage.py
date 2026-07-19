from __future__ import annotations

import os
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

import scopecat.adapters.filesystem.io as local_io
import scopecat.adapters.filesystem.run_repository as run_repository
from scopecat.adapters.filesystem.execution import (
    FilesystemCollectionRepository,
    FilesystemExecutionJournal,
    FilesystemMeasurementDatasetRepository,
)
from scopecat.adapters.filesystem.layout import FilesystemRunLayout
from scopecat.adapters.filesystem.measurement_files import (
    write_measurement_records_path,
)
from scopecat.adapters.filesystem.run_repository import FilesystemRunRepository
from scopecat.adapters.memory import MemoryCollectionRepository
from scopecat.execution.ports.journal import ExecutionJournalError
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.errors import (
    CheckFailed,
    DataIntegrityError,
    NotFound,
    StorageError,
)
from scopecat.kernel.problems import ProblemCategory, StorageLocation
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    ExecutionJournalEntry,
)
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetReceipt,
)
from scopecat.records.parameter import Quantity
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.sdk.instruments import InstrumentReadback


class JsonlRecord(BaseModel):
    message: str


def _write_replace_fixture(kind: str, path: Path, message: str) -> None:
    if kind == "model":
        local_io.write_model(path, JsonlRecord(message=message))
        return
    if kind == "text":
        local_io.write_text(path, message)
        return
    if kind == "jsonl":
        local_io.write_jsonl(path, [JsonlRecord(message=message)])
        return
    raise AssertionError(f"unknown replace fixture kind: {kind}")


@pytest.mark.parametrize("repository_kind", ("memory", "local"))
def test_collection_repository_contract(repository_kind: str, tmp_path: Path) -> None:
    chunk = CollectionChunk(
        run_id="collection-repository-contract-run",
        operation_id="point-0.collect.source",
        command_content_hash="collection-repository-contract-command",
        point_index=0,
        instrument_id="source",
        readback=InstrumentReadback(
            values={"signal": Quantity(value=1.0, unit="ratio")}
        ),
    )
    repository = (
        MemoryCollectionRepository()
        if repository_kind == "memory"
        else FilesystemCollectionRepository(tmp_path, run_id=chunk.run_id)
    )

    receipt = repository.commit(chunk)
    repeated = repository.commit(chunk.model_copy(deep=True))
    resolved = repository.resolve(receipt)
    resolved.instrument_id = "mutated-caller-copy"

    assert repeated == receipt
    assert receipt.operation_id == chunk.operation_id
    assert receipt.content_hash == chunk.content_hash
    assert repository.resolve(receipt).content_hash == chunk.content_hash
    assert repository.resolve(receipt).instrument_id == chunk.instrument_id

    for update in (
        {"operation_id": "foreign-operation"},
        {"ref": "foreign/collection.json"},
        {"content_hash": "foreign-content-hash"},
    ):
        with pytest.raises(ExecutionJournalError):
            repository.resolve(receipt.model_copy(update=update))

    conflicting = chunk.model_copy(
        update={"readback": InstrumentReadback()},
        deep=True,
    )
    with pytest.raises(ExecutionJournalError):
        repository.commit(conflicting)


def test_local_run_layout_resolves_run_relative_refs(tmp_path: Path) -> None:
    layout = FilesystemRunLayout.from_workspace(tmp_path)

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


def test_local_run_store_round_trips_model_text_and_jsonl(tmp_path: Path) -> None:
    store = FilesystemRunRepository(tmp_path)
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


def test_local_run_store_lists_runs_by_created_at(tmp_path: Path) -> None:
    store = FilesystemRunRepository(tmp_path)
    later = _manifest("run-000002", datetime(2026, 1, 2, tzinfo=UTC))
    earlier = _manifest("run-000001", datetime(2026, 1, 1, tzinfo=UTC))

    store.write_manifest(later)
    store.write_manifest(earlier)

    assert [manifest.run_id for manifest in store.list_runs()] == [
        "run-000001",
        "run-000002",
    ]


def test_local_run_store_writes_manifest_atomically(tmp_path: Path) -> None:
    store = FilesystemRunRepository(tmp_path)
    run_id = "run-000001"
    store.write_manifest(_manifest(run_id, datetime(2026, 1, 1, tzinfo=UTC)))

    updated = RunManifest(
        run_id=run_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        lifecycle="running",
        config_content_hash="sha256:" + "0" * 64,
    )
    store.write_manifest(updated)

    assert store.read_manifest(run_id).status == "running"
    assert not store.ref_path(run_id, "manifest.json.tmp").exists()


def test_local_run_store_maps_missing_run_to_not_found(tmp_path: Path) -> None:
    store = FilesystemRunRepository(tmp_path)

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

    store = FilesystemRunRepository(tmp_path)
    with pytest.raises(DataIntegrityError) as captured:
        store.ref_path("run-link", "manifest.json")

    assert captured.value.problems[0].code == "storage.namespace_escape"


def test_local_run_store_maps_invalid_manifest_to_data_integrity(
    tmp_path: Path,
) -> None:
    store = FilesystemRunRepository(tmp_path)
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
    store = FilesystemRunRepository(tmp_path)
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
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = FilesystemRunRepository(tmp_path)
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
        "scopecat.adapters.filesystem.io.os.fsync",
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
    journal = FilesystemExecutionJournal(tmp_path, run_id=run_id)
    journal.append(
        ExecutionJournalEntry(
            run_id=run_id,
            operation_id="test.operation",
            stage="apply_state",
            effect="state_write",
            state="started",
        )
    )
    assert len(fsync_calls) == 2


@pytest.mark.parametrize("kind", ("model", "text", "jsonl"))
def test_replace_writes_keep_previous_content_when_publish_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    path = tmp_path / f"replace-{kind}.data"
    _write_replace_fixture(kind, path, "committed")
    committed = path.read_bytes()
    real_replace = Path.replace

    def fail_target_replace(source: Path, target: Path) -> Path:
        if target == path:
            raise OSError("injected atomic replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_target_replace)

    with pytest.raises(OSError, match="injected atomic replace failure"):
        _write_replace_fixture(kind, path, "replacement")

    assert path.read_bytes() == committed
    assert list(tmp_path.glob(f".{path.name}.*.tmp")) == []


def test_replace_writes_fsync_temporary_file_and_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(file_descriptor: int) -> None:
        fsync_calls.append(file_descriptor)
        real_fsync(file_descriptor)

    monkeypatch.setattr(
        "scopecat.adapters.filesystem.io.os.fsync",
        recording_fsync,
    )

    for kind in ("model", "text", "jsonl"):
        fsync_calls.clear()
        _write_replace_fixture(kind, tmp_path / f"durable-{kind}.data", "durable")
        assert len(fsync_calls) == 2


def test_immutable_publish_durably_creates_each_nested_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    synced_directories: list[Path] = []
    real_fsync_directory = local_io.fsync_directory

    def recording_fsync_directory(path: Path) -> None:
        synced_directories.append(path)
        real_fsync_directory(path)

    monkeypatch.setattr(local_io, "fsync_directory", recording_fsync_directory)
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


def test_collection_chunk_hashes_and_replays_non_finite_readback_values(
    tmp_path: Path,
) -> None:
    chunk = CollectionChunk(
        run_id="run-non-finite",
        operation_id="point-0.collect.source",
        command_content_hash=stable_content_hash(
            {"test_command_id": "point-0.collect.source"}
        ),
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
            metadata={"nested": {"values": [1, None, True]}},
        ),
    )
    committer = FilesystemCollectionRepository(tmp_path, run_id=chunk.run_id)

    first = committer.commit(chunk)
    second = committer.commit(chunk.model_copy(deep=True))
    stored = local_io.read_model(
        FilesystemRunRepository(tmp_path).ref_path(chunk.run_id, first.ref),
        CollectionChunk,
    )

    assert first == second
    assert first.operation_id == chunk.operation_id
    assert first.content_hash == chunk.content_hash == stored.content_hash
    resolved = committer.resolve(first)
    assert resolved is not stored
    assert resolved.content_hash == stored.content_hash


@pytest.mark.parametrize(
    "receipt_update",
    [
        {"operation_id": "another-operation"},
        {"ref": "execution/readbacks/another-file.json"},
        {"content_hash": "another-content-hash"},
    ],
)
def test_local_collection_resolve_rejects_mismatched_receipt(
    tmp_path: Path,
    receipt_update: dict[str, str],
) -> None:
    chunk = CollectionChunk(
        run_id="run-resolve-mismatch",
        operation_id="point-0.collect.source",
        command_content_hash=stable_content_hash(
            {"test_command_id": "point-0.collect.source"}
        ),
        point_index=0,
        instrument_id="source",
        readback=InstrumentReadback(),
    )
    committer = FilesystemCollectionRepository(tmp_path, run_id=chunk.run_id)
    receipt = committer.commit(chunk)

    with pytest.raises(ExecutionJournalError):
        committer.resolve(receipt.model_copy(update=receipt_update))


def test_local_collection_resolve_rejects_unbacked_receipt(tmp_path: Path) -> None:
    operation_id = "point-0.collect.source"
    operation_digest = sha256(operation_id.encode("utf-8")).hexdigest()
    receipt = CollectionChunkReceipt(
        operation_id=operation_id,
        ref=f"execution/readbacks/{operation_digest}.json",
        content_hash="valid-looking-content-hash",
    )
    committer = FilesystemCollectionRepository(tmp_path, run_id="run-unbacked")

    with pytest.raises(ExecutionJournalError, match="failed to resolve"):
        committer.resolve(receipt)


def test_local_collection_resolve_rejects_corrupted_bytes(tmp_path: Path) -> None:
    chunk = CollectionChunk(
        run_id="run-corrupted-readback",
        operation_id="point-0.collect.source",
        command_content_hash="command-content-hash",
        point_index=0,
        instrument_id="source",
        readback=InstrumentReadback(),
    )
    repository = FilesystemCollectionRepository(tmp_path, run_id=chunk.run_id)
    receipt = repository.commit(chunk)
    path = FilesystemRunRepository(tmp_path).ref_path(chunk.run_id, receipt.ref)
    path.write_text('{"corrupted":', encoding="utf-8")

    with pytest.raises(ExecutionJournalError, match="failed to resolve"):
        repository.resolve(receipt)


@pytest.mark.parametrize("value", [(1, 2), {1, 2}, object(), float("nan")])
def test_instrument_readback_rejects_non_json_metadata(value: object) -> None:
    with pytest.raises(ValidationError):
        InstrumentReadback(metadata={"value": value})  # pyright: ignore[reportArgumentType]


def test_local_measurement_commit_is_canonical_and_nan_idempotent(
    tmp_path: Path,
) -> None:
    measurement = MeasurementRecord(
        run_id="run-measurement-replay",
        logical_point_id="point-0",
        point_index=0,
        coordinates={},
        observables={"signal": Quantity(value=float("nan"), unit="ratio")},
        metadata={"stable": ["json", 1]},
    )
    committer = FilesystemMeasurementDatasetRepository(
        tmp_path,
        run_id=measurement.run_id,
    )
    append = MeasurementDatasetAppend(
        run_id=measurement.run_id,
        dataset_id="raw-measurements",
        recording_contract_fingerprint="test-recording-contract",
        start_index=0,
        records=(measurement,),
    )

    first = committer.append(append)
    second = committer.append(append.model_copy(deep=True))
    stored = local_io.read_model(
        FilesystemRunRepository(tmp_path).ref_path(append.run_id, first.dataset_ref),
        MeasurementDatasetAppend,
    )

    assert (
        first
        == second
        == MeasurementDatasetReceipt(
            operation_id=append.operation_id,
            dataset_content_hash=append.content_hash,
            dataset_ref=first.dataset_ref,
        )
    )
    assert stored.operation_id == append.operation_id
    assert stored.content_hash == append.content_hash
    assert len(committer.measurements()) == 1
    assert committer.measurements()[0].logical_point_id == "point-0"
    assert committer.measurements()[0].metadata == {"stable": ["json", 1]}
    different = measurement.model_copy(
        update={"observables": {"signal": Quantity(value=float("inf"), unit="ratio")}}
    )
    with pytest.raises(ExecutionJournalError, match="different content"):
        committer.append(append.model_copy(update={"records": (different,)}))


def test_local_measurement_commit_allows_distinct_datasets_for_same_point(
    tmp_path: Path,
) -> None:
    measurement = MeasurementRecord(
        run_id="run-multi-dataset",
        logical_point_id="point-0",
        point_index=0,
        coordinates={},
        observables={"signal": Quantity(value=1.0, unit="ratio")},
    )
    committer = FilesystemMeasurementDatasetRepository(
        tmp_path,
        run_id=measurement.run_id,
    )
    raw = MeasurementDatasetAppend(
        run_id=measurement.run_id,
        dataset_id="raw-measurements",
        recording_contract_fingerprint="raw-contract",
        start_index=0,
        records=(measurement,),
    )
    derived = raw.model_copy(
        update={
            "dataset_id": "derived-measurements",
            "recording_contract_fingerprint": "derived-contract",
        }
    )

    raw_receipt = committer.append(raw)
    derived_receipt = committer.append(derived)

    assert raw.operation_id != derived.operation_id
    assert raw_receipt.dataset_ref != derived_receipt.dataset_ref
    assert len(committer.measurements()) == 2


def test_local_measurement_commit_rejects_contract_change_in_canonical_slot(
    tmp_path: Path,
) -> None:
    measurement = MeasurementRecord(
        run_id="run-contract-conflict",
        logical_point_id="point-0",
        point_index=0,
        coordinates={},
        observables={"signal": Quantity(value=1.0, unit="ratio")},
    )
    committer = FilesystemMeasurementDatasetRepository(
        tmp_path,
        run_id=measurement.run_id,
    )
    original = MeasurementDatasetAppend(
        run_id=measurement.run_id,
        dataset_id="raw-measurements",
        recording_contract_fingerprint="original-contract",
        start_index=0,
        records=(measurement,),
    )
    changed_contract = original.model_copy(
        update={"recording_contract_fingerprint": "changed-contract"}
    )

    committer.append(original)
    with pytest.raises(ExecutionJournalError, match="different content"):
        committer.append(changed_contract)

    assert original.operation_id != changed_contract.operation_id
    assert len(committer.measurements()) == 1


@pytest.mark.parametrize("value", [(1, 2), {1, 2}, object(), float("nan")])
def test_measurement_record_rejects_non_json_metadata(value: object) -> None:
    with pytest.raises(ValidationError):
        MeasurementRecord(
            run_id="run-invalid-metadata",
            point_index=0,
            coordinates={},
            observables={},
            metadata={"value": value},  # pyright: ignore[reportArgumentType]
        )


def test_collection_chunk_digest_failure_precedes_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chunk = CollectionChunk(
        run_id="run-hash-failure",
        operation_id="point-0.collect.source",
        command_content_hash=stable_content_hash(
            {"test_command_id": "point-0.collect.source"}
        ),
        point_index=0,
        instrument_id="source",
        readback=InstrumentReadback(),
    )

    def fail_hash(value: object) -> str:
        del value
        raise ValueError("hash failed")

    monkeypatch.setattr(
        "scopecat.kernel.content_identity.stable_content_hash",
        fail_hash,
    )

    with pytest.raises(ValueError, match="hash failed"):
        FilesystemCollectionRepository(tmp_path, run_id=chunk.run_id).commit(chunk)

    assert not (tmp_path / "runs" / chunk.run_id).exists()


def test_measurement_dataset_fsyncs_file_and_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def recording_fsync(file_descriptor: int) -> None:
        fsync_calls.append(file_descriptor)
        real_fsync(file_descriptor)

    monkeypatch.setattr(
        "scopecat.adapters.filesystem.io.os.fsync",
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
        config_content_hash="sha256:" + "0" * 64,
        outcome=RunOutcome(
            run_id=run_id,
            result="succeeded",
            certainty="known",
            termination_reason="completed",
        ),
    )
