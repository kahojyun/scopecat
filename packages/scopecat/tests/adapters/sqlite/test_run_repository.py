from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier
from typing import override

import pytest
from pydantic import BaseModel

from scopecat.adapters.sqlite import SQLiteControlPlane, SQLiteRunRepository
from scopecat.kernel.errors import DataIntegrityError, StorageError
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.runs.repository import RunModelWrite, TerminalRunCommit
from tests.contracts.run_repository_contracts import RunRepositoryContract


class _Record(BaseModel):
    value: str


def _repository(root: Path) -> SQLiteRunRepository:
    repository = SQLiteRunRepository(
        root / "workspace.sqlite3",
        root / "objects",
    )
    repository.bootstrap()
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
    database = tmp_path / "workspace.sqlite3"
    control = SQLiteControlPlane(database)
    control.bootstrap()
    repository = SQLiteRunRepository(database, tmp_path / "objects")
    repository.bootstrap()

    repository.write_manifest(_manifest("run-shared"))

    assert control.schema_version() == 1
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


def test_bootstrap_refuses_unknown_run_schema(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    with sqlite3.connect(repository.database) as connection:
        connection.execute("UPDATE run_repository_schema SET version = 99")

    with pytest.raises(DataIntegrityError) as captured:
        repository.bootstrap()

    assert captured.value.problems[0].code == "storage.schema_unsupported"
