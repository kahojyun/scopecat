"""Configuration registry application service."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace

from scopecat.adapters.sqlite import (
    SQLiteConfigRegistryStore,
    SQLiteControlPlane,
)
from scopecat.config.registry import service as config_registry_service
from scopecat.control.models import (
    DurableEventInput,
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
    ConfigRevisionDefaultCommand,
    ConfigRevisionDefaultReceipt,
    ConfigRevisionRegistrationCommand,
    ConfigRevisionRegistrationReceipt,
    ConfigRollbackCommand,
    DirectConfigRevisionSource,
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

from .errors import BackendConflict, BackendNotFound


class ConfigService:
    """Own config-registry commands and their in-process serialization."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        config_registry: SQLiteConfigRegistryStore,
        services: ProjectStateServices,
    ) -> None:
        self._control = control
        self._config_registry = config_registry
        self._services = services

    def get_config_registry(self) -> ConfigRegistryView:
        with self._config_errors():
            snapshot = config_registry_service.load_config_registry_snapshot(
                unit_of_work=self._config_registry.unit_of_work
            )
            return ConfigRegistryView(
                entries=snapshot.entries,
                activation=snapshot.activation,
            )

    def get_config_activation_history(self) -> ConfigActivationHistoryView:
        with self._config_errors():
            return ConfigActivationHistoryView(
                items=config_registry_service.load_config_registry_activation_history(
                    unit_of_work=self._config_registry.unit_of_work
                )
            )

    def get_active_config(self) -> ActiveConfigView:
        with self._config_errors():
            snapshot = config_registry_service.load_active_config_registry_snapshot(
                unit_of_work=self._config_registry.unit_of_work
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
                unit_of_work=self._config_registry.unit_of_work,
            )
            return ConfigEntryView(entry=snapshot.entry, config=snapshot.config)

    def register_config_revision(
        self,
        command: ConfigRevisionRegistrationCommand,
    ) -> ConfigRevisionRegistrationReceipt:
        with (
            self._config_errors(),
            self._config_transaction() as transaction,
        ):
            connection, services = transaction
            result = config_registry_service.register_config_revision(
                registration=_revision_registration(command),
                unit_of_work=services.config_registry,
            )
            self._append_revision_events(connection, command, result)
            return ConfigRevisionRegistrationReceipt(
                entry=result.entry,
                deltas=result.deltas,
            )

    def set_config_default(
        self,
        command: ConfigRevisionDefaultCommand,
    ) -> ConfigRevisionDefaultReceipt:
        with (
            self._config_errors(),
            self._config_transaction() as transaction,
        ):
            connection, services = transaction
            result = config_registry_service.register_and_activate_config_revision(
                registration=_revision_registration(command.registration),
                unit_of_work=services.config_registry,
                operator=command.operator,
                expected_generation=command.expected_generation,
                activation_note=command.activation_note,
            )
            self._append_revision_events(connection, command.registration, result)
            activation = result.activation
            assert activation is not None
            return ConfigRevisionDefaultReceipt(
                entry=result.entry,
                deltas=result.deltas,
                activation=activation,
            )

    def preview_config_draft(
        self,
        command: ConfigDraftCommand,
    ) -> ConfigDraftPreview:
        with self._config_errors():
            result = config_registry_service.preview_manual_config_draft(
                unit_of_work=self._config_registry.unit_of_work,
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
        with (
            self._config_errors(),
            self._config_transaction() as transaction,
        ):
            connection, services = transaction
            result = config_registry_service.activate_config_registry_entry(
                entry_id=command.entry_id,
                unit_of_work=services.config_registry,
                operator=command.operator,
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
            return ConfigActivationReceipt(
                activation=activation,
            )

    def rollback_config(
        self,
        command: ConfigRollbackCommand,
    ) -> ConfigActivationReceipt:
        with (
            self._config_errors(),
            self._config_transaction() as transaction,
        ):
            connection, services = transaction
            result = config_registry_service.rollback_config_registry(
                unit_of_work=services.config_registry,
                operator=command.operator,
                expected_generation=command.expected_generation,
                note=command.note,
            )
            activation = result.activation
            assert activation is not None
            if result.activated:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        kind="config_rolled_back",
                        payload={
                            "entry_id": activation.entry_id,
                            "generation": activation.generation,
                        },
                        occurred_at=activation.recorded_at,
                    ),
                )
            return ConfigActivationReceipt(
                activation=activation,
            )

    def _append_revision_events(
        self,
        connection: sqlite3.Connection,
        command: ConfigRevisionRegistrationCommand,
        result: config_registry_service.ConfigRegistryMutationResult,
    ) -> None:
        source = command.source
        run_id = (
            source.run_id if isinstance(source, CandidateConfigRevisionSource) else None
        )
        if result.registered:
            self._control.append_event_in_transaction(
                connection,
                DurableEventInput(
                    run_id=run_id,
                    kind="config_registered",
                    payload={"entry_id": result.entry.id},
                    occurred_at=result.entry.registered_at,
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

        with self._control.transaction() as connection:
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


def _revision_registration(
    command: ConfigRevisionRegistrationCommand,
) -> config_registry_service.ConfigRevisionRegistration:
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
        )
    return config_registry_service.ConfigRevisionRegistration(
        source=revision_source,
        entry_id=command.entry_id,
        registered_by=command.registered_by,
        note=command.note,
    )
