from __future__ import annotations

import sqlite3
from functools import partial
from pathlib import Path
from typing import override

import pytest

from scopecat.adapters.sqlite import SQLiteProjectStore
from scopecat.adapters.sqlite.config_registry import SQLiteConfigRegistryStore
from scopecat.adapters.sqlite.run_repository import SQLiteRunRepository
from scopecat.config.profiles import load_config_profile
from scopecat.config.registry.ports import ConfigRegistryUnitOfWorkFactory
from scopecat.config.registry.service import (
    activate_config_registry_entry,
    list_config_registry_entries,
    register_and_activate_config_profile,
    register_config_profile,
    rollback_config_registry,
)
from scopecat.kernel.errors import Conflict, StorageError
from tests.contracts.config_registry_contracts import (
    ConfigRegistryUnitOfWorkContract,
)
from tests.testkit.paths import CORE_FIXTURE_DIR


def _store(tmp_path: Path) -> SQLiteConfigRegistryStore:
    database = tmp_path / "control.sqlite3"
    SQLiteProjectStore(database, tmp_path / "objects").bootstrap()
    runs = SQLiteRunRepository(database, tmp_path / "objects")
    return SQLiteConfigRegistryStore(database, runs=runs)


class TestSQLiteConfigRegistryUnitOfWorkContract(ConfigRegistryUnitOfWorkContract):
    @override
    def make_unit_of_work(self, tmp_path: Path) -> ConfigRegistryUnitOfWorkFactory:
        return _store(tmp_path).unit_of_work


def test_registry_and_run_reads_share_one_database(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.runs.write_text("run-shared", "records/value.txt", "value")
    config = load_config_profile(CORE_FIXTURE_DIR / "config-profile.json")

    register_config_profile(
        config=config,
        unit_of_work=store.unit_of_work,
        entry_id="shared",
        registered_by="test",
    )

    with store.unit_of_work() as work:
        assert work.runs is store.runs
        assert work.runs.read_text("run-shared", "records/value.txt") == "value\n"


def test_registration_and_activation_roll_back_together(tmp_path: Path) -> None:
    store = _store(tmp_path)
    config = load_config_profile(CORE_FIXTURE_DIR / "config-profile.json")
    with sqlite3.connect(store.database) as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_initial_activation
            BEFORE INSERT ON config_registry_active
            BEGIN
                SELECT RAISE(ABORT, 'injected failure');
            END
            """
        )

    with pytest.raises(StorageError):
        register_and_activate_config_profile(
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
    config = load_config_profile(CORE_FIXTURE_DIR / "config-profile.json")
    connection = sqlite3.connect(store.database, isolation_level=None)
    connection.row_factory = sqlite3.Row
    with store.borrowed_unit_of_work(connection) as work:
        assert work.registry.list_entries() == ()
    assert not connection.in_transaction

    connection.execute("BEGIN IMMEDIATE")

    register_config_profile(
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
    config = load_config_profile(CORE_FIXTURE_DIR / "config-profile.json")
    first, _, _ = register_and_activate_config_profile(
        config=config,
        unit_of_work=store.unit_of_work,
        entry_id="first",
        registered_by="test",
        operator="test",
        expected_generation=0,
    )
    register_and_activate_config_profile(
        config=config.model_copy(update={"id": "second-config"}),
        unit_of_work=store.unit_of_work,
        entry_id="second",
        registered_by="test",
        operator="test",
        expected_generation=1,
    )

    state, record = rollback_config_registry(
        unit_of_work=store.unit_of_work,
        operator="test",
        expected_generation=2,
    )

    assert state.generation == 3
    assert state.active_entry_id == first.id
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
    config = load_config_profile(CORE_FIXTURE_DIR / "config-profile.json")
    register_config_profile(
        config=config,
        unit_of_work=store.unit_of_work,
        entry_id="first",
        registered_by="test",
    )
    register_config_profile(
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
