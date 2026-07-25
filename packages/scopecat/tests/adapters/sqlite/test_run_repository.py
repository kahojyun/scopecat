from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import override

import pytest
from pydantic import BaseModel

from scopecat.adapters.sqlite import SQLiteProjectStore, SQLiteRunRepository
from scopecat.kernel.errors import DataIntegrityError, StorageError
from scopecat.records.artifact import RunContentEntry
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.runs.repository import (
    RunBytesWrite,
    RunContentPublication,
    RunModelWrite,
    TerminalRunCommit,
)
from tests.contracts.run_repository_contracts import RunRepositoryContract


class _Record(BaseModel):
    value: str


def _repository(root: Path) -> SQLiteRunRepository:
    SQLiteProjectStore(
        root / "control.sqlite3",
        root / "objects",
    ).bootstrap()
    repository = SQLiteRunRepository(
        root / "control.sqlite3",
        root / "objects",
    )
    return repository


def _manifest(run_id: str, *, lifecycle: str = "running") -> RunManifest:
    if lifecycle == "terminal":
        return RunManifest(
            run_id=run_id,
            created_at=datetime(2026, 7, 23, tzinfo=UTC),
            lifecycle="terminal",
            config_content_hash=f"sha256:{'0' * 64}",
            outcome=_outcome(run_id),
        )
    return RunManifest(
        run_id=run_id,
        created_at=datetime(2026, 7, 23, tzinfo=UTC),
        lifecycle="running",
        config_content_hash=f"sha256:{'0' * 64}",
    )


def _outcome(run_id: str) -> RunOutcome:
    return RunOutcome(
        run_id=run_id,
        result="succeeded",
        certainty="known",
        termination_reason="completed",
    )


def _content(content_id: str) -> RunContentEntry:
    return RunContentEntry(
        role="artifact",
        id=content_id,
        kind="test",
        content_hash=f"{content_id}-content",
    )


def _terminal_commit(run_id: str, content_id: str) -> TerminalRunCommit:
    return TerminalRunCommit(
        manifest=_manifest(run_id, lifecycle="terminal").model_copy(
            update={"contents": (_content(content_id),)}
        ),
        models=(
            RunModelWrite(
                ref=f"records/{content_id}.json",
                value=_Record(value=content_id),
            ),
        ),
    )


def _object_files(repository: SQLiteRunRepository) -> set[Path]:
    return {
        path
        for path in repository.objects.root.rglob("*")
        if path.is_file() and not path.name.startswith(".")
    }


class TestSQLiteRunRepositoryContract(RunRepositoryContract):
    @override
    def make_repository(self, tmp_path: Path) -> SQLiteRunRepository:
        return _repository(tmp_path)


def test_control_plane_and_run_index_share_one_database(tmp_path: Path) -> None:
    database = tmp_path / "control.sqlite3"
    SQLiteProjectStore(database, tmp_path / "objects").bootstrap()
    repository = SQLiteRunRepository(database, tmp_path / "objects")

    repository.write_manifest(_manifest("run-shared"))

    assert repository.read_manifest("run-shared").run_id == "run-shared"
    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type = 'table'"
            )
        }
    assert {
        "runs",
        "durable_events",
        "run_repository_refs",
        "run_repository_manifests",
    } <= tables


def test_equal_content_reuses_one_immutable_object(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    repository.write_bytes("run-a", "artifacts/a.bin", b"same")
    repository.write_bytes("run-b", "artifacts/b.bin", b"same")

    with sqlite3.connect(repository.database) as connection:
        digests = {
            row[0]
            for row in connection.execute(
                "SELECT digest FROM run_repository_refs ORDER BY run_id"
            )
        }
    assert len(digests) == 1
    assert len(_object_files(repository)) == 1


def test_if_absent_uses_database_cas_across_connections(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    peer = SQLiteRunRepository(repository.database, repository.objects.root)
    barrier = Barrier(2)

    def publish(selected: SQLiteRunRepository, value: str) -> bool:
        barrier.wait()
        return selected.write_model_if_absent(
            "run-cas",
            "records/value.json",
            _Record(value=value),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(publish, repository, "first"),
            pool.submit(publish, peer, "second"),
        )
        results = [future.result() for future in futures]

    assert sorted(results) == [False, True]
    assert repository.read_model(
        "run-cas",
        "records/value.json",
        _Record,
    ).value in {"first", "second"}


def test_terminal_commit_rolls_back_all_refs_if_manifest_publish_fails(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id = "run-rollback"
    repository.write_manifest(_manifest(run_id))
    objects_before = _object_files(repository)
    with sqlite3.connect(repository.database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_terminal_manifest
            BEFORE UPDATE OF digest ON run_repository_refs
            WHEN OLD.run_id = 'run-rollback' AND OLD.ref = 'manifest.json'
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END
            """
        )

    with pytest.raises(StorageError):
        repository.commit_terminal(
            TerminalRunCommit(
                manifest=_manifest(run_id, lifecycle="terminal"),
                models=(
                    RunModelWrite(
                        ref="records/outcome.json",
                        value=_outcome(run_id),
                    ),
                ),
            )
        )

    assert repository.read_manifest(run_id).lifecycle == "running"
    assert not repository.exists(run_id, "records/outcome.json")
    assert len(_object_files(repository)) > len(objects_before)


def test_terminal_commit_merges_contents_after_acquiring_the_write_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(tmp_path)
    run_id = "run-concurrent-terminal"
    repository.write_manifest(
        _manifest(run_id).model_copy(update={"contents": (_content("existing"),)})
    )
    concurrent_read = Barrier(2)
    start = Barrier(2)
    original_read_manifest = repository.read_manifest

    def synchronize_reads(selected_run_id: str) -> RunManifest:
        current = original_read_manifest(selected_run_id)
        concurrent_read.wait(timeout=5)
        return current

    monkeypatch.setattr(repository, "read_manifest", synchronize_reads)

    def publish(content_id: str) -> RunManifest:
        start.wait(timeout=5)
        return repository.commit_terminal(_terminal_commit(run_id, content_id))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(publish, "first"),
            pool.submit(publish, "second"),
        )
        for future in futures:
            future.result()

    peer = SQLiteRunRepository(repository.database, repository.objects.root)
    assert {entry.id for entry in peer.read_manifest(run_id).contents} == {
        "existing",
        "first",
        "second",
    }


def test_terminal_commit_primitive_uses_and_leaves_the_callers_transaction(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id = "run-terminal-transaction"
    repository.write_manifest(
        _manifest(run_id).model_copy(update={"contents": (_content("existing"),)})
    )
    objects_before = _object_files(repository)

    with sqlite3.connect(
        repository.database,
        isolation_level=None,
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        repository.commit_terminal_in_transaction(
            connection,
            _terminal_commit(run_id, "first"),
        )
        committed = repository.commit_terminal_in_transaction(
            connection,
            _terminal_commit(run_id, "second"),
        )

        assert connection.in_transaction
        assert {entry.id for entry in committed.contents} == {
            "existing",
            "first",
            "second",
        }
        assert (
            connection.execute(
                """
            SELECT COUNT(*) FROM run_repository_refs
            WHERE run_id = ? AND ref IN (?, ?)
            """,
                (
                    run_id,
                    "records/first.json",
                    "records/second.json",
                ),
            ).fetchone()[0]
            == 2
        )
        connection.rollback()

    assert repository.read_manifest(run_id).lifecycle == "running"
    assert not repository.exists(run_id, "records/first.json")
    assert not repository.exists(run_id, "records/second.json")
    assert len(_object_files(repository)) > len(objects_before)


def test_prepared_content_uses_and_leaves_the_callers_transaction(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id = "run-prepared-content"
    repository.write_manifest(_manifest(run_id))
    objects_before = _object_files(repository)
    publication = RunContentPublication(
        run_id=run_id,
        entries=(_content("prepared"),),
        bytes=(
            RunBytesWrite(
                ref="artifacts/prepared.bin",
                content=b"prepared",
            ),
        ),
    )

    prepared = repository.prepare_content_publication(publication)

    assert len(_object_files(repository)) > len(objects_before)
    assert not repository.exists(run_id, "artifacts/prepared.bin")
    with sqlite3.connect(
        repository.database,
        isolation_level=None,
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        manifest = repository.publish_prepared_content_in_transaction(
            connection,
            prepared,
        )

        assert connection.in_transaction
        assert _content("prepared") in manifest.contents
        assert (
            connection.execute(
                """
                SELECT COUNT(*) FROM run_repository_refs
                WHERE run_id = ? AND ref = ?
                """,
                (run_id, "artifacts/prepared.bin"),
            ).fetchone()[0]
            == 1
        )
        connection.rollback()

    assert repository.read_manifest(run_id).contents == ()
    assert not repository.exists(run_id, "artifacts/prepared.bin")


def test_content_publications_merge_the_latest_manifest_across_writers(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id = "run-concurrent-content"
    repository.write_manifest(
        _manifest(run_id).model_copy(update={"contents": (_content("existing"),)})
    )
    peer = SQLiteRunRepository(repository.database, repository.objects.root)
    ready = Barrier(2)

    def publish(selected: SQLiteRunRepository, content_id: str) -> None:
        prepared = selected.prepare_content_publication(
            RunContentPublication(
                run_id=run_id,
                entries=(_content(content_id),),
                bytes=(
                    RunBytesWrite(
                        ref=f"artifacts/{content_id}.bin",
                        content=content_id.encode(),
                    ),
                ),
            )
        )
        ready.wait(timeout=5)
        with sqlite3.connect(
            selected.database,
            isolation_level=None,
            timeout=5,
        ) as connection:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN IMMEDIATE")
            selected.publish_prepared_content_in_transaction(connection, prepared)
            connection.commit()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(publish, repository, "first"),
            pool.submit(publish, peer, "second"),
        )
        for future in futures:
            future.result()

    assert {entry.id for entry in repository.read_manifest(run_id).contents} == {
        "existing",
        "first",
        "second",
    }


def test_corrupt_indexed_object_is_data_integrity_failure(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.write_bytes("run-corrupt", "artifacts/value.bin", b"original")
    with sqlite3.connect(repository.database) as connection:
        row = connection.execute(
            """
            SELECT digest FROM run_repository_refs
            WHERE run_id = 'run-corrupt' AND ref = 'artifacts/value.bin'
            """
        ).fetchone()
    assert row is not None
    repository.objects.path_for(row[0]).write_bytes(b"corrupt")

    with pytest.raises(DataIntegrityError) as captured:
        repository.read_bytes("run-corrupt", "artifacts/value.bin")

    assert captured.value.problems[0].code == "run.ref_invalid"
