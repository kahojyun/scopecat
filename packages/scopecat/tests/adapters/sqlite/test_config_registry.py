from __future__ import annotations

import sqlite3
from functools import partial
from pathlib import Path
from typing import cast

import pytest

from scopecat.adapters.sqlite import SQLiteProjectStore
from scopecat.adapters.sqlite.config_registry import SQLiteConfigRegistryStore
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.registry.service import (
    ConfigRegistryMutationResult,
    ConfigRegistryUnitOfWorkFactory,
    ConfigRevisionRegistration,
    DirectConfigRevisionSource,
    activate_config_registry_entry,
    current_config_registry_generation,
    list_config_registry_entries,
    load_active_config_registry_activation,
    load_active_config_registry_snapshot,
    load_config_registry_entry_snapshot,
    load_config_registry_snapshot,
    register_and_activate_config_revision,
    register_config_revision,
    resolve_config_registry_config_source,
    rollback_config_registry,
)
from scopecat.kernel.errors import Conflict, StorageError
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import ConfigRegistryRunConfigSource
from tests.testkit.config_registry import load_config_registry_config
from tests.testkit.paths import CORE_FIXTURE_DIR
from tests.testkit.runtime import SQLiteTestRunRepository


def _register_direct_revision(
    *,
    config: ConfigProfileSnapshot,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    entry_id: str,
    registered_by: str,
    note: str = "",
) -> ConfigRegistryMutationResult:
    return register_config_revision(
        registration=ConfigRevisionRegistration(
            source=DirectConfigRevisionSource(config),
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        ),
        unit_of_work=unit_of_work,
    )


def _register_and_activate_direct_revision(
    *,
    config: ConfigProfileSnapshot,
    unit_of_work: ConfigRegistryUnitOfWorkFactory,
    entry_id: str,
    registered_by: str,
    operator: str,
    expected_generation: int,
    note: str = "",
) -> ConfigRegistryMutationResult:
    return register_and_activate_config_revision(
        registration=ConfigRevisionRegistration(
            source=DirectConfigRevisionSource(config),
            entry_id=entry_id,
            registered_by=registered_by,
            note=note,
        ),
        unit_of_work=unit_of_work,
        operator=operator,
        expected_generation=expected_generation,
    )


def _store(tmp_path: Path) -> SQLiteConfigRegistryStore:
    database = tmp_path / "control.sqlite3"
    SQLiteProjectStore(database, tmp_path / "objects").bootstrap()
    runs = SQLiteTestRunRepository(database, tmp_path / "objects")
    return SQLiteConfigRegistryStore(database, runs=runs)


def test_registration_is_idempotent_and_round_trips(tmp_path: Path) -> None:
    unit_of_work = _store(tmp_path).unit_of_work
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")

    first = _register_direct_revision(
        config=config,
        unit_of_work=unit_of_work,
        entry_id="contract-entry",
        registered_by="contract",
        note="same request",
    ).entry
    repeated = _register_direct_revision(
        config=config.model_copy(deep=True),
        unit_of_work=unit_of_work,
        entry_id="contract-entry",
        registered_by="contract",
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
    unit_of_work = _store(tmp_path).unit_of_work
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    _register_direct_revision(
        config=config,
        unit_of_work=unit_of_work,
        entry_id="contract-conflict",
        registered_by="first",
    )

    with pytest.raises(Conflict) as captured:
        _register_direct_revision(
            config=config,
            unit_of_work=unit_of_work,
            entry_id="contract-conflict",
            registered_by="different",
        )
    assert captured.value.problems[0].code == "config_registry.duplicate_entry"


def test_activation_uses_generation_cas_and_resolves_source(
    tmp_path: Path,
) -> None:
    unit_of_work = _store(tmp_path).unit_of_work
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    result = _register_and_activate_direct_revision(
        config=config,
        unit_of_work=unit_of_work,
        entry_id="contract-active",
        registered_by="contract",
        operator="contract",
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
        _register_and_activate_direct_revision(
            config=config,
            unit_of_work=unit_of_work,
            entry_id="stale-generation",
            registered_by="contract",
            operator="contract",
            expected_generation=0,
        )
    assert captured.value.problems[0].code == "config_registry.conflict"

    with pytest.raises(Conflict) as repeated:
        activate_config_registry_entry(
            entry_id=entry.id,
            unit_of_work=unit_of_work,
            operator="contract",
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

    _register_direct_revision(
        config=config,
        unit_of_work=store.unit_of_work,
        entry_id="shared",
        registered_by="test",
    )

    with store.unit_of_work() as work:
        assert work.runs is store.runs
        assert work.runs.read_text("run-shared", "records/value.txt") == "value\n"


def test_listing_reads_entry_metadata_without_loading_each_config(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    _register_direct_revision(
        config=config,
        unit_of_work=store.unit_of_work,
        entry_id="first",
        registered_by="test",
    )
    _register_direct_revision(
        config=config.model_copy(update={"id": "second"}),
        unit_of_work=store.unit_of_work,
        entry_id="second",
        registered_by="test",
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
    _register_and_activate_direct_revision(
        config=config,
        unit_of_work=store.unit_of_work,
        entry_id="active",
        registered_by="test",
        operator="test",
        expected_generation=0,
    )
    opens = 0

    def counted_unit_of_work():
        nonlocal opens
        opens += 1
        return store.unit_of_work()

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


def test_registration_and_activation_roll_back_together(tmp_path: Path) -> None:
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
        _register_and_activate_direct_revision(
            config=config,
            unit_of_work=store.unit_of_work,
            entry_id="rolled-back",
            registered_by="test",
            operator="test",
            expected_generation=0,
        )

    assert list_config_registry_entries(unit_of_work=store.unit_of_work) == []


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

    _register_direct_revision(
        config=config,
        unit_of_work=partial(store.borrowed_unit_of_work, connection),
        entry_id="borrowed",
        registered_by="test",
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


def test_rollback_persists_contiguous_activation_generations(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    first = _register_and_activate_direct_revision(
        config=config,
        unit_of_work=store.unit_of_work,
        entry_id="first",
        registered_by="test",
        operator="test",
        expected_generation=0,
    )
    _register_and_activate_direct_revision(
        config=config.model_copy(update={"id": "second-config"}),
        unit_of_work=store.unit_of_work,
        entry_id="second",
        registered_by="test",
        operator="test",
        expected_generation=1,
    )

    rollback = rollback_config_registry(
        unit_of_work=store.unit_of_work,
        operator="test",
        expected_generation=2,
    )

    record = rollback.activation
    assert record is not None
    assert record.generation == 3
    assert record.entry_id == first.entry.id
    assert record.action == "rollback"
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
    peer = SQLiteConfigRegistryStore(store.database, runs=store.runs)
    config = load_config_snapshot_document(CORE_FIXTURE_DIR / "config-snapshot.json")
    _register_direct_revision(
        config=config,
        unit_of_work=store.unit_of_work,
        entry_id="first",
        registered_by="test",
    )
    _register_direct_revision(
        config=config.model_copy(update={"id": "second-config"}),
        unit_of_work=store.unit_of_work,
        entry_id="second",
        registered_by="test",
    )
    activate_config_registry_entry(
        entry_id="first",
        unit_of_work=store.unit_of_work,
        operator="first",
        expected_generation=0,
    )

    with pytest.raises(Conflict) as captured:
        activate_config_registry_entry(
            entry_id="second",
            unit_of_work=peer.unit_of_work,
            operator="second",
            expected_generation=0,
        )

    assert captured.value.problems[0].code == "config_registry.conflict"
