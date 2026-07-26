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
from scopecat.config.registry.records import ConfigRegistryEntry
from scopecat.config.resolution import validate_config_profile
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
    CandidateConfigActivationCommand,
    CandidateConfigActivationReceipt,
    ConfigActivationReceipt,
    ConfigDefaultReceipt,
    ConfigDraftCommand,
    ConfigDraftDefaultCommand,
    ConfigDraftDefaultReceipt,
    ConfigDraftRegistrationCommand,
    ConfigDraftRegistrationReceipt,
    ConfigEntryActivationCommand,
    ConfigRollbackCommand,
    DirectConfigDefaultCommand,
    DirectConfigImportCommand,
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
                active_state=snapshot.active_state,
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
                active_state=snapshot.active_state,
                config=snapshot.config,
            )

    def get_config_entry(self, entry_id: str) -> ConfigEntryView:
        with self._config_errors():
            snapshot = config_registry_service.load_config_registry_entry_snapshot(
                entry_id=entry_id,
                unit_of_work=self._config_registry.unit_of_work,
            )
            return ConfigEntryView(entry=snapshot.entry, config=snapshot.config)

    def import_direct_config(
        self,
        command: DirectConfigImportCommand,
    ) -> ConfigRegistryEntry:
        with (
            self._config_errors(),
            self._config_transaction() as transaction,
        ):
            connection, services = transaction
            existing_entries = config_registry_service.list_config_registry_entries(
                unit_of_work=services.config_registry
            )
            existing_ids = {entry.id for entry in existing_entries}
            config = validate_config_profile(command.config)
            entry = config_registry_service.register_config_profile(
                config=config,
                unit_of_work=services.config_registry,
                entry_id=command.entry_id,
                registered_by=command.registered_by,
                note=command.note,
            )
            if entry.id not in existing_ids:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        kind="config_imported",
                        payload={"entry_id": entry.id},
                        occurred_at=entry.registered_at,
                    ),
                )
            return entry

    def set_direct_config_default(
        self,
        command: DirectConfigDefaultCommand,
    ) -> ConfigDefaultReceipt:
        with (
            self._config_errors(),
            self._config_transaction() as transaction,
        ):
            connection, services = transaction
            existing_entries = config_registry_service.list_config_registry_entries(
                unit_of_work=services.config_registry
            )
            existing_ids = {entry.id for entry in existing_entries}
            previous_generation = (
                config_registry_service.current_config_registry_generation(
                    unit_of_work=services.config_registry
                )
            )
            config = validate_config_profile(command.config)
            if previous_generation > 0 and config_content_hash(
                config_registry_service.load_active_config_registry_config(
                    unit_of_work=services.config_registry
                )
            ) == config_content_hash(config):
                state = config_registry_service.load_active_config_registry_state(
                    unit_of_work=services.config_registry
                )
                entry = config_registry_service.load_active_config_registry_entry(
                    unit_of_work=services.config_registry
                )
                history = (
                    config_registry_service.load_config_registry_activation_history(
                        unit_of_work=services.config_registry
                    )
                )
                return ConfigDefaultReceipt(
                    entry=entry,
                    active_state=state,
                    activation=history[-1],
                )
            reusable = next(
                (
                    entry
                    for entry in reversed(existing_entries)
                    if entry.content_hash == config_content_hash(config)
                ),
                None,
            )
            if reusable is not None:
                state, activation = (
                    config_registry_service.activate_config_registry_entry(
                        entry_id=reusable.id,
                        unit_of_work=services.config_registry,
                        operator=command.operator,
                        expected_generation=command.expected_generation,
                        note=command.note,
                    )
                )
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        kind="config_activated",
                        payload={
                            "entry_id": reusable.id,
                            "generation": state.generation,
                        },
                        occurred_at=activation.recorded_at,
                    ),
                )
                return ConfigDefaultReceipt(
                    entry=reusable,
                    active_state=state,
                    activation=activation,
                )
            entry, state, activation = (
                config_registry_service.register_and_activate_config_profile(
                    config=config,
                    unit_of_work=services.config_registry,
                    entry_id=command.entry_id,
                    registered_by=command.registered_by,
                    operator=command.operator,
                    expected_generation=command.expected_generation,
                    note=command.note,
                )
            )
            if entry.id not in existing_ids:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        kind="config_imported",
                        payload={"entry_id": entry.id},
                        occurred_at=entry.registered_at,
                    ),
                )
            if state.generation != previous_generation:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        kind="config_activated",
                        payload={
                            "entry_id": entry.id,
                            "generation": state.generation,
                        },
                        occurred_at=activation.recorded_at,
                    ),
                )
            return ConfigDefaultReceipt(
                entry=entry,
                active_state=state,
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

    def register_config_draft(
        self,
        command: ConfigDraftRegistrationCommand,
    ) -> ConfigDraftRegistrationReceipt:
        with (
            self._config_errors(),
            self._config_transaction() as transaction,
        ):
            connection, services = transaction
            existing_ids = {
                entry.id
                for entry in config_registry_service.list_config_registry_entries(
                    unit_of_work=services.config_registry
                )
            }
            draft = command.draft
            entry, result = config_registry_service.register_manual_config_draft(
                unit_of_work=services.config_registry,
                base_entry_id=draft.base_entry_id,
                base_config_content_hash=draft.base_content_hash,
                base_generation=draft.base_generation,
                candidate_id=draft.candidate_id,
                updates=draft.updates,
                expected_result_content_hash=command.expected_result_content_hash,
                entry_id=command.entry_id,
                registered_by=command.registered_by,
                note=command.note,
            )
            if entry.id not in existing_ids:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        kind="config_draft_registered",
                        payload={
                            "entry_id": entry.id,
                            "base_entry_id": draft.base_entry_id,
                        },
                        occurred_at=entry.registered_at,
                    ),
                )
            return ConfigDraftRegistrationReceipt(
                entry=entry,
                result_content_hash=entry.content_hash,
                deltas=result.check.deltas,
            )

    def set_config_draft_default(
        self,
        command: ConfigDraftDefaultCommand,
    ) -> ConfigDraftDefaultReceipt:
        with (
            self._config_errors(),
            self._config_transaction() as transaction,
        ):
            connection, services = transaction
            existing_ids = {
                entry.id
                for entry in config_registry_service.list_config_registry_entries(
                    unit_of_work=services.config_registry
                )
            }
            previous_generation = (
                config_registry_service.current_config_registry_generation(
                    unit_of_work=services.config_registry
                )
            )
            registration = command.registration
            draft = registration.draft
            entry, result, state, activation = (
                config_registry_service.register_and_activate_manual_config_draft(
                    unit_of_work=services.config_registry,
                    base_entry_id=draft.base_entry_id,
                    base_config_content_hash=draft.base_content_hash,
                    base_generation=draft.base_generation,
                    candidate_id=draft.candidate_id,
                    updates=draft.updates,
                    expected_result_content_hash=(
                        registration.expected_result_content_hash
                    ),
                    entry_id=registration.entry_id,
                    registered_by=registration.registered_by,
                    operator=command.operator,
                    note=registration.note,
                    activation_note=command.activation_note,
                )
            )
            if entry.id not in existing_ids:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        kind="config_draft_registered",
                        payload={
                            "entry_id": entry.id,
                            "base_entry_id": draft.base_entry_id,
                        },
                        occurred_at=entry.registered_at,
                    ),
                )
            if state.generation != previous_generation:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        kind="config_activated",
                        payload={
                            "entry_id": entry.id,
                            "generation": state.generation,
                        },
                        occurred_at=activation.recorded_at,
                    ),
                )
            return ConfigDraftDefaultReceipt(
                entry=entry,
                result_content_hash=entry.content_hash,
                deltas=result.check.deltas,
                active_state=state,
                activation=activation,
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
            previous_generation = (
                config_registry_service.current_config_registry_generation(
                    unit_of_work=services.config_registry
                )
            )
            state, activation = config_registry_service.activate_config_registry_entry(
                entry_id=command.entry_id,
                unit_of_work=services.config_registry,
                operator=command.operator,
                expected_generation=command.expected_generation,
                note=command.note,
            )
            if state.generation != previous_generation:
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
                active_state=state,
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
            previous_generation = (
                config_registry_service.current_config_registry_generation(
                    unit_of_work=services.config_registry
                )
            )
            state, activation = config_registry_service.rollback_config_registry(
                unit_of_work=services.config_registry,
                operator=command.operator,
                expected_generation=command.expected_generation,
                note=command.note,
            )
            if state.generation != previous_generation:
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
                active_state=state,
                activation=activation,
            )

    def activate_candidate_config(
        self,
        command: CandidateConfigActivationCommand,
    ) -> CandidateConfigActivationReceipt:
        with (
            self._config_errors(),
            self._config_transaction() as transaction,
        ):
            connection, services = transaction
            previous_generation = (
                config_registry_service.current_config_registry_generation(
                    unit_of_work=services.config_registry
                )
            )
            entry, active_state, activation = (
                config_registry_service.register_and_activate_candidate_config(
                    unit_of_work=services.config_registry,
                    entry_id=command.entry_id,
                    registered_by=command.registered_by,
                    run_id=command.run_id,
                    proposal_id=command.proposal_id,
                    operator=command.operator,
                    expected_generation=command.expected_generation,
                    note=command.note,
                    activation_note=command.activation_note,
                )
            )
            if active_state.generation != previous_generation:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        run_id=command.run_id,
                        kind="config_activated",
                        payload={
                            "entry_id": entry.id,
                            "generation": active_state.generation,
                            "source_run_id": command.run_id,
                            "proposal_id": command.proposal_id,
                        },
                        occurred_at=activation.recorded_at,
                    ),
                )
            return CandidateConfigActivationReceipt(
                entry=entry,
                active_state=active_state,
                activation=activation,
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
