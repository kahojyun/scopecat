"""Configuration registry application service."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from threading import Lock

from scopecat.config.changes import prepare_parameter_change_approval
from scopecat.config.inventory import (
    InstrumentInventoryRekey,
    InstrumentInventoryRemoval,
    InstrumentInventoryRenameRekey,
)
from scopecat.config.registry import service as config_registry_service
from scopecat.config.registry.records import CrossRunCandidateAcceptance
from scopecat.config.registry.service import (
    publish_instrument_inventory_migration_revision,
)
from scopecat.control.models import (
    DurableEventInput,
    InventoryMigrationBlocker,
    ResourceKey,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigActivationHistoryView,
    ConfigDraftPreview,
    ConfigEntryView,
    ConfigRegistryView,
)
from scopecat.daemon.wire import (
    CandidateConfigRevisionSource,
    ConfigActivationReceipt,
    ConfigDraftCommand,
    ConfigEntryActivationCommand,
    ConfigPublishCommand,
    ConfigPublishReceipt,
    ConfigUndoCommand,
    DirectConfigRevisionSource,
    InstrumentInventoryMigrationCommand,
    InstrumentInventoryMigrationReceipt,
    ManualConfigDraftRevisionSource,
)
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
)
from scopecat.project_state import ProjectStateServices
from scopecat.records.config import config_content_hash

from scopecat_server.storage.sqlite.config_registry import SQLiteConfigRegistryStore
from scopecat_server.storage.sqlite.control_plane import SQLiteControlPlane
from scopecat_server.storage.sqlite.run_repository import SQLiteRunRepository

from ..errors import BackendConflict, BackendNotFound
from ..instruments.actors import (
    InstrumentActorConflict,
    InstrumentActorRegistry,
    InstrumentActorShutdown,
)
from .analyses import AnalysisService


class ConfigService:
    """Own config-registry commands and their in-process serialization."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        config_registry: SQLiteConfigRegistryStore,
        runs: SQLiteRunRepository,
        services: ProjectStateServices,
        actors: InstrumentActorRegistry,
        analyses: AnalysisService,
    ) -> None:
        self._control = control
        self._config_registry = config_registry
        self._runs = runs
        self._services = services
        self._actors = actors
        self._analyses = analyses
        self._mutation_lock = Lock()

    def get_config_registry(self) -> ConfigRegistryView:
        with self._config_errors():
            snapshot = config_registry_service.load_config_registry_snapshot(
                unit_of_work=self._config_registry.read_unit_of_work
            )
            return ConfigRegistryView(
                entries=snapshot.entries,
                activation=snapshot.activation,
            )

    def get_config_activation_history(self) -> ConfigActivationHistoryView:
        with self._config_errors():
            return ConfigActivationHistoryView(
                items=config_registry_service.load_config_registry_activation_history(
                    unit_of_work=self._config_registry.read_unit_of_work
                )
            )

    def get_active_config(self) -> ActiveConfigView:
        with self._config_errors():
            snapshot = config_registry_service.load_active_config_registry_snapshot(
                unit_of_work=self._config_registry.read_unit_of_work
            )
            return ActiveConfigView(
                entry=snapshot.entry,
                activation=snapshot.activation,
                config=snapshot.config,
            )

    def get_config_entry(self, entry_id: str) -> ConfigEntryView:
        with self._config_errors():
            snapshot = config_registry_service.load_config_registry_entry_snapshot(
                entry_id=entry_id,
                unit_of_work=self._config_registry.read_unit_of_work,
            )
            return ConfigEntryView(entry=snapshot.entry, config=snapshot.config)

    def publish_config(
        self,
        command: ConfigPublishCommand,
    ) -> ConfigPublishReceipt:
        """Publish one revision; candidate approval shares the same commit."""

        with self._mutation_lock, self._config_errors():
            with self._config_transaction() as transaction:
                connection, services = transaction
                source = command.source
                if isinstance(source, CandidateConfigRevisionSource):
                    if isinstance(source.acceptance, CrossRunCandidateAcceptance):
                        self._analyses.validate_candidate_verification(
                            source.acceptance.decision,
                            source_run_id=source.run_id,
                            proposal_id=source.proposal_id,
                        )
                    prepared = prepare_parameter_change_approval(
                        run_id=source.run_id,
                        selector=source.proposal_id,
                        services=self._services,
                        actor=command.actor,
                        note=command.note,
                    )
                    if prepared.publication is not None:
                        publication = self._runs.prepare_content_publication(
                            prepared.publication
                        )
                        self._runs.publish_prepared_content_in_transaction(
                            connection,
                            publication,
                        )
                        self._control.append_event_in_transaction(
                            connection,
                            DurableEventInput(
                                run_id=source.run_id,
                                kind="parameter_proposal_approved",
                                payload={
                                    "proposal_id": source.proposal_id,
                                    "actor": command.actor,
                                },
                                occurred_at=prepared.approval.approved_at,
                            ),
                        )
                result = config_registry_service.publish_config_revision(
                    revision=_config_revision(command),
                    unit_of_work=services.config_registry,
                    expected_generation=command.expected_generation,
                )
                self._append_revision_events(connection, command, result)
                activation = result.activation
                assert activation is not None
                receipt = ConfigPublishReceipt(
                    entry=result.entry,
                    deltas=result.deltas,
                    activation=activation,
                )
            return receipt

    def migrate_instrument_inventory(
        self,
        command: InstrumentInventoryMigrationCommand,
    ) -> InstrumentInventoryMigrationReceipt:
        """Publish one destructive inventory change after fencing its keys."""

        declared = _inventory_migration_deltas(command)
        with self._mutation_lock, self._config_errors():
            active = config_registry_service.load_active_config_registry_snapshot(
                unit_of_work=self._config_registry.read_unit_of_work
            )
            # Do not retire healthy idle connections for an already-stale intent.
            if active.activation.generation != command.expected_generation:
                raise BackendConflict("config registry active state changed")
            plan = config_registry_service.plan_instrument_inventory_migration(
                current=active.config,
                target=command.config,
                declared=declared,
            )
            try:
                retirement = self._actors.begin_retirement(
                    plan.affected_exclusivity_keys
                )
            except (InstrumentActorConflict, InstrumentActorShutdown) as error:
                raise BackendConflict(str(error)) from error
            with retirement:
                # Known owners should fail before idle connections are disconnected.
                self._require_inventory_migration_drained(
                    plan.affected_exclusivity_keys
                )
                try:
                    retirement.retire_idle()
                except (InstrumentActorConflict, InstrumentActorShutdown) as error:
                    raise BackendConflict(str(error)) from error
                except Exception as error:
                    raise BackendConflict(
                        "instrument connection could not be retired safely"
                    ) from error

                with self._config_transaction() as transaction:
                    connection, services = transaction
                    # Close the claim race after the first drained snapshot.
                    blockers = (
                        self._control.inventory_migration_blockers_in_transaction(
                            connection,
                            tuple(
                                ResourceKey.instrument(key)
                                for key in plan.affected_exclusivity_keys
                            ),
                        )
                    )
                    _require_no_inventory_migration_blockers(blockers)
                    result = publish_instrument_inventory_migration_revision(
                        revision=config_registry_service.ConfigRevision(
                            source=(
                                config_registry_service.DirectConfigRevisionSource(
                                    command.config
                                )
                            ),
                            entry_id=command.entry_id,
                            actor=command.actor,
                            note=command.note,
                        ),
                        declared=declared,
                        unit_of_work=services.config_registry,
                        expected_generation=command.expected_generation,
                    )
                    activation = result.activation
                    assert activation is not None
                    self._append_inventory_migration_events(
                        connection,
                        result,
                        change_count=len(plan.changes),
                    )
                    # Old-snapshot claims still lose the generation CAS, while
                    # new-snapshot owners no longer see an activation-to-gate gap.
                    retirement.release_gate()
                    receipt = InstrumentInventoryMigrationReceipt(
                        entry=result.entry,
                        activation=activation,
                        changes=tuple(
                            _wire_inventory_migration_change(change)
                            for change in plan.changes
                        ),
                    )
                return receipt

    def _require_inventory_migration_drained(
        self,
        exclusivity_keys: tuple[str, ...],
    ) -> None:
        with self._control.read_transaction() as connection:
            blockers = self._control.inventory_migration_blockers_in_transaction(
                connection,
                tuple(ResourceKey.instrument(key) for key in exclusivity_keys),
            )
        _require_no_inventory_migration_blockers(blockers)

    def preview_config_draft(
        self,
        command: ConfigDraftCommand,
    ) -> ConfigDraftPreview:
        with self._config_errors():
            result = config_registry_service.preview_manual_config_draft(
                unit_of_work=self._config_registry.read_unit_of_work,
                base_entry_id=command.base_entry_id,
                base_config_content_hash=command.base_content_hash,
                base_generation=command.base_generation,
                candidate_id=command.candidate_id,
                updates=command.updates,
            )
            candidate = result.check.candidate
            return ConfigDraftPreview(
                valid=result.check.ok,
                base_entry=result.base_entry,
                base_generation=result.base_generation,
                base_content_hash=result.base_entry.content_hash,
                config=candidate,
                result_content_hash=(
                    None if candidate is None else config_content_hash(candidate)
                ),
                deltas=result.check.deltas,
                problems=result.check.problems,
            )

    def activate_config_entry(
        self,
        command: ConfigEntryActivationCommand,
    ) -> ConfigActivationReceipt:
        with self._mutation_lock, self._config_errors():
            with self._config_transaction() as transaction:
                connection, services = transaction
                result = config_registry_service.activate_config_registry_entry(
                    entry_id=command.entry_id,
                    unit_of_work=services.config_registry,
                    actor=command.actor,
                    expected_generation=command.expected_generation,
                    note=command.note,
                )
                activation = result.activation
                assert activation is not None
                if result.activated:
                    self._control.append_event_in_transaction(
                        connection,
                        DurableEventInput(
                            kind="config_activated",
                            payload={
                                "entry_id": activation.entry_id,
                                "generation": activation.generation,
                            },
                            occurred_at=activation.recorded_at,
                        ),
                    )
                receipt = ConfigActivationReceipt(
                    activation=activation,
                )
            return receipt

    def undo_config(
        self,
        command: ConfigUndoCommand,
    ) -> ConfigActivationReceipt:
        with self._mutation_lock, self._config_errors():
            with self._config_transaction() as transaction:
                connection, services = transaction
                result = config_registry_service.undo_config_registry(
                    unit_of_work=services.config_registry,
                    actor=command.actor,
                    expected_generation=command.expected_generation,
                    note=command.note,
                )
                activation = result.activation
                assert activation is not None
                if result.activated:
                    self._control.append_event_in_transaction(
                        connection,
                        DurableEventInput(
                            kind="config_undone",
                            payload={
                                "entry_id": activation.entry_id,
                                "generation": activation.generation,
                            },
                            occurred_at=activation.recorded_at,
                        ),
                    )
                receipt = ConfigActivationReceipt(
                    activation=activation,
                )
            return receipt

    def _append_inventory_migration_events(
        self,
        connection: sqlite3.Connection,
        result: config_registry_service.ConfigRegistryMutationResult,
        *,
        change_count: int,
    ) -> None:
        if result.saved:
            self._control.append_event_in_transaction(
                connection,
                DurableEventInput(
                    kind="config_saved",
                    payload={"entry_id": result.entry.id},
                    occurred_at=result.entry.recorded_at,
                ),
            )
        activation = result.activation
        if result.activated and activation is not None:
            self._control.append_event_in_transaction(
                connection,
                DurableEventInput(
                    kind="instrument_inventory_migrated",
                    payload={
                        "entry_id": result.entry.id,
                        "generation": activation.generation,
                        "change_count": change_count,
                    },
                    occurred_at=activation.recorded_at,
                ),
            )

    def _append_revision_events(
        self,
        connection: sqlite3.Connection,
        command: ConfigPublishCommand,
        result: config_registry_service.ConfigRegistryMutationResult,
    ) -> None:
        source = command.source
        run_id = (
            source.run_id if isinstance(source, CandidateConfigRevisionSource) else None
        )
        if result.saved:
            self._control.append_event_in_transaction(
                connection,
                DurableEventInput(
                    run_id=run_id,
                    kind="config_saved",
                    payload={"entry_id": result.entry.id},
                    occurred_at=result.entry.recorded_at,
                ),
            )
        activation = result.activation
        if result.activated and activation is not None:
            self._control.append_event_in_transaction(
                connection,
                DurableEventInput(
                    run_id=run_id,
                    kind="config_activated",
                    payload={
                        "entry_id": result.entry.id,
                        "generation": activation.generation,
                    },
                    occurred_at=activation.recorded_at,
                ),
            )

    @contextmanager
    def _config_transaction(
        self,
    ) -> Generator[tuple[sqlite3.Connection, ProjectStateServices]]:
        """Commit registry state and replay events through one SQLite writer."""

        with self._control.write_transaction() as connection:
            services = replace(
                self._services,
                config_registry=lambda: self._config_registry.borrowed_unit_of_work(
                    connection
                ),
            )
            yield connection, services

    @contextmanager
    def _config_errors(self) -> Generator[None]:
        try:
            yield
        except NotFound as error:
            raise BackendNotFound(str(error)) from error
        except (CheckFailed, Conflict, DataIntegrityError) as error:
            raise BackendConflict(str(error)) from error


def _config_revision(
    command: ConfigPublishCommand,
) -> config_registry_service.ConfigRevision:
    source = command.source
    if isinstance(source, DirectConfigRevisionSource):
        revision_source = config_registry_service.DirectConfigRevisionSource(
            source.config
        )
    elif isinstance(source, ManualConfigDraftRevisionSource):
        draft = source.draft
        revision_source = config_registry_service.ManualConfigDraftRevisionSource(
            base_entry_id=draft.base_entry_id,
            base_config_content_hash=draft.base_content_hash,
            base_generation=draft.base_generation,
            candidate_id=draft.candidate_id,
            updates=draft.updates,
            expected_result_content_hash=source.expected_result_content_hash,
        )
    else:
        revision_source = config_registry_service.CandidateConfigRevisionSource(
            run_id=source.run_id,
            proposal_id=source.proposal_id,
            acceptance=source.acceptance,
        )
    return config_registry_service.ConfigRevision(
        source=revision_source,
        entry_id=command.entry_id,
        actor=command.actor,
        note=command.note,
    )


def _inventory_migration_deltas(
    command: InstrumentInventoryMigrationCommand,
) -> tuple[config_registry_service.InstrumentInventoryMigrationDelta, ...]:
    changes: list[config_registry_service.InstrumentInventoryMigrationDelta] = []
    for change in command.changes:
        if isinstance(change, InstrumentInventoryRemoval):
            changes.append(
                config_registry_service.InstrumentInventoryMigrationDelta(
                    kind="remove",
                    old_instrument_id=change.instrument_id,
                    old_exclusivity_key=change.exclusivity_key,
                )
            )
        elif isinstance(change, InstrumentInventoryRekey):
            changes.append(
                config_registry_service.InstrumentInventoryMigrationDelta(
                    kind="rekey",
                    old_instrument_id=change.instrument_id,
                    old_exclusivity_key=change.from_exclusivity_key,
                    new_instrument_id=change.instrument_id,
                    new_exclusivity_key=change.to_exclusivity_key,
                )
            )
        else:
            assert isinstance(change, InstrumentInventoryRenameRekey)
            changes.append(
                config_registry_service.InstrumentInventoryMigrationDelta(
                    kind="rename_rekey",
                    old_instrument_id=change.from_instrument_id,
                    old_exclusivity_key=change.from_exclusivity_key,
                    new_instrument_id=change.to_instrument_id,
                    new_exclusivity_key=change.to_exclusivity_key,
                )
            )
    return tuple(changes)


def _wire_inventory_migration_change(
    change: config_registry_service.InstrumentInventoryMigrationDelta,
) -> (
    InstrumentInventoryRemoval
    | InstrumentInventoryRekey
    | InstrumentInventoryRenameRekey
):
    if change.kind == "remove":
        return InstrumentInventoryRemoval(
            instrument_id=change.old_instrument_id,
            exclusivity_key=change.old_exclusivity_key,
        )
    if change.kind == "rekey":
        assert change.new_exclusivity_key is not None
        return InstrumentInventoryRekey(
            instrument_id=change.old_instrument_id,
            from_exclusivity_key=change.old_exclusivity_key,
            to_exclusivity_key=change.new_exclusivity_key,
        )
    assert change.new_instrument_id is not None
    assert change.new_exclusivity_key is not None
    return InstrumentInventoryRenameRekey(
        from_instrument_id=change.old_instrument_id,
        to_instrument_id=change.new_instrument_id,
        from_exclusivity_key=change.old_exclusivity_key,
        to_exclusivity_key=change.new_exclusivity_key,
    )


def _require_no_inventory_migration_blockers(
    blockers: tuple[InventoryMigrationBlocker, ...],
) -> None:
    if not blockers:
        return
    details = ", ".join(
        f"{blocker.owner_kind} {blocker.owner_id} ({blocker.state}) on {blocker.key.id}"
        for blocker in blockers
    )
    raise BackendConflict(
        f"instrument inventory migration requires drained resources: {details}"
    )
