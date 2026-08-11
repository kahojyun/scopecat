from __future__ import annotations

import sqlite3
from functools import partial
from pathlib import Path
from typing import cast

import pytest
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.registry.service import (
    ConfigRegistryMutationResult,
    ConfigRegistryUnitOfWorkFactory,
    ConfigRevision,
    DirectConfigRevisionSource,
    activate_config_registry_entry,
    current_config_registry_generation,
    list_config_registry_entries,
    load_active_config_registry_activation,
    load_active_config_registry_snapshot,
    load_config_registry_entry_snapshot,
    load_config_registry_snapshot,
    publish_config_revision,
    resolve_config_registry_config_source,
    undo_config_registry,
)
from scopecat.kernel.errors import Conflict, StorageError
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import ConfigRegistryRunConfigSource
from scopecat_testkit.config_registry import load_config_registry_config
from scopecat_testkit.paths import CORE_FIXTURE_DIR
from scopecat_testkit.server.runtime import SQLiteTestRunRepository

from scopecat_server.storage.sqlite.config_registry import SQLiteConfigRegistryStore
from scopecat_server.storage.sqlite.connection import SQLiteDatabase
from scopecat_server.storage.sqlite.project_store import SQLiteProjectStore


def _publish_direct_revision(
    *,
    config: ConfigProfileSnapshot,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    entry_id: str,
    actor: str,
    expected_generation: int | None = None,
    note: str = "",
) -> ConfigRegistryMutationResult:
    generation = (
        current_config_registry_generation(unit_of_work=unit_of_work)
        if expected_generation is None
        else expected_generation
    )
    return publish_config_revision(
        revision=ConfigRevision(
            source=DirectConfigRevisionSource(config),
            entry_id=entry_id,
            actor=actor,
            note=note,
        ),
        unit_of_work=unit_of_work,
        expected_generation=generation,
    )


def _store(tmp_path: Path) -> SQLiteConfigRegistryStore:
    database = tmp_path / "control.sqlite3"
    sqlite = SQLiteDatabase(database)
    SQLiteProjectStore(sqlite, tmp_path / "objects").bootstrap()
    runs = SQLiteTestRunRepository(sqlite, tmp_path / "objects")
    return SQLiteConfigRegistryStore(sqlite, runs=runs)


def test_publish_is_idempotent_and_round_trips(tmp_path: Path) -> None:
    unit_of_work = _store(tmp_path).write_unit_of_work
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")

    first = _publish_direct_revision(
        config=config,
        unit_of_work=unit_of_work,
        entry_id="contract-entry",
        actor="contract",
        note="same request",
    ).entry
    repeated = _publish_direct_revision(
        config=config.model_copy(deep=True),
        unit_of_work=unit_of_work,
        entry_id="contract-entry",
        actor="contract",
        note="same request",
    ).entry

    assert repeated == first
    assert (
        load_config_registry_config(
            entry_id=first.id,
            unit_of_work=unit_of_work,
        )
        == config
    )
    assert list_config_registry_entries(unit_of_work=unit_of_work) == [first]


def test_duplicate_identity_rejects_different_request(tmp_path: Path) -> None:
    unit_of_work = _store(tmp_path).write_unit_of_work
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    _publish_direct_revision(
        config=config,
        unit_of_work=unit_of_work,
        entry_id="contract-conflict",
        actor="first",
    )

    with pytest.raises(Conflict) as captured:
        _publish_direct_revision(
            config=config,
            unit_of_work=unit_of_work,
            entry_id="contract-conflict",
            actor="different",
        )
    assert captured.value.problems[0].code == "config_registry.duplicate_entry"


def test_activation_uses_generation_cas_and_resolves_source(
    tmp_path: Path,
) -> None:
    unit_of_work = _store(tmp_path).write_unit_of_work
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    result = _publish_direct_revision(
        config=config,
        unit_of_work=unit_of_work,
        entry_id="contract-active",
        actor="contract",
        expected_generation=0,
    )
    entry = result.entry
    activation = result.activation
    assert activation is not None

    assert activation.generation == 1
    assert current_config_registry_generation(unit_of_work=unit_of_work) == 1
    assert (
        load_active_config_registry_activation(unit_of_work=unit_of_work) == activation
    )
    resolved, source = resolve_config_registry_config_source(
        selector="active",
        unit_of_work=unit_of_work,
    )
    assert resolved == config
    assert isinstance(source, ConfigRegistryRunConfigSource)
    assert source.entry_id == entry.id

    with pytest.raises(Conflict) as captured:
        _publish_direct_revision(
            config=config,
            unit_of_work=unit_of_work,
            entry_id="stale-generation",
            actor="contract",
            expected_generation=2,
        )
    assert captured.value.problems[0].code == "config_registry.conflict"

    with pytest.raises(Conflict) as repeated:
        activate_config_registry_entry(
            entry_id=entry.id,
            unit_of_work=unit_of_work,
            actor="contract",
            expected_generation=0,
        )
    assert repeated.value.problems[0].code == "config_registry.conflict"


def test_registry_and_run_reads_share_one_database(tmp_path: Path) -> None:
    store = _store(tmp_path)
    cast("SQLiteTestRunRepository", store.runs).write_text(
        "run-shared",
        "records/value.txt",
        "value",
    )
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")

    _publish_direct_revision(
        config=config,
        unit_of_work=store.write_unit_of_work,
        entry_id="shared",
        actor="test",
    )

    with store.write_unit_of_work() as work:
        assert work.runs is store.runs
        assert work.runs.read_text("run-shared", "records/value.txt") == "value\n"


def test_listing_reads_entry_metadata_without_loading_each_config(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    _publish_direct_revision(
        config=config,
        unit_of_work=store.write_unit_of_work,
        entry_id="first",
        actor="test",
    )
    _publish_direct_revision(
        config=config.model_copy(update={"id": "second"}),
        unit_of_work=store.write_unit_of_work,
        entry_id="second",
        actor="test",
    )
    statements: list[str] = []
    connection = sqlite3.connect(store.database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.set_trace_callback(statements.append)

    entries = list_config_registry_entries(
        unit_of_work=partial(store.borrowed_unit_of_work, connection)
    )

    assert [entry.id for entry in entries] == ["first", "second"]
    entry_reads = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith("SELECT")
        and "config_registry_entries" in statement
    ]
    assert len(entry_reads) == 1
    assert "config_json" not in entry_reads[0]
    connection.close()


def test_aggregate_reads_open_one_unit_of_work(tmp_path: Path) -> None:
    store = _store(tmp_path)
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    _publish_direct_revision(
        config=config,
        unit_of_work=store.write_unit_of_work,
        entry_id="active",
        actor="test",
        expected_generation=0,
    )
    opens = 0

    def counted_unit_of_work():
        nonlocal opens
        opens += 1
        return store.write_unit_of_work()

    registry = load_config_registry_snapshot(unit_of_work=counted_unit_of_work)
    assert opens == 1
    opens = 0
    active = load_active_config_registry_snapshot(unit_of_work=counted_unit_of_work)
    assert opens == 1
    opens = 0
    entry = load_config_registry_entry_snapshot(
        entry_id="active",
        unit_of_work=counted_unit_of_work,
    )
    assert opens == 1
    assert registry.activation == active.activation
    assert active.entry == entry.entry
    assert active.config == entry.config


def test_publish_rolls_back_together(tmp_path: Path) -> None:
    store = _store(tmp_path)
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    with sqlite3.connect(store.database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_initial_activation
            BEFORE INSERT ON config_registry_activations
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END
            """
        )

    with pytest.raises(StorageError):
        _publish_direct_revision(
            config=config,
            unit_of_work=store.write_unit_of_work,
            entry_id="rolled-back",
            actor="test",
            expected_generation=0,
        )

    assert list_config_registry_entries(unit_of_work=store.read_unit_of_work) == []


def test_borrowed_unit_of_work_leaves_transaction_and_connection_owned_by_caller(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    connection = sqlite3.connect(store.database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    with store.borrowed_unit_of_work(connection) as work:
        assert work.registry.list_entries() == ()
    assert not connection.in_transaction

    connection.execute("BEGIN IMMEDIATE")

    _publish_direct_revision(
        config=config,
        unit_of_work=partial(store.borrowed_unit_of_work, connection),
        entry_id="borrowed",
        actor="test",
    )

    assert connection.in_transaction
    assert (
        connection.execute("SELECT COUNT(*) FROM config_registry_entries").fetchone()[0]
        == 1
    )
    connection.rollback()
    assert (
        connection.execute("SELECT COUNT(*) FROM config_registry_entries").fetchone()[0]
        == 0
    )
    connection.close()


def test_borrowed_unit_of_work_only_scopes_registry_access(tmp_path: Path) -> None:
    store = _store(tmp_path)
    connection = sqlite3.connect(store.database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("BEGIN IMMEDIATE")
    work = store.borrowed_unit_of_work(connection)

    with pytest.raises(RuntimeError, match="entered twice"), work:
        assert work.registry.list_entries() == ()
        work.__enter__()

    assert connection.in_transaction
    with pytest.raises(RuntimeError, match="has not been entered"):
        _ = work.registry
    connection.rollback()
    connection.close()


def test_undo_persists_contiguous_activation_generations(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    first = _publish_direct_revision(
        config=config,
        unit_of_work=store.write_unit_of_work,
        entry_id="first",
        actor="test",
        expected_generation=0,
    )
    _publish_direct_revision(
        config=config.model_copy(update={"id": "second-config"}),
        unit_of_work=store.write_unit_of_work,
        entry_id="second",
        actor="test",
        expected_generation=1,
    )

    undo = undo_config_registry(
        unit_of_work=store.write_unit_of_work,
        actor="test",
        expected_generation=2,
    )

    record = undo.activation
    assert record is not None
    assert record.generation == 3
    assert record.entry_id == first.entry.id
    assert record.action == "undo"
    with sqlite3.connect(store.database) as connection:
        generations = [
            row[0]
            for row in connection.execute(
                """
                SELECT generation
                FROM config_registry_activations
                ORDER BY generation
                """
            )
        ]
    assert generations == [1, 2, 3]


def test_generation_cas_is_shared_across_store_instances(tmp_path: Path) -> None:
    store = _store(tmp_path)
    peer = SQLiteConfigRegistryStore(store.sqlite, runs=store.runs)
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    _publish_direct_revision(
        config=config,
        unit_of_work=store.write_unit_of_work,
        entry_id="first",
        actor="test",
    )
    _publish_direct_revision(
        config=config.model_copy(update={"id": "second-config"}),
        unit_of_work=store.write_unit_of_work,
        entry_id="second",
        actor="test",
    )
    activate_config_registry_entry(
        entry_id="first",
        unit_of_work=store.write_unit_of_work,
        actor="first",
        expected_generation=2,
    )

    with pytest.raises(Conflict) as captured:
        activate_config_registry_entry(
            entry_id="second",
            unit_of_work=peer.write_unit_of_work,
            actor="second",
            expected_generation=2,
        )

    assert captured.value.problems[0].code == "config_registry.conflict"
