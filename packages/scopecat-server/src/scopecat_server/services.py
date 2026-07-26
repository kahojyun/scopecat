"""Daemon application services with explicit SQLite state ownership."""

from __future__ import annotations

import logging
import sqlite3
from base64 import b64decode, b64encode
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Literal

from pydantic import JsonValue, RootModel
from scopecat.adapters.sqlite import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    ExecutorLeaseNotHeld,
    SQLiteConfigRegistryStore,
    SQLiteControlPlane,
    SQLiteExecutionJournal,
    SQLiteMeasurementDatasetRepository,
    SQLiteProjectStore,
    SQLiteRunRepository,
)
from scopecat.adapters.sqlite.execution import ExecutionJournalConflict
from scopecat.analysis.service import (
    AnalysisInput,
    AnalysisOutput,
    prepare_analysis,
    prepare_analysis_artifact,
)
from scopecat.application.services import ProjectStateServices
from scopecat.config.candidates import CandidateConfig
from scopecat.config.changes import (
    list_parameter_change_decisions,
    list_parameter_change_proposals,
    load_parameter_change_proposal,
    prepare_parameter_change_decision,
    prepare_parameter_change_review,
)
from scopecat.config.registry import service as config_registry_service
from scopecat.config.registry.records import ConfigRegistryEntry
from scopecat.config.resolution import (
    register_and_activate_candidate_config,
    validate_config_profile,
)
from scopecat.control.models import (
    ControlRun,
    ControlRunState,
    DurableEventInput,
    EventPage,
    RunAdmissionRecord,
)
from scopecat.control.models import (
    ExecutorLease as ControlExecutorLease,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigDraftPreview,
    ConfigEntryView,
    ConfigRegistryView,
    DaemonHealth,
    MeasurementPage,
    ParameterProposalListView,
    ParameterProposalView,
    RunAnalysisListView,
    RunAnalysisView,
    RunArtifactBytesView,
    RunConfigView,
    RunDetail,
    RunRequestView,
    RunResourceView,
    RunSummary,
    RunSummaryPage,
)
from scopecat.daemon.wire import (
    AnalysisArtifactOutputPayload,
    AnalysisOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
    AttentionResolutionReceipt,
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
    ExecutionTransitionAppend,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    MeasurementAppendCommand,
    MeasurementSealCommand,
    ParameterProposalDecisionCommand,
    ParameterProposalReviewCommand,
    RunAdmission,
    RunAttachmentCommand,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
)
from scopecat.kernel.problems import (
    ProblemPhase,
    problem,
)
from scopecat.records.analysis import AnalysisRecord
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement_recording import MeasurementDatasetReceipt
from scopecat.records.parameter_change import ParameterChangeDecisionRecord
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.runs.access import list_records
from scopecat.runs.admission import build_run_admission
from scopecat.runs.attachments import attach_run_artifact
from scopecat.runs.data import (
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.repository import (
    RunModelWrite,
    TerminalRunCommit,
)
from scopecat.runs.service import (
    load_run_request,
    read_run_artifact_bytes,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_measurement_dataset,
    read_run_record_json,
)
from scopecat.runs.terminal import merge_terminal_manifest

from .errors import BackendConflict, BackendNotFound

logger = logging.getLogger(__name__)


class _JsonDocument(RootModel[dict[str, JsonValue]]):
    pass


def _analysis_output(item: AnalysisOutputPayload) -> AnalysisOutput:
    if isinstance(item, AnalysisArtifactOutputPayload):
        content = prepare_analysis_artifact(
            title=item.title,
            kind=item.artifact_kind,
            artifact_id=item.artifact_id,
            filename=item.filename,
            model=None,
            json_content=None,
            text=None,
            content=b64decode(item.content_base64, validate=True),
            path=None,
            media_type=item.media_type,
            metadata=item.artifact_metadata,
        )
    else:
        content = item.content
    return AnalysisOutput(
        kind=item.kind,
        title=item.title,
        content=content,
        metadata=item.metadata,
    )


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
                return ConfigDefaultReceipt(
                    entry=entry,
                    active_state=state,
                    activation=state.history[-1],
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
            candidate = CandidateConfig(
                parameter_proposals=tuple(
                    load_parameter_change_proposal(
                        run_id=command.run_id,
                        selector=proposal_id,
                        services=services,
                    )
                    for proposal_id in command.proposal_ids
                )
            )
            result = register_and_activate_candidate_config(
                candidate=candidate,
                services=services,
                entry_id=command.entry_id,
                registered_by=command.registered_by,
                operator=command.operator,
                note=command.note,
                activation_note=command.activation_note,
                expected_generation=command.expected_generation,
            )
            if result.active_state.generation != previous_generation:
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        run_id=command.run_id,
                        kind="config_activated",
                        payload={
                            "entry_id": result.entry.id,
                            "generation": result.active_state.generation,
                            "source_run_id": command.run_id,
                            "proposal_ids": list(command.proposal_ids),
                        },
                        occurred_at=result.activation.recorded_at,
                    ),
                )
            return CandidateConfigActivationReceipt(
                entry=result.entry,
                active_state=result.active_state,
                activation=result.activation,
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


class RunService:
    """Own run records, analysis content, and read-side queries."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
        services: ProjectStateServices,
    ) -> None:
        self._control = control
        self._runs = runs
        self._services = services

    def list_runs(
        self,
        *,
        limit: int,
        after: int | None,
        before: int | None,
        state: ControlRunState | None,
        latest: bool = False,
    ) -> RunSummaryPage:
        with self._control.transaction() as connection:
            page = self._control.list_runs_in_transaction(
                connection,
                limit=limit,
                after=after,
                before=before,
                state=state,
                latest=latest,
            )
            return RunSummaryPage(
                items=tuple(
                    RunSummary(
                        control=control,
                        manifest=self._runs.read_manifest_in_transaction(
                            connection,
                            control.run_id,
                        ),
                    )
                    for control in page.items
                ),
                next_cursor=page.next_cursor,
                previous_cursor=page.previous_cursor,
            )

    def get_run(self, run_id: str) -> RunDetail:
        try:
            with self._control.transaction() as connection:
                control = self._control.get_run_in_transaction(connection, run_id)
                manifest = self._runs.read_manifest_in_transaction(connection, run_id)
                leases = {
                    (lease.resource.kind, lease.resource.id): lease
                    for lease in self._control.list_resource_leases_in_transaction(
                        connection
                    )
                    if lease.run_id == run_id
                }
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        resources = tuple(
            RunResourceView(
                resource=resource,
                status=(
                    lease.status
                    if (lease := leases.get((resource.kind, resource.id))) is not None
                    else ("released" if control.state == "closed" else "required")
                ),
                expires_at=None if lease is None else lease.expires_at,
            )
            for resource in control.admission.resource_claims
        )
        return RunDetail(
            control=control,
            manifest=manifest,
            resources=resources,
        )

    def get_run_config(self, run_id: str) -> RunConfigView:
        with self._config_errors():
            manifest = self._runs.read_manifest(run_id)
            return RunConfigView(
                run_id=run_id,
                config_content_hash=manifest.config_content_hash,
                config=self._runs.read_config_profile_snapshot(run_id),
            )

    def get_run_request(self, run_id: str) -> RunRequestView:
        with self._config_errors():
            return RunRequestView(
                run_id=run_id,
                request=load_run_request(run_id=run_id, services=self._services),
            )

    def list_run_analyses(self, run_id: str) -> RunAnalysisListView:
        with self._config_errors():
            manifest = self._runs.read_manifest(run_id)
            return RunAnalysisListView(
                run_id=run_id,
                items=tuple(
                    self._run_analysis_view(run_id, record.id)
                    for record in list_records(manifest, kind="analysis")
                ),
            )

    def get_run_analysis(self, run_id: str, selector: str) -> RunAnalysisView:
        with self._config_errors():
            return self._run_analysis_view(run_id, selector)

    def _run_analysis_view(self, run_id: str, selector: str) -> RunAnalysisView:
        result = read_run_record_json(
            run_id=run_id,
            selector=selector,
            expected_kind="analysis",
            services=self._services,
        )
        return RunAnalysisView(
            run_id=run_id,
            entry=result.record,
            analysis=AnalysisRecord.model_validate(result.content),
        )

    def save_run_analysis(
        self,
        run_id: str,
        command: AnalysisSaveCommand,
    ) -> AnalysisSaveReceipt:
        inputs = tuple(
            AnalysisInput(
                target=item.target,
                kind=item.kind,
                role=item.role,
                title=item.title,
                metadata=item.metadata,
            )
            for item in command.inputs
        )
        outputs = tuple(_analysis_output(item) for item in command.outputs)
        proposals = tuple(
            item.content
            for item in command.outputs
            if isinstance(item, AnalysisParameterProposalOutputPayload)
        )
        with self._config_errors():
            prepared = prepare_analysis(
                services=self._services,
                run_id=run_id,
                title=command.title,
                analysis_key=command.analysis_key,
                step_id=command.step_id,
                inputs=inputs,
                outputs=outputs,
                parameter_proposals=proposals,
            )
            publication = self._runs.prepare_content_publication(prepared.publication)
            with self._control.transaction() as connection:
                existing = {
                    entry.id: entry.content_hash
                    for entry in self._runs.read_manifest_in_transaction(
                        connection,
                        run_id,
                    ).records
                }
                self._runs.publish_prepared_content_in_transaction(
                    connection,
                    publication,
                )
                if (
                    existing.get(prepared.saved.record.id)
                    != prepared.saved.record.content_hash
                ):
                    self._control.append_event_in_transaction(
                        connection,
                        DurableEventInput(
                            run_id=run_id,
                            kind="analysis_saved",
                            payload={
                                "analysis_key": prepared.saved.analysis_key,
                                "record_id": prepared.saved.record.id,
                            },
                        ),
                    )
        return AnalysisSaveReceipt(
            record=prepared.saved.record,
            analysis_key=prepared.saved.analysis_key,
            inputs=command.inputs,
            output_artifacts=prepared.saved.output_artifacts,
        )

    def get_run_artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactBytesView:
        with self._config_errors():
            result = read_run_artifact_bytes(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self._services,
            )
            return RunArtifactBytesView(
                run_id=run_id,
                artifact=result.artifact,
                content_base64=b64encode(result.content).decode("ascii"),
            )

    def get_run_artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactTextResult:
        with self._config_errors():
            return read_run_artifact_text(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self._services,
            )

    def get_run_artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactJsonResult:
        with self._config_errors():
            return read_run_artifact_json(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self._services,
            )

    def get_run_record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunRecordJsonResult:
        with self._config_errors():
            return read_run_record_json(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self._services,
            )

    def get_run_dataset_content(
        self,
        run_id: str,
        selector: str,
    ) -> RunMeasurementDatasetResult:
        with self._config_errors():
            return read_run_measurement_dataset(
                run_id=run_id,
                selector=selector,
                services=self._services,
            )

    def attach_run_content(
        self,
        run_id: str,
        command: RunAttachmentCommand,
    ) -> RunContentEntry:
        content = (
            None
            if command.content_base64 is None
            else b64decode(command.content_base64, validate=True)
        )
        with self._config_errors():
            artifact = attach_run_artifact(
                services=self._services,
                run_id=run_id,
                key=command.key,
                kind=command.kind,
                text=command.text,
                content=content,
                filename=command.filename,
                media_type=command.media_type,
                metadata=command.metadata,
            )
        return artifact

    def list_parameter_proposals(self, run_id: str) -> ParameterProposalListView:
        with self._config_errors():
            proposals = list_parameter_change_proposals(
                run_id=run_id,
                services=self._services,
            )
            return ParameterProposalListView(
                run_id=run_id,
                items=tuple(
                    ParameterProposalView(
                        proposal=proposal,
                        decisions=tuple(
                            list_parameter_change_decisions(
                                run_id=run_id,
                                selector=proposal.id,
                                storage=self._runs,
                            )
                        ),
                    )
                    for proposal in proposals
                ),
            )

    def review_parameter_proposal(
        self,
        run_id: str,
        proposal_id: str,
        command: ParameterProposalReviewCommand,
    ) -> ParameterChangeDecisionRecord:
        with self._config_errors():
            prepared = prepare_parameter_change_review(
                run_id=run_id,
                selector=proposal_id,
                services=self._services,
                state=command.decision,
                reviewer=command.reviewer,
                note=command.note,
            )
            publication = self._runs.prepare_content_publication(prepared.publication)
            with self._control.transaction() as connection:
                self._runs.publish_prepared_content_in_transaction(
                    connection,
                    publication,
                )
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        run_id=run_id,
                        kind="parameter_proposal_reviewed",
                        payload={
                            "proposal_id": prepared.decision.proposal_id,
                            "decision": prepared.decision.decision,
                            "event_id": prepared.decision.event_id,
                        },
                        occurred_at=prepared.decision.decided_at,
                    ),
                )
        return prepared.decision

    def decide_parameter_proposal(
        self,
        run_id: str,
        proposal_id: str,
        command: ParameterProposalDecisionCommand,
    ) -> ParameterChangeDecisionRecord:
        with self._config_errors():
            prepared = prepare_parameter_change_decision(
                run_id=run_id,
                selector=proposal_id,
                services=self._services,
                decision=command.decision,
                authority=command.authority,
                note=command.note,
            )
            publication = self._runs.prepare_content_publication(prepared.publication)
            with self._control.transaction() as connection:
                self._runs.publish_prepared_content_in_transaction(
                    connection,
                    publication,
                )
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        run_id=run_id,
                        kind="parameter_proposal_decided",
                        payload={
                            "proposal_id": prepared.decision.proposal_id,
                            "decision": prepared.decision.decision,
                            "authority_kind": prepared.decision.authority.kind,
                            "event_id": prepared.decision.event_id,
                        },
                        occurred_at=prepared.decision.decided_at,
                    ),
                )
        return prepared.decision

    def measurements(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> MeasurementPage:
        with self._config_errors():
            self._runs.read_manifest(run_id)
            records = SQLiteMeasurementDatasetRepository(
                self._runs,
                run_id=run_id,
            ).measurements()
        items = records[offset : offset + limit]
        next_offset = (
            offset + len(items) if offset + len(items) < len(records) else None
        )
        return MeasurementPage(items=items, next_offset=next_offset)

    @contextmanager
    def _config_errors(self) -> Generator[None]:
        try:
            yield
        except NotFound as error:
            raise BackendNotFound(str(error)) from error
        except (CheckFailed, Conflict, DataIntegrityError) as error:
            raise BackendConflict(str(error)) from error

    def list_events(
        self,
        *,
        limit: int,
        after: int | None,
        run_id: str | None,
        latest: bool = False,
    ) -> EventPage:
        return self._control.list_events(
            limit=limit,
            after=after,
            run_id=run_id,
            latest=latest,
        )


class AdmissionService:
    """Own idempotent admission and admitted snapshots."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
    ) -> None:
        self._control = control
        self._runs = runs

    def submit_run(self, submission: RunSubmission) -> RunAdmission:
        skeleton = build_run_admission(
            config=submission.config,
            request=submission.request,
            config_source=submission.config_source,
        )
        admission = RunAdmissionRecord(
            submission_id=submission.submission_id,
            submission_content_hash=submission.intent_content_hash,
            run_id=skeleton.manifest.run_id,
            plan=submission.plan,
            admitted_at=skeleton.manifest.created_at,
        )
        prepared = self._runs.prepare_run_skeleton(skeleton)
        try:
            with self._control.transaction() as connection:
                run = self._control.admit_run_in_transaction(connection, admission)
                if run.run_id == admission.run_id:
                    self._runs.commit_run_skeleton_in_transaction(
                        connection,
                        prepared,
                    )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        return self._wire_admission(run)

    def resolve_attention(
        self,
        run_id: str,
    ) -> AttentionResolutionReceipt:
        run = self._control_run(run_id)
        if run.state != "attention_required":
            raise BackendConflict("run does not require operator attention")
        outcome = RunOutcome(
            run_id=run_id,
            result="failed",
            certainty="indeterminate",
            problems=(
                problem(
                    "daemon.executor_loss_reconciled",
                    "operator reconciled external state after executor loss",
                    phase=ProblemPhase.EXECUTION,
                ),
            ),
        )
        prepared = self._runs.prepare_terminal_commit(
            TerminalRunCommit(run_id=run_id, outcome=outcome)
        )
        try:
            with self._control.transaction() as connection:
                released = self._control.release_run_resources_in_transaction(
                    connection,
                    run_id,
                )
                self._runs.commit_prepared_terminal_in_transaction(
                    connection,
                    prepared,
                )
                self._control.close_run_in_transaction(
                    connection,
                    run_id,
                )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        return AttentionResolutionReceipt(
            run_id=run_id,
            state="closed",
            released_resource_count=released,
        )

    def _control_run(self, run_id: str) -> ControlRun:
        try:
            return self._control.get_run(run_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error

    def _wire_admission(self, run: ControlRun) -> RunAdmission:
        return RunAdmission(
            submission_id=run.admission.submission_id,
            manifest=self._runs.read_manifest(run.run_id),
        )


class ExecutorService:
    """Own executor leases and every fenced durable execution write."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
        lease_ttl: timedelta | None = None,
    ) -> None:
        self._control = control
        self._runs = runs
        self._lease_ttl = lease_ttl or timedelta(seconds=30)
        self._heartbeat_interval_seconds = self._lease_ttl.total_seconds() / 3

    def _control_run(self, run_id: str) -> ControlRun:
        try:
            return self._control.get_run(run_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error

    def start_executor(
        self,
        run_id: str,
        request: ExecutorStartRequest,
    ) -> ExecutorLease:
        return self._start_execution(
            run_id,
            executor_id=request.executor_id,
        )

    def heartbeat_executor(
        self,
        run_id: str,
        heartbeat: ExecutorHeartbeat,
    ) -> ExecutorLease:
        try:
            renewed = self._control.renew_executor_lease(
                run_id,
                heartbeat.lease_id,
                ttl=self._lease_ttl,
            )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        return self._wire_lease(renewed)

    def append_transition(
        self,
        run_id: str,
        command: ExecutionTransitionAppend,
    ) -> ExecutionTransition:
        journal = SQLiteExecutionJournal(self._runs, run_id=run_id)
        with self.fenced_write(
            run_id,
            token=command.lease_id,
        ) as connection:
            transition, created = journal.append_in_transaction(
                connection,
                command.transition,
            )
            if created:
                # The effect ledger owns HTTP retry identity; this is its UI projection.
                self._control.append_event_in_transaction(
                    connection,
                    DurableEventInput(
                        run_id=run_id,
                        kind="execution_transition_committed",
                        payload={
                            "sequence": transition.sequence,
                            "operation_id": transition.operation_id,
                            "stage": transition.stage,
                            "effect": transition.effect,
                            "state": transition.state,
                            "point_index": transition.point_index,
                            "instrument_id": transition.instrument_id,
                            "evidence": transition.evidence,
                        },
                        occurred_at=transition.timestamp,
                    ),
                )
        return transition

    def append_measurements(
        self,
        run_id: str,
        command: MeasurementAppendCommand,
    ) -> MeasurementDatasetReceipt:
        repository = SQLiteMeasurementDatasetRepository(
            self._runs,
            run_id=run_id,
        )
        try:
            prepared = repository.prepare_append(command.append)
        except ExecutionJournalConflict as error:
            raise BackendConflict(
                "measurement command conflicts with durable state"
            ) from error
        with self.fenced_write(
            run_id,
            token=command.lease_id,
        ) as connection:
            receipt, created = repository.append_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self.append_effect_event_in_transaction(
                    connection,
                    run_id,
                    "measurements_appended",
                    command.append.operation_id,
                )
        return receipt

    def seal_measurements(
        self,
        run_id: str,
        command: MeasurementSealCommand,
    ) -> MeasurementDatasetReceipt:
        repository = SQLiteMeasurementDatasetRepository(
            self._runs,
            run_id=run_id,
        )
        try:
            prepared = repository.prepare_seal(command.seal)
        except ExecutionJournalConflict as error:
            raise BackendConflict(
                "measurement command conflicts with durable state"
            ) from error
        with self.fenced_write(
            run_id,
            token=command.lease_id,
        ) as connection:
            receipt, created = repository.seal_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self.append_effect_event_in_transaction(
                    connection,
                    run_id,
                    "measurements_sealed",
                    command.seal.operation_id,
                )
        return receipt

    def commit_terminal(
        self,
        run_id: str,
        command: TerminalRunCommitCommand,
    ) -> RunManifest:
        commit = TerminalRunCommit(
            run_id=run_id,
            outcome=command.outcome,
            contents=command.contents,
            models=tuple(
                RunModelWrite(
                    ref=write.ref,
                    value=_JsonDocument(root=write.value),
                )
                for write in command.models
            ),
        )
        control_run = self._control_run(run_id)
        if control_run.state == "closed":
            manifest = self._runs.read_manifest(run_id)
            if not _matches_terminal_intent(manifest, commit):
                raise BackendConflict("run already has a different terminal outcome")
            return manifest
        try:
            manifest = self.commit_terminal_with_authority(
                run_id,
                token=command.lease_id,
                commit=commit,
            )
        except BackendConflict:
            current = self._control_run(run_id)
            manifest = self._runs.read_manifest(run_id)
            if current.state != "closed" or not _matches_terminal_intent(
                manifest,
                commit,
            ):
                raise
        return manifest

    def _start_execution(
        self,
        run_id: str,
        *,
        executor_id: str,
    ) -> ExecutorLease:
        try:
            with self._control.transaction() as connection:
                current = self._control.get_run_in_transaction(connection, run_id)
                latest_manifest = self._runs.read_manifest_in_transaction(
                    connection,
                    run_id,
                )
                if current.state == "leased":
                    lease = self._control.executor_lease_for_run_in_transaction(
                        connection,
                        run_id,
                    )
                    if (
                        lease is None
                        or lease.expires_at <= datetime.now(tz=UTC)
                        or lease.executor_id != executor_id
                        or latest_manifest.outcome is not None
                    ):
                        raise ControlPlaneConflict(
                            "run is already owned by a different executor intent"
                        )
                    return self._wire_lease(lease)
                if latest_manifest.outcome is not None:
                    raise ControlPlaneConflict(
                        "run manifest is not ready to start execution"
                    )
                lease = self._control.start_execution_in_transaction(
                    connection,
                    run_id,
                    executor_id=executor_id,
                    ttl=self._lease_ttl,
                )
                return self._wire_lease(lease)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error

    def fence_executor(self, run_id: str, token: str) -> str:
        try:
            self._control.validate_executor_lease(
                run_id,
                token=token,
            )
        except ExecutorLeaseNotHeld as error:
            raise BackendConflict(
                "executor lease is absent, stale, or expired"
            ) from error
        return token

    @contextmanager
    def fenced_write(
        self,
        run_id: str,
        *,
        token: str,
    ) -> Generator[sqlite3.Connection]:
        try:
            with self._control.fenced_transaction(
                run_id,
                token=token,
            ) as connection:
                yield connection
        except (
            ControlPlaneConflict,
            ExecutionJournalConflict,
        ) as error:
            raise BackendConflict(
                "executor command conflicts with durable run state"
            ) from error

    def _wire_lease(self, lease: ControlExecutorLease) -> ExecutorLease:
        return ExecutorLease(
            lease_id=lease.token,
            run_id=lease.run_id,
            executor_id=lease.executor_id,
            issued_at=lease.acquired_at,
            expires_at=lease.expires_at,
            heartbeat_interval_seconds=self._heartbeat_interval_seconds,
        )

    def append_effect_event_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        kind: str,
        operation_id: str,
    ) -> None:
        self._control.append_event_in_transaction(
            connection,
            DurableEventInput(
                run_id=run_id,
                kind=kind,
                payload={"operation_id": operation_id},
            ),
        )

    def commit_terminal_with_authority(
        self,
        run_id: str,
        *,
        token: str,
        commit: TerminalRunCommit,
    ) -> RunManifest:
        prepared = self._runs.prepare_terminal_commit(commit)
        with self.fenced_write(
            run_id,
            token=token,
        ) as connection:
            manifest = self._runs.commit_prepared_terminal_in_transaction(
                connection,
                prepared,
            )
            self._control.close_run_in_transaction(
                connection,
                run_id,
                executor_token=token,
            )
            return manifest


def _matches_terminal_intent(
    current: RunManifest,
    commit: TerminalRunCommit,
) -> bool:
    if current.outcome != commit.outcome:
        return False
    try:
        return (
            merge_terminal_manifest(
                current,
                run_id=commit.run_id,
                outcome=commit.outcome,
                contents=commit.contents,
            )
            == current
        )
    except ValueError:
        return False


class ExecutorLeaseSupervisor:
    """Expire abandoned executor leases and reconcile daemon restarts."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        supervisor_interval_seconds: float = 0.5,
    ) -> None:
        self._control = control
        self._supervisor_interval_seconds = supervisor_interval_seconds
        self._stop = Event()
        self._supervisor_failed = False
        self._supervisor: Thread | None = None

    @property
    def healthy(self) -> bool:
        supervisor = self._supervisor
        return (
            supervisor is not None
            and supervisor.is_alive()
            and not self._supervisor_failed
        )

    def start(self) -> None:
        if self._supervisor is not None:
            raise RuntimeError("executor lease supervisor already started")
        self._stop.clear()
        self._supervisor_failed = False
        self._reconcile_startup()
        supervisor = Thread(
            target=self._supervise,
            name="scopecat-executor-leases",
            daemon=True,
        )
        self._supervisor = supervisor
        try:
            supervisor.start()
        except BaseException:
            self._supervisor = None
            raise

    def close(self) -> None:
        supervisor = self._supervisor
        self._stop.set()
        if supervisor is not None:
            supervisor.join()
        self._supervisor = None

    def _supervise(self) -> None:
        while not self._stop.wait(self._supervisor_interval_seconds):
            try:
                self._control.expire_executor_leases()
            except Exception:
                self._supervisor_failed = True
                logger.exception("executor lease supervisor iteration failed")

    def _reconcile_startup(self) -> None:
        self._control.abandon_executor_leases()


class DaemonApplication:
    """Composition root exposing narrow services to the transport."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        project_id: str,
        project_store: SQLiteProjectStore,
        config: ConfigService,
        runs: RunService,
        admission: AdmissionService,
        executor: ExecutorService,
        lease_supervisor: ExecutorLeaseSupervisor,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.project_id = project_id
        self._project_store = project_store
        self.config = config
        self.runs = runs
        self._admission = admission
        self.executor = executor
        self._lease_supervisor = lease_supervisor

    def start(self) -> None:
        self._lease_supervisor.start()

    def close(self) -> None:
        self._lease_supervisor.close()

    def health(self) -> DaemonHealth:
        try:
            self._project_store.schema_version()
        except Exception:
            status: Literal["ok", "degraded"] = "degraded"
        else:
            status = "ok" if self._lease_supervisor.healthy else "degraded"
        return DaemonHealth(
            status=status,
            project_id=self.project_id,
            project_name=self.project_root.name,
            project_root=str(self.project_root),
        )

    def submit_run(self, submission: RunSubmission) -> RunAdmission:
        return self._admission.submit_run(submission)

    def resolve_attention(
        self,
        run_id: str,
    ) -> AttentionResolutionReceipt:
        return self._admission.resolve_attention(run_id)


__all__ = [
    "AdmissionService",
    "ConfigService",
    "DaemonApplication",
    "ExecutorLeaseSupervisor",
    "ExecutorService",
    "RunService",
]
