"""SQLite compositions for repository tests."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from scopecat.adapters.sqlite import (
    SQLiteConfigRegistryStore,
    SQLiteControlPlane,
    SQLiteExecutionJournal,
    SQLiteMeasurementDatasetRepository,
    SQLiteProjectStore,
    SQLiteRunRepository,
)
from scopecat.adapters.sqlite.run_repository import _PreparedRef
from scopecat.config.registry.ports import ConfigRegistryUnitOfWorkFactory
from scopecat.execution.ports.instruments import RunInstrumentHost
from scopecat.execution.services import ExecutionSession
from scopecat.project_state import ProjectStateServices
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetHeader,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
)
from scopecat.records.run import RunConfigSource, RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.admission import RunSkeleton, build_run_admission
from scopecat.runs.refs import MANIFEST_REF
from scopecat.runs.repository import RunRepository
from tests.testkit.instrument_host import TestRunInstrumentHost


class SQLiteTestRunRepository(SQLiteRunRepository):
    """Fixture-only low-level writes excluded from the production port."""

    def write_manifest(self, manifest: RunManifest) -> None:
        prepared = self._prepare_model(
            manifest.run_id,
            MANIFEST_REF,
            manifest,
        )
        with self._transaction() as connection:
            self._publish_refs(
                connection,
                manifest.run_id,
                (prepared,),
            )

    def write_run_skeleton(self, skeleton: RunSkeleton) -> None:
        _persist_run_skeleton(self, skeleton)

    def list_runs(self) -> list[RunManifest]:
        return list_test_runs(self)

    def write_model(self, run_id: str, ref: str, model: BaseModel) -> None:
        self._write_fixture_ref(
            run_id,
            self._prepare_model(run_id, ref, model),
        )

    def write_text(self, run_id: str, ref: str, content: str) -> None:
        if content and not content.endswith("\n"):
            content = f"{content}\n"
        self.write_bytes(run_id, ref, content.encode())

    def write_bytes(self, run_id: str, ref: str, content: bytes) -> None:
        self._write_fixture_ref(
            run_id,
            self._prepare_bytes(run_id, ref, content),
        )

    def _write_fixture_ref(self, run_id: str, prepared: _PreparedRef) -> None:
        with self._transaction() as connection:
            self._publish_refs(
                connection,
                run_id,
                (prepared,),
            )


class SQLiteTestExecutionJournal(SQLiteExecutionJournal):
    """Own test transactions and expose durable entries for assertions."""

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        with SQLiteControlPlane(self._runs.database).transaction() as connection:
            committed, _created = self.append_in_transaction(connection, entry)
            return committed

    def entries(self) -> tuple[ExecutionTransition, ...]:
        with sqlite3.connect(self._runs.database) as connection:
            rows = cast(
                "list[tuple[str, int, str]]",
                connection.execute(
                    """
                    SELECT payload_json, run_sequence, occurred_at
                    FROM durable_events
                    WHERE run_id = ?
                      AND kind = 'execution_transition_committed'
                    ORDER BY run_sequence
                    """,
                    (self._run_id,),
                ).fetchall(),
            )
        return tuple(
            ExecutionTransition.model_validate(
                {
                    **json.loads(payload_json),
                    "run_id": self._run_id,
                    "sequence": sequence,
                    "timestamp": occurred_at,
                }
            )
            for payload_json, sequence, occurred_at in rows
        )


class SQLiteTestMeasurementDatasetRepository(SQLiteMeasurementDatasetRepository):
    """Own transactions for in-process execution tests."""

    def initialize(
        self,
        header: MeasurementDatasetHeader,
    ) -> MeasurementDatasetReceipt:
        prepared = self.prepare_header(header)
        with SQLiteControlPlane(self._runs.database).transaction() as connection:
            receipt, _created = self.header_prepared_in_transaction(
                connection,
                prepared,
            )
            return receipt

    def append(self, append: MeasurementDatasetAppend) -> MeasurementDatasetReceipt:
        prepared = self.prepare_append(append)
        with SQLiteControlPlane(self._runs.database).transaction() as connection:
            receipt, _created = self.append_prepared_in_transaction(
                connection,
                prepared,
            )
            return receipt

    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt:
        prepared = self.prepare_seal(seal)
        with SQLiteControlPlane(self._runs.database).transaction() as connection:
            receipt, _created = self.seal_prepared_in_transaction(
                connection,
                prepared,
            )
            return receipt


@dataclass(frozen=True, slots=True)
class SQLiteExecutionSession(ExecutionSession):
    """Concrete SQLite session exposing read models to test assertions."""

    journal: SQLiteTestExecutionJournal
    measurements: SQLiteTestMeasurementDatasetRepository


def admit_test_run(
    *,
    config: ConfigProfileSnapshot,
    request: RunRequest,
    repository: RunRepository,
    config_source: RunConfigSource | None = None,
) -> RunManifest:
    """Persist one accepted run for an in-process test."""

    skeleton = build_run_admission(
        config=config,
        request=request,
        config_source=config_source,
    )
    _persist_run_skeleton(repository, skeleton)
    return skeleton.manifest


def _persist_run_skeleton(
    repository: RunRepository,
    skeleton: RunSkeleton,
) -> None:
    """Persist admission state without adding a test-only repository method."""

    runs = cast("SQLiteRunRepository", repository)
    prepared = runs.prepare_run_skeleton(skeleton)
    with SQLiteControlPlane(runs.database).transaction() as connection:
        runs.commit_run_skeleton_in_transaction(connection, prepared)


def list_test_runs(repository: RunRepository) -> list[RunManifest]:
    """Inspect SQLite manifests for tests that do not own scheduler state."""

    runs = cast("SQLiteRunRepository", repository)
    with sqlite3.connect(runs.database) as connection:
        rows = cast(
            "list[tuple[str]]",
            connection.execute(
                """
                SELECT run_id FROM run_repository_refs
                WHERE ref = ?
                """,
                (MANIFEST_REF,),
            ).fetchall(),
        )
    manifests = [runs.read_manifest(row[0]) for row in rows]
    return sorted(
        manifests, key=lambda manifest: (manifest.created_at, manifest.run_id)
    )


def sqlite_run_repository(project: str | Path) -> SQLiteTestRunRepository:
    """Open an isolated SQLite run repository."""

    database, objects = _sqlite_paths(project)
    SQLiteProjectStore(database, objects).bootstrap()
    repository = SQLiteTestRunRepository(database, objects)
    return repository


def sqlite_config_registry_unit_of_work(
    project: str | Path,
) -> ConfigRegistryUnitOfWorkFactory:
    """Open isolated configuration registry transactions."""

    runs = sqlite_run_repository(project)
    return _config_registry_store(project, runs=runs).unit_of_work


def sqlite_execution_session(
    project: str | Path,
    run_id: str,
    *,
    runs: SQLiteRunRepository | None = None,
    instruments: RunInstrumentHost | None = None,
) -> SQLiteExecutionSession:
    """Bind one run's execution ports to isolated SQLite persistence."""

    selected_runs = sqlite_run_repository(project) if runs is None else runs
    return SQLiteExecutionSession(
        accepted=selected_runs.read_manifest(run_id),
        begin=lambda: None,
        commit_terminal=selected_runs.commit_terminal,
        journal=SQLiteTestExecutionJournal(selected_runs, run_id=run_id),
        measurements=SQLiteTestMeasurementDatasetRepository(
            selected_runs,
            run_id=run_id,
        ),
        instruments=instruments or TestRunInstrumentHost(),
    )


def sqlite_project_services(project: str | Path) -> ProjectStateServices:
    """Bind application ports to isolated SQLite adapters."""

    runs = sqlite_run_repository(project)
    config_registry = _config_registry_store(project, runs=runs)
    return ProjectStateServices(
        runs=runs,
        config_registry=config_registry.unit_of_work,
    )


def _sqlite_paths(project: str | Path) -> tuple[Path, Path]:
    state = Path(project) / ".scopecat-test"
    return state / "control.sqlite3", state / "objects"


def _config_registry_store(
    project: str | Path,
    *,
    runs: SQLiteRunRepository,
) -> SQLiteConfigRegistryStore:
    database, _ = _sqlite_paths(project)
    return SQLiteConfigRegistryStore(database, runs=runs)
