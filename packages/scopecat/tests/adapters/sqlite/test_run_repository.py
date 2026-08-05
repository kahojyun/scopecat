from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from pydantic import BaseModel

from scopecat.adapters.sqlite import (
    SQLiteDatabase,
    SQLiteProjectStore,
    SQLiteRunRepository,
)
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
    StorageError,
)
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.run import (
    ConfigRegistryRunConfigSource,
    RunConfigSource,
    RunManifest,
)
from scopecat.records.run_request import RunRequest
from scopecat.runs.admission import RunSkeleton
from scopecat.runs.refs import CONFIG_PROFILE_SNAPSHOT_REF
from scopecat.runs.repository import (
    RunBytesWrite,
    RunContentPublication,
    RunModelWrite,
    TerminalRunCommit,
)
from tests.testkit.authoring import load_config
from tests.testkit.runtime import SQLiteTestRunRepository


class _Record(BaseModel):
    value: str


class _PortableRecord(BaseModel):
    message: str
    value: float = 0.0


def _repository(root: Path) -> SQLiteTestRunRepository:
    sqlite = SQLiteDatabase(root / "control.sqlite3")
    SQLiteProjectStore(
        sqlite,
        root / "objects",
    ).bootstrap()
    repository = SQLiteTestRunRepository(
        sqlite,
        root / "objects",
    )
    return repository


def _manifest(run_id: str) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        created_at=datetime(2026, 7, 23, tzinfo=UTC),
        config_content_hash=f"sha256:{'0' * 64}",
    )


def _outcome(run_id: str) -> RunOutcome:
    return RunOutcome(
        run_id=run_id,
        result="succeeded",
        certainty="known",
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
        run_id=run_id,
        outcome=_outcome(run_id),
        contents=(_content(content_id),),
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


def _portable_manifest(run_id: str, day: int) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        created_at=datetime(2026, 1, day, tzinfo=UTC),
        config_content_hash="sha256:" + "0" * 64,
        outcome=RunOutcome(
            run_id=run_id,
            result="succeeded",
            certainty="known",
        ),
    )


def _config_source(content_hash: str) -> RunConfigSource:
    return ConfigRegistryRunConfigSource(
        selector="active",
        entry_id="config-entry",
        config_ref="configs/config-entry.json",
        content_hash=content_hash,
        registry_generation=1,
    )


def _structured_run_inputs(
    run_id: str,
    *,
    config: ConfigProfileSnapshot | None = None,
    with_source: bool = True,
) -> RunSkeleton:
    selected_config = load_config() if config is None else config
    content_hash = config_content_hash(selected_config)
    return RunSkeleton(
        manifest=RunManifest(
            run_id=run_id,
            config_content_hash=content_hash,
            config_source=_config_source(content_hash) if with_source else None,
        ),
        request=RunRequest(experiment_id=f"scratch:{run_id}"),
        config=selected_config,
    )


def test_round_trips_all_portable_content(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    run_id = "run-repository-contract"
    manifest = _portable_manifest(run_id, 1)
    record = _PortableRecord(message="record", value=float("inf"))

    repository.write_manifest(manifest)
    repository.write_model(run_id, "records/model.json", record)
    repository.write_text(run_id, "artifacts/note.txt", "note")
    repository.write_bytes(run_id, "artifacts/blob.bin", b"\x00\xff")

    assert repository.read_manifest(run_id) == manifest
    assert (
        repository.read_model(run_id, "records/model.json", _PortableRecord) == record
    )
    assert repository.read_text(run_id, "artifacts/note.txt") == "note\n"
    assert repository.read_bytes(run_id, "artifacts/blob.bin") == b"\x00\xff"
    assert repository.exists(run_id, "records/model.json")
    assert not repository.exists(run_id, "records/missing.json")


def test_lists_runs_by_creation_time(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    repository.write_manifest(_portable_manifest("run-later", 2))
    repository.write_manifest(_portable_manifest("run-earlier", 1))

    assert [manifest.run_id for manifest in repository.list_runs()] == [
        "run-earlier",
        "run-later",
    ]


def test_structured_run_inputs_bind_manifest_source_and_snapshot_hashes(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    skeleton = _structured_run_inputs("run-provenance-round-trip")

    repository.write_run_skeleton(skeleton)
    assert (
        repository.read_config_profile_snapshot(skeleton.manifest.run_id)
        == skeleton.config
    )


def test_terminal_commit_publishes_content_before_merged_manifest(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id = "run-terminal-commit"
    repository.write_manifest(
        RunManifest(
            run_id=run_id,
            config_content_hash="sha256:" + "0" * 64,
            contents=(
                RunContentEntry(
                    role="artifact",
                    id="operator-note",
                    kind="attachment",
                    content_hash="operator-note-content",
                ),
            ),
        )
    )
    outcome = RunOutcome(
        run_id=run_id,
        result="succeeded",
        certainty="known",
    )
    terminal_evidence = RunContentEntry(
        role="record",
        id="terminal-evidence",
        kind="contract_evidence",
        content_hash="terminal-evidence-content",
    )

    committed = repository.commit_terminal(
        TerminalRunCommit(
            run_id=run_id,
            outcome=outcome,
            contents=(terminal_evidence,),
            models=(
                RunModelWrite(
                    ref="records/terminal-evidence.json",
                    value=_PortableRecord(message="terminal"),
                ),
            ),
        )
    )

    assert {entry.id for entry in committed.contents} == {
        "operator-note",
        "terminal-evidence",
    }
    assert repository.read_manifest(run_id) == committed
    assert repository.read_model(
        run_id,
        "records/terminal-evidence.json",
        _PortableRecord,
    ) == _PortableRecord(message="terminal")


def test_content_publication_merges_entries_and_refs(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    run_id = "run-content-publication"
    existing = RunContentEntry(
        role="artifact",
        id="existing",
        kind="attachment",
        content_hash="existing-content",
    )
    published = RunContentEntry(
        role="record",
        id="analysis",
        kind="analysis",
        content_hash="analysis-content",
    )
    repository.write_manifest(
        _portable_manifest(run_id, 1).model_copy(update={"contents": (existing,)})
    )

    manifest = repository.publish_content(
        RunContentPublication(
            run_id=run_id,
            entries=(published,),
            models=(
                RunModelWrite(
                    ref="records/analysis.json",
                    value=_PortableRecord(message="analysis"),
                ),
            ),
            bytes=(
                RunBytesWrite(
                    ref="artifacts/summary.txt",
                    content=b"summary\n",
                ),
            ),
        )
    )

    assert manifest.contents == (existing, published)
    assert repository.read_manifest(run_id) == manifest
    assert repository.read_model(
        run_id,
        "records/analysis.json",
        _PortableRecord,
    ) == _PortableRecord(message="analysis")
    assert repository.read_bytes(run_id, "artifacts/summary.txt") == b"summary\n"


def test_immutable_content_conflict_does_not_partially_publish(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id = "run-content-conflict"
    original = RunContentEntry(
        role="record",
        id="proposal",
        kind="parameter_change_proposal",
        content_hash="original-content",
    )
    repository.write_manifest(_portable_manifest(run_id, 1))
    repository.publish_content(
        RunContentPublication(
            run_id=run_id,
            entries=(original,),
            models=(
                RunModelWrite(
                    ref="records/proposal.json",
                    value=_PortableRecord(message="original"),
                    replace=False,
                ),
            ),
        )
    )
    repository.publish_content(
        RunContentPublication(
            run_id=run_id,
            entries=(original,),
            models=(
                RunModelWrite(
                    ref="records/proposal.json",
                    value=_PortableRecord(message="original"),
                    replace=False,
                ),
            ),
        )
    )
    before = repository.read_manifest(run_id)

    with pytest.raises(Conflict) as captured:
        repository.publish_content(
            RunContentPublication(
                run_id=run_id,
                entries=(
                    RunContentEntry(
                        role="record",
                        id="other",
                        kind="analysis",
                        content_hash="other-content",
                    ),
                ),
                models=(
                    RunModelWrite(
                        ref="records/proposal.json",
                        value=_PortableRecord(message="different"),
                        replace=False,
                    ),
                ),
                bytes=(
                    RunBytesWrite(
                        ref="artifacts/should-not-publish.txt",
                        content=b"uncommitted",
                    ),
                ),
            )
        )

    assert captured.value.problems[0].code == "run.ref_conflict"
    assert repository.read_manifest(run_id) == before
    assert not repository.exists(run_id, "artifacts/should-not-publish.txt")
    assert repository.read_model(
        run_id,
        "records/proposal.json",
        _PortableRecord,
    ) == _PortableRecord(message="original")


def test_duplicate_immutable_refs_conflict_within_one_publication(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run_id = "run-content-duplicate-immutable"
    repository.write_manifest(_portable_manifest(run_id, 1))
    before = repository.read_manifest(run_id)

    with pytest.raises(Conflict) as captured:
        repository.publish_content(
            RunContentPublication(
                run_id=run_id,
                entries=(
                    RunContentEntry(
                        role="record",
                        id="proposal",
                        kind="parameter_change_proposal",
                        content_hash="second-content",
                    ),
                ),
                models=(
                    RunModelWrite(
                        ref="records/proposal.json",
                        value=_PortableRecord(message="first"),
                        replace=False,
                    ),
                    RunModelWrite(
                        ref="records/proposal.json",
                        value=_PortableRecord(message="second"),
                        replace=False,
                    ),
                ),
            )
        )

    assert captured.value.problems[0].code == "run.ref_conflict"
    assert repository.read_manifest(run_id) == before
    assert not repository.exists(run_id, "records/proposal.json")


def test_structured_run_reads_detect_snapshot_drift(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    skeleton = _structured_run_inputs("run-snapshot-drift")
    repository.write_run_skeleton(skeleton)
    drifted = skeleton.config.model_copy(update={"id": "drifted-config"})
    repository.write_model(
        skeleton.manifest.run_id,
        CONFIG_PROFILE_SNAPSHOT_REF,
        drifted,
    )

    with pytest.raises(DataIntegrityError) as captured:
        repository.read_config_profile_snapshot(skeleton.manifest.run_id)
    assert captured.value.problems[0].code == "run.config_provenance_mismatch"


def test_direct_snapshot_run_is_protected_by_its_manifest_hash(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    skeleton = _structured_run_inputs(
        "run-direct-snapshot",
        with_source=False,
    )
    repository.write_run_skeleton(skeleton)
    repository.write_model(
        skeleton.manifest.run_id,
        CONFIG_PROFILE_SNAPSHOT_REF,
        skeleton.config.model_copy(update={"id": "drifted-direct-snapshot"}),
    )

    with pytest.raises(DataIntegrityError) as captured:
        repository.read_config_profile_snapshot(skeleton.manifest.run_id)

    assert captured.value.problems[0].code == "run.config_provenance_mismatch"


def test_config_read_remains_independent_for_capture_runs(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    run_id = "capture-config"
    config = load_config()
    repository.write_model(run_id, CONFIG_PROFILE_SNAPSHOT_REF, config)
    repository.write_manifest(
        RunManifest(
            run_id=run_id,
            config_content_hash=config_content_hash(config),
        )
    )

    assert repository.read_config_profile_snapshot(run_id) == config


def test_missing_run_and_ref_have_stable_errors(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(NotFound) as missing_run:
        repository.read_manifest("run-missing")
    assert missing_run.value.problems[0].code == "run.not_found"

    with pytest.raises(DataIntegrityError) as missing_ref:
        repository.read_text("run-missing", "records/missing.json")
    assert missing_ref.value.problems[0].code == "run.ref_missing"


@pytest.mark.parametrize("ref", ("../outside.json", "/outside.json"))
def test_rejects_refs_outside_run_namespace(tmp_path: Path, ref: str) -> None:
    repository = _repository(tmp_path)

    with pytest.raises(CheckFailed) as captured:
        repository.write_text("run-contract", ref, "escape")
    assert captured.value.problems[0].code == "run.ref_path_escape"


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
                run_id=run_id,
                outcome=_outcome(run_id),
                models=(
                    RunModelWrite(
                        ref="records/terminal-evidence.json",
                        value=_Record(value="terminal"),
                    ),
                ),
            )
        )

    assert repository.read_manifest(run_id).outcome is None
    assert not repository.exists(run_id, "records/terminal-evidence.json")
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

    peer = SQLiteRunRepository(repository.sqlite, repository.objects.root)
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
    prepared_first = repository.prepare_terminal_commit(
        _terminal_commit(run_id, "first")
    )
    prepared_second = repository.prepare_terminal_commit(
        _terminal_commit(run_id, "second")
    )

    with sqlite3.connect(
        repository.database,
        isolation_level=None,
    ) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN IMMEDIATE")
        repository.commit_prepared_terminal_in_transaction(
            connection,
            prepared_first,
        )
        committed = repository.commit_prepared_terminal_in_transaction(
            connection,
            prepared_second,
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

    assert repository.read_manifest(run_id).outcome is None
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
    peer = SQLiteRunRepository(repository.sqlite, repository.objects.root)
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
