"""Configuration registry application service."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace

from scopecat.adapters.sqlite import (
    SQLiteConfigRegistryStore,
    SQLiteControlPlane,
    SQLiteRunRepository,
)
from scopecat.config.changes import prepare_parameter_change_approval
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
    ConfigPublishCommand,
    ConfigPublishReceipt,
    ConfigUndoCommand,
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
        runs: SQLiteRunRepository,
        services: ProjectStateServices,
    ) -> None:
        self._control = control
        self._config_registry = config_registry
        self._runs = runs
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

    def publish_config(
        self,
        command: ConfigPublishCommand,
    ) -> ConfigPublishReceipt:
        """Publish one revision; candidate approval shares the same commit."""

        with self._config_errors():
            with self._config_transaction() as transaction:
                connection, services = transaction
                source = command.source
                if isinstance(source, CandidateConfigRevisionSource):
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
        with self._config_errors():
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
        with self._config_errors():
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
        )
    return config_registry_service.ConfigRevision(
        source=revision_source,
        entry_id=command.entry_id,
        actor=command.actor,
        note=command.note,
    )
