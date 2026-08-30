from __future__ import annotations

from pathlib import Path

import pytest

from scopecat_server.storage.sqlite.measurement_pack import (
    MeasurementPackCorruptError,
    MeasurementPackNotFoundError,
    MeasurementPackStore,
    PackedMeasurementPayload,
    measurement_segment_pack_id,
)


def test_measurement_pack_appends_multiple_verified_frames_to_one_file(
    tmp_path: Path,
) -> None:
    store = MeasurementPackStore(tmp_path / "packs")
    store.bootstrap()
    pack_id = measurement_segment_pack_id(run_id="run-1", segment_id="segment-1")

    first = store.append(pack_id, b"first Arrow payload")
    second = store.append(pack_id, b"second Arrow payload")

    assert first.pack_id == second.pack_id == pack_id
    assert second.offset > first.offset
    assert store.read(first) == b"first Arrow payload"
    assert store.read(second) == b"second Arrow payload"
    assert [path for path in store.root.rglob("*.pack") if path.is_file()] == [
        store.path_for(pack_id)
    ]


def test_measurement_pack_ignores_unindexed_tail_before_later_frame(
    tmp_path: Path,
) -> None:
    store = MeasurementPackStore(tmp_path / "packs")
    store.bootstrap()
    pack_id = measurement_segment_pack_id(run_id="run-1", segment_id="segment-1")
    first = store.append(pack_id, b"first")
    with store.path_for(pack_id).open("ab") as output:
        output.write(b"orphaned partial frame")

    later = store.append(pack_id, b"later")

    assert store.read(first) == b"first"
    assert store.read(later) == b"later"


def test_measurement_pack_trims_only_the_unindexed_tail(tmp_path: Path) -> None:
    store = MeasurementPackStore(tmp_path / "packs")
    store.bootstrap()
    pack_id = measurement_segment_pack_id(run_id="run-1", segment_id="segment-1")
    published = store.append(pack_id, b"published")
    unindexed = store.append(pack_id, b"unindexed")
    original_size = store.path_for(pack_id).stat().st_size

    reclaimed = store.trim_unindexed_tail(
        pack_id,
        indexed_end=published.end_offset,
    )

    assert reclaimed == original_size - published.end_offset
    assert store.path_for(pack_id).stat().st_size == published.end_offset
    assert store.read(published) == b"published"
    with pytest.raises(MeasurementPackCorruptError):
        store.read(unindexed)


def test_measurement_pack_refuses_to_trim_below_an_indexed_end(
    tmp_path: Path,
) -> None:
    store = MeasurementPackStore(tmp_path / "packs")
    store.bootstrap()
    pack_id = measurement_segment_pack_id(run_id="run-1", segment_id="segment-1")
    published = store.append(pack_id, b"published")
    original_size = store.path_for(pack_id).stat().st_size

    with pytest.raises(MeasurementPackCorruptError):
        store.trim_unindexed_tail(
            pack_id,
            indexed_end=published.end_offset + 1,
        )

    assert store.path_for(pack_id).stat().st_size == original_size
    assert store.read(published) == b"published"


def test_measurement_pack_rejects_missing_and_mismatched_frames(
    tmp_path: Path,
) -> None:
    store = MeasurementPackStore(tmp_path / "packs")
    store.bootstrap()
    pack_id = measurement_segment_pack_id(run_id="run-1", segment_id="segment-1")
    payload = store.append(pack_id, b"payload")
    mismatched = PackedMeasurementPayload(
        pack_id=payload.pack_id,
        offset=payload.offset,
        length=payload.length,
        digest=f"sha256:{'0' * 64}",
    )
    missing = PackedMeasurementPayload(
        pack_id=measurement_segment_pack_id(
            run_id="missing",
            segment_id="segment-1",
        ),
        offset=0,
        length=1,
        digest=f"sha256:{'0' * 64}",
    )

    with pytest.raises(MeasurementPackCorruptError):
        store.read(mismatched)
    with pytest.raises(MeasurementPackNotFoundError):
        store.read(missing)


def test_measurement_pack_fsyncs_each_published_frame(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MeasurementPackStore(tmp_path / "packs")
    store.bootstrap()
    pack_id = measurement_segment_pack_id(run_id="run-1", segment_id="segment-1")
    fsync_calls = 0

    def fsync(_descriptor: int) -> None:
        nonlocal fsync_calls
        fsync_calls += 1

    def skip_directory_fsync(_path: Path) -> None:
        return

    monkeypatch.setattr(
        "scopecat_server.storage.sqlite.measurement_pack.os.fsync",
        fsync,
    )
    monkeypatch.setattr(
        "scopecat_server.storage.sqlite.measurement_pack._fsync_directory",
        skip_directory_fsync,
    )

    store.append(pack_id, b"first")
    store.append(pack_id, b"second")

    assert fsync_calls == 2
