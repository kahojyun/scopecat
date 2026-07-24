"""Concrete SQLite application service for one daemon-owned project."""

from __future__ import annotations

import logging
import sqlite3
from base64 import b64decode, b64encode
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Literal, cast

from pydantic import JsonValue, RootModel, TypeAdapter
from pydantic_core import to_jsonable_python
from scopecat.adapters.sqlite import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    ExecutorLeaseNotHeld,
    SQLiteCollectionRecordRepository,
    SQLiteConfigRegistryStore,
    SQLiteControlPlane,
    SQLiteExecutionJournal,
    SQLiteMeasurementDatasetRepository,
    SQLitePayloadEvidenceCommitter,
    SQLiteRunRepository,
)
from scopecat.adapters.sqlite.execution import ExecutionJournalConflict
from scopecat.analysis.service import (
    AnalysisInput,
    AnalysisOutput,
    prepare_encoded_analysis_artifact,
    save_analysis,
)
from scopecat.application.services import WorkspaceServices
from scopecat.config.candidates import CandidateConfig
from scopecat.config.changes import (
    list_parameter_change_decisions,
    list_parameter_change_proposals,
    load_parameter_change_proposal,
    review_parameter_change_proposal,
)
from scopecat.config.parameter_updates import (
    ParameterUpdate,
    ReplaceParameter,
    delete_parameter_rows,
    insert_parameter_rows,
    update_parameter_rows,
)
from scopecat.config.registry import service as config_registry_service
from scopecat.config.resolution import (
    register_and_activate_candidate_config,
    resolve_experiment_config,
    validate_config_profile,
)
from scopecat.control.models import (
    ControlRun,
    ControlRunState,
    DurableEventInput,
    EventPage,
    ResourceKey,
    RunAdmissionRecord,
    RunPage,
)
from scopecat.control.models import (
    ExecutorLease as ControlExecutorLease,
)
from scopecat.daemon.catalog import RegisteredExperimentCatalog
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
    RunArtifactJsonView,
    RunArtifactTextView,
    RunConfigView,
    RunDatasetContentView,
    RunDetail,
    RunRecordJsonView,
    RunRequestView,
    RunResourceView,
)
from scopecat.daemon.wire import (
    AnalysisArtifactOutputPayload,
    AnalysisOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
    AttentionResolutionCommand,
    AttentionResolutionReceipt,
    CandidateConfigActivationCommand,
    CandidateConfigActivationReceipt,
    CollectionCommitCommand,
    CollectionCommitReceipt,
    CollectionResolveCommand,
    CollectionResolveReceipt,
    ConfigActivationReceipt,
    ConfigDraftCommand,
    ConfigDraftRegistrationCommand,
    ConfigDraftRegistrationReceipt,
    ConfigEntryActivationCommand,
    ConfigImportReceipt,
    ConfigRollbackCommand,
    DelegatedPlanSummary,
    DelegatedRunSubmission,
    DeleteConfigParameterRows,
    DirectConfigImportCommand,
    ExecutionRecoveryRequest,
    ExecutionRecoverySnapshot,
    ExecutionTransitionBatch,
    ExecutionTransitionBatchReceipt,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    ExperimentCatalog,
    InsertConfigParameterRows,
    ManagedRunSubmission,
    MeasurementAppendCommand,
    MeasurementAppendReceipt,
    MeasurementSealCommand,
    MeasurementSealReceipt,
    ParameterProposalReviewCommand,
    ParameterProposalReviewReceipt,
    PayloadCommitCommand,
    PayloadCommitReceipt,
    ReplaceConfigParameter,
    ResourceClaimDescriptor,
    RunAdmission,
    RunAttachmentCommand,
    RunAttachmentReceipt,
    RunSubmission,
    TerminalRunCommitCommand,
    TerminalRunCommitReceipt,
    UpdateConfigParameterRows,
)
from scopecat.execution.evidence import run_outcome_ref
from scopecat.execution.interpreter import execute_running_run
from scopecat.execution.observation import RuntimeEvent
from scopecat.execution.ports.resources import ResourceLeaseManager
from scopecat.execution.services import ExecutionServices
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
    RunFailed,
    RunIndeterminate,
)
from scopecat.kernel.ids import new_run_id
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
)
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.measurements.results import MeasurementRecord
from scopecat.planning.system import (
    ExperimentSystemBuilder,
    build_experiment_system,
)
from scopecat.records.analysis import AnalysisRecord
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.execution_journal import (
    CollectionChunk,
    CollectionChunkReceipt,
    CommittedPayloadEvidence,
    ExecutionTransition,
    PayloadEvidence,
)
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetAppendIndex,
    MeasurementDatasetReceipt,
    MeasurementDatasetSeal,
)
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.records.run_request import RunRequest
from scopecat.runs.access import list_records, require_dataset
from scopecat.runs.attachments import attach_run_artifact
from scopecat.runs.repository import (
    RunModelWrite,
    RunRecordSetWrite,
    TerminalRunCommit,
)
from scopecat.runs.service import (
    PlannedRun,
    load_run_request,
    plan_experiment,
    read_run_artifact_bytes,
    read_run_artifact_json,
    read_run_artifact_text,
    read_run_data_array,
    read_run_data_table,
    read_run_measurement_dataset,
    read_run_record_json,
)

from .errors import BackendConflict, BackendNotFound

_JSON_OBJECT = TypeAdapter(dict[str, JsonValue])
logger = logging.getLogger(__name__)


class _JsonDocument(RootModel[dict[str, JsonValue]]):
    pass


def _analysis_output(item: AnalysisOutputPayload) -> AnalysisOutput:
    if isinstance(item, AnalysisArtifactOutputPayload):
        content = prepare_encoded_analysis_artifact(
            title=item.title,
            kind=item.artifact_kind,
            artifact_id=item.artifact_id,
            filename=item.filename,
            content=b64decode(item.content_base64, validate=True),
            media_type=item.media_type,
            metadata=item.artifact_metadata,
            source_default_filename=item.source_default_filename,
            source_default_extension=item.source_default_extension,
            source_default_media_type=item.source_default_media_type,
            source_content_hash=item.source_content_hash,
        )
    else:
        content = item.content
    return AnalysisOutput(
        kind=item.kind,
        title=item.title,
        content=content,
        metadata=item.metadata,
    )


def _config_parameter_update(
    item: (
        ReplaceConfigParameter
        | UpdateConfigParameterRows
        | InsertConfigParameterRows
        | DeleteConfigParameterRows
    ),
) -> ParameterUpdate:
    if isinstance(item, ReplaceConfigParameter):
        return ReplaceParameter(value=item.value)
    if isinstance(item, UpdateConfigParameterRows):
        return update_parameter_rows(
            item.parameter_id,
            key=item.key,
            values=item.values,
        )
    if isinstance(item, InsertConfigParameterRows):
        return insert_parameter_rows(item.parameter_id, item.rows)
    return delete_parameter_rows(item.parameter_id, key=item.key)


class SQLiteDaemonBackend:
    """Single-process scheduler and execution boundary over shared SQLite state."""

    def __init__(
        self,
        *,
        project_root: str | Path,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
        config_registry: SQLiteConfigRegistryStore,
        catalog: RegisteredExperimentCatalog | None = None,
        build_system: ExperimentSystemBuilder | None = None,
        lease_ttl: timedelta | None = None,
        supervisor_interval_seconds: float = 0.5,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.control = control
        self.runs = runs
        self.config_registry = config_registry
        self._catalog = catalog or RegisteredExperimentCatalog()
        self._build_system = build_system
        self._lease_ttl = lease_ttl or timedelta(seconds=30)
        self._heartbeat_interval_seconds = self._lease_ttl.total_seconds() / 3
        self._supervisor_interval_seconds = supervisor_interval_seconds
        self._config_lock = Lock()
        self._run_content_lock = Lock()
        self._submission_lock = Lock()
        self._managed_lock = Lock()
        self._managed_plans: dict[str, PlannedRun] = {}
        self._managed_active: set[str] = set()
        self._stop = Event()
        self._supervisor_failed = False
        self._workers = ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="scopecat-run",
        )
        self.services = WorkspaceServices(
            runs=runs,
            execution=self._execution_services(_UnavailableResources()),
            config_registry=config_registry.unit_of_work,
        )
        self._reconcile_startup()
        self._supervisor = Thread(
            target=self._supervise,
            name="scopecat-supervisor",
            daemon=True,
        )
        self._supervisor.start()

    def close(self) -> None:
        self._stop.set()
        self._supervisor.join()
        self._workers.shutdown(wait=True, cancel_futures=False)

    def health(self) -> DaemonHealth:
        try:
            self.control.schema_version()
        except Exception:
            return self._health("degraded")
        if self._supervisor_failed or not self._supervisor.is_alive():
            return self._health("degraded")
        return self._health("ok")

    def catalog(self) -> ExperimentCatalog:
        return self._catalog.snapshot

    def get_config_registry(self) -> ConfigRegistryView:
        with self._config_lock, self._config_errors():
            entries = config_registry_service.list_config_registry_entries(
                unit_of_work=self.config_registry.unit_of_work
            )
            generation = config_registry_service.current_config_registry_generation(
                unit_of_work=self.config_registry.unit_of_work
            )
            if generation == 0:
                active_state = None
            else:
                active_state = (
                    config_registry_service.load_active_config_registry_state(
                        unit_of_work=self.config_registry.unit_of_work
                    )
                )
                config_registry_service.load_active_config_registry_entry(
                    unit_of_work=self.config_registry.unit_of_work
                )
            return ConfigRegistryView(
                entries=tuple(entries),
                active_state=active_state,
            )

    def get_active_config(self) -> ActiveConfigView:
        with self._config_lock, self._config_errors():
            state = config_registry_service.load_active_config_registry_state(
                unit_of_work=self.config_registry.unit_of_work
            )
            entry = config_registry_service.load_active_config_registry_entry(
                unit_of_work=self.config_registry.unit_of_work
            )
            config = config_registry_service.load_active_config_registry_config(
                unit_of_work=self.config_registry.unit_of_work
            )
            return ActiveConfigView(
                entry=entry,
                active_state=state,
                config=config,
            )

    def get_config_entry(self, entry_id: str) -> ConfigEntryView:
        with self._config_lock, self._config_errors():
            entry = config_registry_service.load_config_registry_entry(
                entry_id=entry_id,
                unit_of_work=self.config_registry.unit_of_work,
            )
            config = config_registry_service.load_config_registry_config(
                entry_id=entry_id,
                unit_of_work=self.config_registry.unit_of_work,
            )
            return ConfigEntryView(entry=entry, config=config)

    def import_direct_config(
        self,
        command: DirectConfigImportCommand,
    ) -> ConfigImportReceipt:
        with self._config_lock, self._config_errors():
            existing_ids = {
                entry.id
                for entry in config_registry_service.list_config_registry_entries(
                    unit_of_work=self.config_registry.unit_of_work
                )
            }
            config = validate_config_profile(command.config).config
            entry = config_registry_service.register_config_profile(
                config=config,
                unit_of_work=self.config_registry.unit_of_work,
                entry_id=command.entry_id,
                registered_by=command.registered_by,
                note=command.note,
            )
            if entry.id not in existing_ids:
                self.control.append_event(
                    DurableEventInput(
                        kind="config_imported",
                        payload={"entry_id": entry.id},
                        occurred_at=entry.registered_at,
                    )
                )
            return ConfigImportReceipt(entry=entry)

    def preview_config_draft(
        self,
        command: ConfigDraftCommand,
    ) -> ConfigDraftPreview:
        with self._config_lock, self._config_errors():
            result = config_registry_service.preview_manual_config_draft(
                unit_of_work=self.config_registry.unit_of_work,
                base_entry_id=command.base_entry_id,
                base_config_content_hash=command.base_content_hash,
                base_generation=command.base_generation,
                candidate_id=command.candidate_id,
                updates=tuple(
                    _config_parameter_update(update) for update in command.updates
                ),
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
        with self._config_lock, self._config_errors():
            existing_ids = {
                entry.id
                for entry in config_registry_service.list_config_registry_entries(
                    unit_of_work=self.config_registry.unit_of_work
                )
            }
            draft = command.draft
            entry, result = config_registry_service.register_manual_config_draft(
                unit_of_work=self.config_registry.unit_of_work,
                base_entry_id=draft.base_entry_id,
                base_config_content_hash=draft.base_content_hash,
                base_generation=draft.base_generation,
                candidate_id=draft.candidate_id,
                updates=tuple(
                    _config_parameter_update(update) for update in draft.updates
                ),
                expected_result_content_hash=command.expected_result_content_hash,
                entry_id=command.entry_id,
                registered_by=command.registered_by,
                note=command.note,
            )
            if entry.id not in existing_ids:
                self.control.append_event(
                    DurableEventInput(
                        kind="config_draft_registered",
                        payload={
                            "entry_id": entry.id,
                            "base_entry_id": draft.base_entry_id,
                        },
                        occurred_at=entry.registered_at,
                    )
                )
            return ConfigDraftRegistrationReceipt(
                entry=entry,
                result_content_hash=entry.content_hash,
                deltas=result.check.deltas,
            )

    def activate_config_entry(
        self,
        command: ConfigEntryActivationCommand,
    ) -> ConfigActivationReceipt:
        with self._config_lock, self._config_errors():
            previous_generation = (
                config_registry_service.current_config_registry_generation(
                    unit_of_work=self.config_registry.unit_of_work
                )
            )
            state, activation = config_registry_service.activate_config_registry_entry(
                entry_id=command.entry_id,
                unit_of_work=self.config_registry.unit_of_work,
                operator=command.operator,
                expected_generation=command.expected_generation,
                note=command.note,
            )
            if state.generation != previous_generation:
                self.control.append_event(
                    DurableEventInput(
                        kind="config_activated",
                        payload={
                            "entry_id": activation.entry_id,
                            "generation": activation.generation,
                        },
                        occurred_at=activation.recorded_at,
                    )
                )
            return ConfigActivationReceipt(
                active_state=state,
                activation=activation,
            )

    def rollback_config(
        self,
        command: ConfigRollbackCommand,
    ) -> ConfigActivationReceipt:
        with self._config_lock, self._config_errors():
            previous_generation = (
                config_registry_service.current_config_registry_generation(
                    unit_of_work=self.config_registry.unit_of_work
                )
            )
            state, activation = config_registry_service.rollback_config_registry(
                unit_of_work=self.config_registry.unit_of_work,
                operator=command.operator,
                expected_generation=command.expected_generation,
                note=command.note,
            )
            if state.generation != previous_generation:
                self.control.append_event(
                    DurableEventInput(
                        kind="config_rolled_back",
                        payload={
                            "entry_id": activation.entry_id,
                            "generation": activation.generation,
                        },
                        occurred_at=activation.recorded_at,
                    )
                )
            return ConfigActivationReceipt(
                active_state=state,
                activation=activation,
            )

    def list_runs(
        self,
        *,
        limit: int,
        after: int | None,
        state: ControlRunState | None,
        latest: bool = False,
    ) -> RunPage:
        return self.control.list_runs(
            limit=limit,
            after=after,
            state=state,
            latest=latest,
        )

    def get_run(self, run_id: str) -> RunDetail:
        control = self._control_run(run_id)
        leases = {
            (lease.resource.kind, lease.resource.id): lease
            for lease in self.control.list_resource_leases()
            if lease.run_id == run_id
        }
        resources = tuple(
            RunResourceView(
                resource=resource,
                status=(
                    lease.status
                    if (lease := leases.get((resource.kind, resource.id))) is not None
                    else ("released" if control.state == "terminal" else "required")
                ),
                expires_at=None if lease is None else lease.expires_at,
            )
            for resource in control.admission.resource_claims
        )
        return RunDetail(
            control=control,
            manifest=self.runs.read_manifest(run_id),
            resources=resources,
        )

    def get_run_config(self, run_id: str) -> RunConfigView:
        self._control_run(run_id)
        manifest = self.runs.read_manifest(run_id)
        return RunConfigView(
            run_id=run_id,
            config_content_hash=manifest.config_content_hash,
            config=self.runs.read_config_profile_snapshot(run_id),
        )

    def get_run_request(self, run_id: str) -> RunRequestView:
        self._control_run(run_id)
        with self._run_content_lock, self._config_errors():
            return RunRequestView(
                run_id=run_id,
                request=load_run_request(run_id=run_id, services=self.services),
            )

    def list_run_analyses(self, run_id: str) -> RunAnalysisListView:
        self._control_run(run_id)
        with self._run_content_lock, self._config_errors():
            manifest = self.runs.read_manifest(run_id)
            return RunAnalysisListView(
                run_id=run_id,
                items=tuple(
                    self._run_analysis_view(run_id, record.id)
                    for record in list_records(manifest, kind="analysis")
                ),
            )

    def get_run_analysis(self, run_id: str, selector: str) -> RunAnalysisView:
        self._control_run(run_id)
        with self._run_content_lock, self._config_errors():
            return self._run_analysis_view(run_id, selector)

    def _run_analysis_view(self, run_id: str, selector: str) -> RunAnalysisView:
        result = read_run_record_json(
            run_id=run_id,
            selector=selector,
            expected_kind="analysis",
            services=self.services,
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
        self._control_run(run_id)
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
        with self._run_content_lock, self._config_errors():
            existing = {
                entry.id: entry.content_hash
                for entry in self.runs.read_manifest(run_id).records
            }
            saved = save_analysis(
                services=self.services,
                run_id=run_id,
                title=command.title,
                analysis_key=command.analysis_key,
                step_id=command.step_id,
                inputs=inputs,
                outputs=outputs,
                parameter_proposals=proposals,
            )
            if existing.get(saved.record.id) != saved.record.content_hash:
                self.control.append_event(
                    DurableEventInput(
                        run_id=run_id,
                        kind="analysis_saved",
                        payload={
                            "analysis_key": saved.analysis_key,
                            "record_id": saved.record.id,
                        },
                    )
                )
        return AnalysisSaveReceipt(
            record=saved.record,
            analysis_key=saved.analysis_key,
            inputs=command.inputs,
            output_artifacts=saved.output_artifacts,
        )

    def get_run_artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactBytesView:
        self._control_run(run_id)
        with self._run_content_lock, self._config_errors():
            result = read_run_artifact_bytes(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self.services,
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
    ) -> RunArtifactTextView:
        self._control_run(run_id)
        with self._run_content_lock, self._config_errors():
            result = read_run_artifact_text(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self.services,
            )
            return RunArtifactTextView(
                run_id=run_id,
                artifact=result.artifact,
                content=result.content,
            )

    def get_run_artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactJsonView:
        self._control_run(run_id)
        with self._run_content_lock, self._config_errors():
            result = read_run_artifact_json(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self.services,
            )
            return RunArtifactJsonView(
                run_id=run_id,
                artifact=result.artifact,
                content=dict(result.content),
            )

    def get_run_record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunRecordJsonView:
        self._control_run(run_id)
        with self._run_content_lock, self._config_errors():
            result = read_run_record_json(
                run_id=run_id,
                selector=selector,
                expected_kind=expected_kind,
                services=self.services,
            )
            return RunRecordJsonView(
                run_id=run_id,
                record=result.record,
                content=dict(result.content),
            )

    def get_run_dataset_content(
        self,
        run_id: str,
        selector: str,
    ) -> RunDatasetContentView:
        self._control_run(run_id)
        with self._run_content_lock, self._config_errors():
            dataset = require_dataset(
                manifest=self.runs.read_manifest(run_id),
                selector=selector,
            )
            if dataset.kind == "measurement_dataset":
                content = read_run_measurement_dataset(
                    run_id=run_id,
                    selector=selector,
                    services=self.services,
                ).dataset
            elif dataset.kind == "data_table":
                content = read_run_data_table(
                    run_id=run_id,
                    selector=selector,
                    services=self.services,
                ).table
            elif dataset.kind == "data_array":
                content = read_run_data_array(
                    run_id=run_id,
                    selector=selector,
                    services=self.services,
                ).array
            else:
                raise BackendConflict(
                    f"run dataset kind does not support content access: {dataset.kind}"
                )
            return RunDatasetContentView(
                run_id=run_id,
                dataset=dataset,
                content=content,
            )

    def attach_run_content(
        self,
        run_id: str,
        command: RunAttachmentCommand,
    ) -> RunAttachmentReceipt:
        self._control_run(run_id)
        content = (
            None
            if command.content_base64 is None
            else b64decode(command.content_base64, validate=True)
        )
        with self._run_content_lock, self._config_errors():
            artifact = attach_run_artifact(
                services=self.services,
                run_id=run_id,
                key=command.key,
                kind=command.kind,
                text=command.text,
                content=content,
                filename=command.filename,
                media_type=command.media_type,
                metadata=command.metadata,
            )
        return RunAttachmentReceipt(run_id=run_id, artifact=artifact)

    def list_parameter_proposals(self, run_id: str) -> ParameterProposalListView:
        self._control_run(run_id)
        with self._run_content_lock, self._config_errors():
            proposals = list_parameter_change_proposals(
                run_id=run_id,
                services=self.services,
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
                                storage=self.runs,
                            )
                        ),
                    )
                    for proposal in proposals
                ),
            )

    def review_parameter_proposal(
        self,
        run_id: str,
        command: ParameterProposalReviewCommand,
    ) -> ParameterProposalReviewReceipt:
        self._control_run(run_id)
        with self._run_content_lock, self._config_errors():
            decision = review_parameter_change_proposal(
                run_id=run_id,
                selector=command.proposal_id,
                services=self.services,
                state=command.decision,
                reviewer=command.reviewer,
                note=command.note,
            )
            self.control.append_event(
                DurableEventInput(
                    run_id=run_id,
                    kind="parameter_proposal_reviewed",
                    payload={
                        "proposal_id": decision.proposal_id,
                        "decision": decision.decision,
                        "event_id": decision.event_id,
                    },
                    occurred_at=decision.decided_at,
                )
            )
        return ParameterProposalReviewReceipt(decision=decision)

    def activate_candidate_config(
        self,
        command: CandidateConfigActivationCommand,
    ) -> CandidateConfigActivationReceipt:
        self._control_run(command.run_id)
        with (
            self._config_lock,
            self._run_content_lock,
            self._config_errors(),
        ):
            previous_generation = (
                config_registry_service.current_config_registry_generation(
                    unit_of_work=self.config_registry.unit_of_work
                )
            )
            candidate = CandidateConfig(
                parameter_proposals=tuple(
                    load_parameter_change_proposal(
                        run_id=command.run_id,
                        selector=proposal_id,
                        services=self.services,
                    )
                    for proposal_id in command.proposal_ids
                )
            )
            result = register_and_activate_candidate_config(
                candidate=candidate,
                services=self.services,
                entry_id=command.entry_id,
                registered_by=command.registered_by,
                operator=command.operator,
                note=command.note,
                activation_note=command.activation_note,
                expected_generation=command.expected_generation,
            )
            if result.active_state.generation != previous_generation:
                self.control.append_event(
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
                    )
                )
            return CandidateConfigActivationReceipt(
                entry=result.entry,
                active_state=result.active_state,
                activation=result.activation,
            )

    def resolve_attention(
        self,
        run_id: str,
        command: AttentionResolutionCommand,
    ) -> AttentionResolutionReceipt:
        run = self._control_run(run_id)
        if run.state != "attention_required":
            raise BackendConflict("run does not require operator attention")
        if command.action == "release":
            try:
                released = self.control.release_run_resources(run_id)
            except ControlPlaneConflict as error:
                raise BackendConflict(str(error)) from error
            return AttentionResolutionReceipt(
                run_id=run_id,
                action=command.action,
                state="attention_required",
                released_resource_count=released,
            )

        planned = None
        if command.action == "requeue" and run.admission.execution_mode == "managed":
            try:
                planned = self._rebuild_managed_plan(run)
            except Exception as error:
                raise BackendConflict(
                    "managed run no longer matches its admitted plan"
                ) from error

        manifest = self.runs.read_manifest(run_id)
        if command.action == "requeue":
            accepted = RunManifest.model_validate(
                {
                    **manifest.model_dump(mode="python"),
                    "lifecycle": "accepted",
                    "outcome": None,
                }
            )
            try:
                with self.control.transaction() as connection:
                    released = self.control.release_run_resources_in_transaction(
                        connection,
                        run_id,
                    )
                    self.runs.write_manifest_in_transaction(connection, accepted)
                    self.control.transition_run_in_transaction(
                        connection,
                        run_id,
                        expected_state="attention_required",
                        state="accepted",
                    )
            except ControlPlaneConflict as error:
                raise BackendConflict(str(error)) from error
            if planned is not None:
                self._schedule_managed(run_id, planned)
            return AttentionResolutionReceipt(
                run_id=run_id,
                action=command.action,
                state="accepted",
                released_resource_count=released,
            )

        outcome = RunOutcome(
            run_id=run_id,
            result="failed",
            certainty="known",
            termination_reason="blocking_problem",
            problems=(
                blocking_problem(
                    "daemon.operator_aborted",
                    "operator aborted a run requiring reconciliation",
                    category=ProblemCategory.CONFLICT,
                    phase=ProblemPhase.EXECUTION,
                ),
            ),
        )
        terminal = RunManifest.model_validate(
            {
                **manifest.model_dump(mode="python"),
                "lifecycle": "terminal",
                "outcome": outcome,
            }
        )
        prepared = self.runs.prepare_terminal_commit(
            TerminalRunCommit(
                manifest=terminal,
                models=(
                    RunModelWrite(
                        ref=run_outcome_ref(),
                        value=outcome,
                    ),
                ),
            )
        )
        try:
            with self.control.transaction() as connection:
                released = self.control.release_run_resources_in_transaction(
                    connection,
                    run_id,
                )
                self.runs.commit_prepared_terminal_in_transaction(
                    connection,
                    prepared,
                )
                self.control.transition_run_in_transaction(
                    connection,
                    run_id,
                    expected_state="attention_required",
                    state="terminal",
                    outcome=outcome,
                )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        self._managed_finished(run_id, terminal=True)
        return AttentionResolutionReceipt(
            run_id=run_id,
            action=command.action,
            state="terminal",
            released_resource_count=released,
        )

    def measurements(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> MeasurementPage:
        self._control_run(run_id)
        records = SQLiteMeasurementDatasetRepository(
            self.runs,
            run_id=run_id,
        ).measurements()
        items = records[offset : offset + limit]
        next_offset = (
            offset + len(items) if offset + len(items) < len(records) else None
        )
        return MeasurementPage(items=items, next_offset=next_offset)

    def _control_run(self, run_id: str) -> ControlRun:
        try:
            return self.control.get_run(run_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error

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
        return self.control.list_events(
            limit=limit,
            after=after,
            run_id=run_id,
            latest=latest,
        )

    def submit_run(self, submission: RunSubmission) -> RunAdmission:
        with self._submission_lock:
            existing = self._existing_submission(submission)
            if existing is not None:
                return self._wire_admission(existing)
            if isinstance(submission, DelegatedRunSubmission):
                run = self._admit_delegated(submission)
            else:
                run, planned = self._admit_managed(submission)
                self._schedule_managed(run.run_id, planned)
            return self._wire_admission(run)

    def start_executor(
        self,
        run_id: str,
        request: ExecutorStartRequest,
    ) -> ExecutorLease:
        run = self._control_run(run_id)
        if run.admission.execution_mode != "delegated":
            raise BackendConflict("only delegated runs accept external executors")
        accepted = self.runs.read_manifest(run_id)
        expected = accepted.model_copy(update={"lifecycle": "running"})
        if request.manifest != expected:
            raise BackendConflict(
                "running manifest does not match the admitted run snapshot"
            )
        lease = self._start_execution(
            run_id,
            executor_id=request.executor_id,
            manifest=request.manifest,
        )
        return self._wire_lease(lease)

    def heartbeat_executor(
        self,
        run_id: str,
        heartbeat: ExecutorHeartbeat,
    ) -> ExecutorLease:
        self.fence_executor(run_id, heartbeat.lease_id, heartbeat.generation)
        try:
            renewed = self.control.renew_executor_lease(
                heartbeat.lease_id,
                ttl=self._lease_ttl,
            )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        return self._wire_lease(renewed)

    def append_transitions(
        self,
        run_id: str,
        batch: ExecutionTransitionBatch,
    ) -> ExecutionTransitionBatchReceipt:
        self.fence_executor(run_id, batch.lease_id, batch.generation)
        journal = SQLiteExecutionJournal(self.runs, run_id=run_id)
        with self.fenced_write(
            run_id,
            token=batch.lease_id,
            generation=batch.generation,
        ) as connection:
            commit = journal.append_batch_in_transaction(
                connection,
                batch.batch_id,
                batch.transitions,
            )
            if commit.created:
                for transition in commit.transitions:
                    self.control.append_event_in_transaction(
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
                            },
                        ),
                    )
        return ExecutionTransitionBatchReceipt(
            batch_id=batch.batch_id,
            committed=commit.transitions,
        )

    def recover_execution(
        self,
        run_id: str,
        request: ExecutionRecoveryRequest,
    ) -> ExecutionRecoverySnapshot:
        self.fence_executor(run_id, request.lease_id, request.generation)
        return ExecutionRecoverySnapshot(
            transitions=SQLiteExecutionJournal(
                self.runs,
                run_id=run_id,
            ).entries(),
            measurements=SQLiteMeasurementDatasetRepository(
                self.runs,
                run_id=run_id,
            ).measurements(),
            measurement_append_indices=SQLiteMeasurementDatasetRepository(
                self.runs,
                run_id=run_id,
            ).append_indices(),
            collection_receipts=SQLiteCollectionRecordRepository(
                self.runs,
                run_id=run_id,
            ).receipts(),
        )

    def append_measurements(
        self,
        run_id: str,
        command: MeasurementAppendCommand,
    ) -> MeasurementAppendReceipt:
        self.fence_executor(run_id, command.lease_id, command.generation)
        repository = SQLiteMeasurementDatasetRepository(
            self.runs,
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
            generation=command.generation,
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
                    command.command_id,
                )
        return MeasurementAppendReceipt(
            command_id=command.command_id,
            receipt=receipt,
        )

    def seal_measurements(
        self,
        run_id: str,
        command: MeasurementSealCommand,
    ) -> MeasurementSealReceipt:
        self.fence_executor(run_id, command.lease_id, command.generation)
        repository = SQLiteMeasurementDatasetRepository(
            self.runs,
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
            generation=command.generation,
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
                    command.command_id,
                )
        return MeasurementSealReceipt(
            command_id=command.command_id,
            receipt=receipt,
        )

    def commit_collection(
        self,
        run_id: str,
        command: CollectionCommitCommand,
    ) -> CollectionCommitReceipt:
        self.fence_executor(run_id, command.lease_id, command.generation)
        repository = SQLiteCollectionRecordRepository(
            self.runs,
            run_id=run_id,
        )
        try:
            prepared = repository.prepare_commit(command.chunk)
        except ExecutionJournalConflict as error:
            raise BackendConflict(
                "collection command conflicts with durable state"
            ) from error
        with self.fenced_write(
            run_id,
            token=command.lease_id,
            generation=command.generation,
        ) as connection:
            receipt, created = repository.commit_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self.append_effect_event_in_transaction(
                    connection,
                    run_id,
                    "collection_committed",
                    command.command_id,
                )
        return CollectionCommitReceipt(
            command_id=command.command_id,
            receipt=receipt,
        )

    def resolve_collection(
        self,
        run_id: str,
        command: CollectionResolveCommand,
    ) -> CollectionResolveReceipt:
        self.fence_executor(run_id, command.lease_id, command.generation)
        chunk = SQLiteCollectionRecordRepository(
            self.runs,
            run_id=run_id,
        ).resolve(command.receipt)
        return CollectionResolveReceipt(chunk=chunk)

    def commit_payload(
        self,
        run_id: str,
        command: PayloadCommitCommand,
    ) -> PayloadCommitReceipt:
        self.fence_executor(run_id, command.lease_id, command.generation)
        repository = SQLitePayloadEvidenceCommitter(
            self.runs,
            run_id=run_id,
        )
        try:
            prepared = repository.prepare_commit(command.evidence)
        except ExecutionJournalConflict as error:
            raise BackendConflict(
                "payload command conflicts with durable state"
            ) from error
        with self.fenced_write(
            run_id,
            token=command.lease_id,
            generation=command.generation,
        ) as connection:
            evidence, created = repository.commit_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self.append_effect_event_in_transaction(
                    connection,
                    run_id,
                    "payload_committed",
                    command.command_id,
                )
        return PayloadCommitReceipt(
            command_id=command.command_id,
            evidence=evidence,
        )

    def commit_terminal(
        self,
        run_id: str,
        command: TerminalRunCommitCommand,
    ) -> TerminalRunCommitReceipt:
        control_run = self._control_run(run_id)
        if control_run.state == "terminal":
            manifest = self.runs.read_manifest(run_id)
            if manifest != command.manifest:
                raise BackendConflict("run already has a different terminal manifest")
            return TerminalRunCommitReceipt(
                command_id=command.command_id,
                manifest=manifest,
            )
        commit = TerminalRunCommit(
            manifest=command.manifest,
            models=tuple(
                RunModelWrite(
                    ref=write.ref,
                    value=_JsonDocument(root=write.value),
                )
                for write in command.models
            ),
            record_sets=tuple(
                RunRecordSetWrite(
                    ref=write.ref,
                    records=tuple(
                        _JsonDocument(root=record) for record in write.records
                    ),
                )
                for write in command.record_sets
            ),
        )
        try:
            manifest = self.commit_terminal_with_authority(
                run_id,
                token=command.lease_id,
                generation=command.generation,
                commit=commit,
            )
        except BackendConflict:
            current = self._control_run(run_id)
            manifest = self.runs.read_manifest(run_id)
            if current.state != "terminal" or manifest != command.manifest:
                raise
        return TerminalRunCommitReceipt(
            command_id=command.command_id,
            manifest=manifest,
        )

    @property
    def _project_id(self) -> str:
        identity = sha256(str(self.project_root).encode()).hexdigest()[:16]
        return f"local:{identity}"

    def _health(self, status: Literal["ok", "degraded"]) -> DaemonHealth:
        return DaemonHealth(
            status=status,
            project_id=self._project_id,
            project_name=self.project_root.name,
            project_root=str(self.project_root),
        )

    def _admit_delegated(self, submission: DelegatedRunSubmission) -> ControlRun:
        accepted = RunManifest(
            run_id=new_run_id(),
            lifecycle="accepted",
            config_content_hash=submission.config_content_hash,
        )
        admission = RunAdmissionRecord(
            submission_id=submission.submission_id,
            run_id=accepted.run_id,
            execution_mode="delegated",
            experiment_id=submission.plan.experiment_id,
            config_content_hash=submission.config_content_hash,
            request=submission.request,
            plan_summary={
                "submission": self._submission_identity(submission),
                "plan": submission.plan.model_dump(mode="json"),
            },
            resource_claims=tuple(
                ResourceKey(kind=claim.kind, id=claim.id)
                for claim in submission.plan.run_resource_claims
            ),
            admitted_at=accepted.created_at,
        )
        return self._commit_admission(
            accepted=accepted,
            config=submission.config,
            request=submission.request,
            admission=admission,
        )

    def _commit_admission(
        self,
        *,
        accepted: RunManifest,
        config: ConfigProfileSnapshot,
        request: RunRequest | None,
        admission: RunAdmissionRecord,
    ) -> ControlRun:
        prepared = self.runs.prepare_run_skeleton(
            manifest=accepted,
            request=request,
            config=config,
        )
        with self.control.transaction() as connection:
            self.runs.commit_run_skeleton_in_transaction(connection, prepared)
            return self.control.admit_run_in_transaction(connection, admission)

    def _managed_admission(
        self,
        submission: ManagedRunSubmission,
        planned: PlannedRun,
        accepted: RunManifest,
        summary: DelegatedPlanSummary,
    ) -> RunAdmissionRecord:
        return RunAdmissionRecord(
            submission_id=submission.submission_id,
            run_id=accepted.run_id,
            execution_mode="managed",
            experiment_id=planned.program.experiment_id,
            config_content_hash=accepted.config_content_hash,
            request=planned.request,
            plan_summary={
                "submission": self._submission_identity(submission),
                "plan": summary.model_dump(mode="json"),
            },
            resource_claims=tuple(
                ResourceKey(kind=claim.kind, id=claim.id)
                for claim in planned.program.resource_claims
            ),
            admitted_at=accepted.created_at,
        )

    def _admit_managed(
        self,
        submission: ManagedRunSubmission,
    ) -> tuple[ControlRun, PlannedRun]:
        try:
            prepared = self._catalog.prepare(submission)
            resolved_config = resolve_experiment_config(
                services=self.services,
                config=submission.request.config_source or "active",
            )
            system = build_experiment_system(
                self._build_system,
                resolved_config.config,
            )
            planned = plan_experiment(
                prepared,
                services=self.services,
                config=resolved_config.config,
                system=system,
            )
            planned = replace(planned, config_source=resolved_config.config_source)
        except KeyError as error:
            raise BackendNotFound(str(error)) from error
        except CheckFailed as error:
            raise BackendConflict("managed run did not pass planning checks") from error
        accepted = RunManifest(
            run_id=new_run_id(),
            lifecycle="accepted",
            config_content_hash=config_content_hash(planned.config),
            config_source=planned.config_source,
        )
        summary = self._program_summary(planned)
        run = self._commit_admission(
            accepted=accepted,
            config=planned.config,
            request=planned.request,
            admission=self._managed_admission(
                submission,
                planned,
                accepted,
                summary,
            ),
        )
        return run, planned

    def _existing_submission(
        self,
        submission: RunSubmission,
    ) -> ControlRun | None:
        try:
            existing = self.control.get_run_by_submission_id(submission.submission_id)
        except ControlPlaneNotFound:
            return None
        stored = existing.admission.plan_summary.get("submission")
        if (
            existing.admission.execution_mode != submission.execution_mode
            or existing.admission.request != submission.request
            or stored != self._submission_identity(submission)
            or (
                isinstance(submission, DelegatedRunSubmission)
                and existing.admission.config_content_hash
                != submission.config_content_hash
            )
        ):
            raise BackendConflict(
                "submission id is already bound to different run intent"
            )
        return existing

    def _submission_identity(
        self,
        submission: RunSubmission,
    ) -> dict[str, JsonValue]:
        if isinstance(submission, DelegatedRunSubmission):
            return {
                "executor_id": submission.executor_id,
                "plan": submission.plan.model_dump(mode="json"),
            }
        return {
            "registration_id": submission.registration_id,
            "registration_version": submission.registration_version,
        }

    def _wire_admission(self, run: ControlRun) -> RunAdmission:
        events = self.control.list_events(limit=1, run_id=run.run_id).items
        if not events:
            raise RuntimeError("admitted run is missing its first durable event")
        return RunAdmission(
            run_id=run.run_id,
            submission_id=run.admission.submission_id,
            execution_mode=run.admission.execution_mode,
            config_content_hash=run.admission.config_content_hash,
            accepted_at=run.admission.admitted_at,
            event_cursor=events[0].event_id,
        )

    def _program_summary(self, planned: PlannedRun) -> DelegatedPlanSummary:
        program = planned.program
        return DelegatedPlanSummary(
            experiment_id=program.experiment_id,
            experiment_kind=program.points.experiment_kind,
            point_count=len(program.points.points),
            coordinate_ids=program.points.coordinate_ids,
            record_ids=tuple(record.id for record in program.measurements.records),
            run_resource_claims=tuple(
                ResourceClaimDescriptor(id=claim.id, kind=claim.kind)
                for claim in program.resource_claims
            ),
        )

    def _start_execution(
        self,
        run_id: str,
        *,
        executor_id: str,
        manifest: RunManifest,
    ) -> ControlExecutorLease:
        try:
            with self.control.transaction() as connection:
                current = self.control.get_run_in_transaction(connection, run_id)
                if current.state == "running":
                    lease = self.control.executor_lease_for_run_in_transaction(
                        connection,
                        run_id,
                    )
                    if (
                        lease is None
                        or lease.expires_at <= datetime.now(tz=UTC)
                        or lease.executor_id != executor_id
                        or self.runs.read_manifest_in_transaction(
                            connection,
                            run_id,
                        )
                        != manifest
                    ):
                        raise ControlPlaneConflict(
                            "run is already owned by a different executor intent"
                        )
                    return lease
                lease = self.control.start_execution_in_transaction(
                    connection,
                    run_id,
                    executor_id=executor_id,
                    ttl=self._lease_ttl,
                )
                self.runs.write_manifest_in_transaction(connection, manifest)
                return lease
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error

    def fence_executor(self, run_id: str, token: str, generation: int) -> str:
        try:
            self.control.validate_executor_lease(
                run_id,
                token=token,
                generation=generation,
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
        generation: int,
    ) -> Generator[sqlite3.Connection]:
        try:
            with self.control.fenced_transaction(
                run_id,
                token=token,
                generation=generation,
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
            generation=lease.generation,
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
        command_id: str,
    ) -> None:
        self.control.append_event_in_transaction(
            connection,
            DurableEventInput(
                run_id=run_id,
                kind=kind,
                payload={"command_id": command_id},
            ),
        )

    def commit_terminal_with_authority(
        self,
        run_id: str,
        *,
        token: str,
        generation: int,
        commit: TerminalRunCommit,
    ) -> RunManifest:
        self.fence_executor(run_id, token, generation)
        prepared = self.runs.prepare_terminal_commit(commit)
        with self.fenced_write(
            run_id,
            token=token,
            generation=generation,
        ) as connection:
            manifest = self.runs.commit_prepared_terminal_in_transaction(
                connection,
                prepared,
            )
            if manifest.outcome is None:
                raise ValueError("terminal manifest requires an outcome")
            self.control.transition_run_in_transaction(
                connection,
                run_id,
                expected_state="running",
                state="terminal",
                outcome=manifest.outcome,
                executor_token=token,
            )
            return manifest

    def _execution_services(
        self,
        resources: ResourceLeaseManager,
    ) -> ExecutionServices:
        return ExecutionServices(
            runs=self.runs,
            resources=resources,
            journal_for=lambda run_id: SQLiteExecutionJournal(
                self.runs,
                run_id=run_id,
            ),
            measurements_for=lambda run_id: SQLiteMeasurementDatasetRepository(
                self.runs,
                run_id=run_id,
            ),
            collections_for=lambda run_id: SQLiteCollectionRecordRepository(
                self.runs,
                run_id=run_id,
            ),
            payloads_for=lambda run_id: SQLitePayloadEvidenceCommitter(
                self.runs,
                run_id=run_id,
            ),
        )

    def _managed_execution_services(
        self,
        authority: _ManagedExecutionAuthority,
        resources: ResourceLeaseManager,
    ) -> ExecutionServices:
        return ExecutionServices(
            runs=_ManagedRunStore(authority),
            resources=resources,
            journal_for=lambda run_id: _ManagedExecutionJournal(
                authority.for_run(run_id)
            ),
            measurements_for=lambda run_id: _ManagedMeasurements(
                authority.for_run(run_id)
            ),
            collections_for=lambda run_id: _ManagedCollections(
                authority.for_run(run_id)
            ),
            payloads_for=lambda run_id: _ManagedPayloads(authority.for_run(run_id)),
        )

    def _schedule_managed(self, run_id: str, planned: PlannedRun) -> None:
        with self._managed_lock:
            self._managed_plans[run_id] = planned
            if run_id in self._managed_active:
                return
            self._managed_active.add(run_id)
        self._workers.submit(self._execute_managed, run_id, planned)

    def _execute_managed(self, run_id: str, planned: PlannedRun) -> None:
        terminal = False
        accepted = self.runs.read_manifest(run_id)
        running = accepted.model_copy(update={"lifecycle": "running"})
        try:
            lease = self._start_execution(
                run_id,
                executor_id=f"daemon:{self._project_id}",
                manifest=running,
            )
        except BackendConflict:
            self._managed_finished(run_id, terminal=False)
            return
        authority = _ManagedExecutionAuthority(
            backend=self,
            run_id=run_id,
            token=lease.token,
            generation=lease.generation,
        )
        heartbeat_stop = Event()
        heartbeat = Thread(
            target=self._heartbeat_managed,
            args=(lease.token, heartbeat_stop),
            name=f"scopecat-heartbeat-{run_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            execute_running_run(
                run_id=run_id,
                program=planned.program,
                services=self._managed_execution_services(
                    authority,
                    _PreclaimedResources(
                        control=self.control,
                        run_id=run_id,
                        token=lease.token,
                        generation=lease.generation,
                        claims=planned.program.resource_claims,
                    ),
                ),
                instrument_provider=(
                    None if planned.system is None else planned.system.provider
                ),
                event_sink=authority.observe,
            )
        except (RunFailed, RunIndeterminate):
            logger.info("managed run reached a durable non-success outcome: %s", run_id)
        except BaseException:
            logger.exception("managed executor stopped unexpectedly: %s", run_id)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)
        if self.control.get_run(run_id).state == "terminal":
            terminal = True
        else:
            self._require_attention(run_id, lease.token, "managed_executor_stopped")
        self._managed_finished(run_id, terminal=terminal)

    def _managed_finished(self, run_id: str, *, terminal: bool) -> None:
        with self._managed_lock:
            self._managed_active.discard(run_id)
            if terminal:
                self._managed_plans.pop(run_id, None)

    def _heartbeat_managed(self, token: str, stop: Event) -> None:
        while not stop.wait(self._heartbeat_interval_seconds):
            try:
                self.control.renew_executor_lease(token, ttl=self._lease_ttl)
            except ControlPlaneConflict:
                return

    def _require_attention(self, run_id: str, token: str, reason: str) -> None:
        try:
            run = self.control.get_run(run_id)
            if run.state == "running":
                self.control.transition_run(
                    run_id,
                    expected_state="running",
                    state="attention_required",
                    attention_reason=reason,
                    executor_token=token,
                )
        except ControlPlaneConflict:
            return

    def _supervise(self) -> None:
        while not self._stop.wait(self._supervisor_interval_seconds):
            try:
                self.control.expire_executor_leases()
                with self._managed_lock:
                    pending = tuple(self._managed_plans.items())
                for run_id, planned in pending:
                    if self.control.get_run(run_id).state == "accepted":
                        self._schedule_managed(run_id, planned)
            except Exception:
                self._supervisor_failed = True
                logger.exception("daemon supervisor iteration failed")

    def _reconcile_startup(self) -> None:
        self.control.abandon_executor_leases()
        for run in self._all_control_runs():
            if run.state != "accepted" or run.admission.execution_mode != "managed":
                continue
            try:
                planned = self._rebuild_managed_plan(run)
            except Exception as error:
                logger.warning(
                    "managed run could not be rebuilt at startup: %s",
                    run.run_id,
                    exc_info=True,
                )
                self._fail_unstartable_managed(run, error)
                continue
            self._schedule_managed(run.run_id, planned)

    def _rebuild_managed_plan(self, run: ControlRun) -> PlannedRun:
        submission_data = cast(
            "dict[str, JsonValue]",
            run.admission.plan_summary["submission"],
        )
        request = run.admission.request
        if request is None:
            raise ValueError("managed admission is missing its run request")
        submission = ManagedRunSubmission(
            submission_id=run.admission.submission_id,
            registration_id=cast("str", submission_data["registration_id"]),
            registration_version=cast(
                "str",
                submission_data["registration_version"],
            ),
            request=request,
        )
        config = self.runs.read_config_profile_snapshot(run.run_id)
        system = build_experiment_system(self._build_system, config)
        planned = plan_experiment(
            self._catalog.prepare(submission),
            services=self.services,
            config=config,
            system=system,
        )
        planned = replace(
            planned,
            config_source=self.runs.read_manifest(run.run_id).config_source,
        )
        if (
            self._program_summary(planned).model_dump(mode="json")
            != run.admission.plan_summary.get("plan")
            or config_content_hash(planned.config) != run.admission.config_content_hash
        ):
            raise ValueError("managed plan changed since admission")
        return planned

    def _fail_unstartable_managed(
        self,
        run: ControlRun,
        error: Exception,
    ) -> None:
        manifest = self.runs.read_manifest(run.run_id)
        outcome = RunOutcome(
            run_id=run.run_id,
            result="failed",
            certainty="known",
            termination_reason="blocking_problem",
            problems=(
                blocking_problem(
                    "daemon.managed_plan_unavailable",
                    "managed run could not be rebuilt from its admitted plan",
                    category=ProblemCategory.CONFLICT,
                    phase=ProblemPhase.PLANNING,
                    details={"exception_type": type(error).__qualname__},
                ),
            ),
        )
        terminal = RunManifest.model_validate(
            {
                **manifest.model_dump(mode="python"),
                "lifecycle": "terminal",
                "outcome": outcome,
            }
        )
        prepared = self.runs.prepare_terminal_commit(
            TerminalRunCommit(
                manifest=terminal,
                models=(
                    RunModelWrite(
                        ref=run_outcome_ref(),
                        value=outcome,
                    ),
                ),
            )
        )
        try:
            with self.control.transaction() as connection:
                self.runs.commit_prepared_terminal_in_transaction(
                    connection,
                    prepared,
                )
                self.control.transition_run_in_transaction(
                    connection,
                    run.run_id,
                    expected_state="accepted",
                    state="terminal",
                    outcome=outcome,
                )
        except ControlPlaneConflict:
            logger.info(
                "managed run changed while startup failure was recorded: %s",
                run.run_id,
            )

    def _all_control_runs(self) -> tuple[ControlRun, ...]:
        selected: list[ControlRun] = []
        cursor: int | None = None
        while True:
            page = self.control.list_runs(limit=500, after=cursor)
            selected.extend(page.items)
            if page.next_cursor is None:
                return tuple(selected)
            cursor = page.next_cursor


class _ManagedExecutionAuthority:
    """Bind every managed executor write to one live fencing generation."""

    def __init__(
        self,
        *,
        backend: SQLiteDaemonBackend,
        run_id: str,
        token: str,
        generation: int,
    ) -> None:
        self.backend = backend
        self.run_id = run_id
        self.token = token
        self.generation = generation
        self.terminal_committed = False

    def for_run(self, run_id: str) -> _ManagedExecutionAuthority:
        if run_id != self.run_id:
            raise ValueError("managed execution service run id changed")
        return self

    def fence(self) -> None:
        self.backend.fence_executor(self.run_id, self.token, self.generation)

    @contextmanager
    def write(self) -> Generator[sqlite3.Connection]:
        with self.backend.fenced_write(
            self.run_id,
            token=self.token,
            generation=self.generation,
        ) as connection:
            yield connection

    def effect_event(
        self,
        connection: sqlite3.Connection,
        kind: str,
        command_id: str,
    ) -> None:
        self.backend.append_effect_event_in_transaction(
            connection,
            self.run_id,
            kind,
            command_id,
        )

    def commit_terminal(self, commit: TerminalRunCommit) -> RunManifest:
        manifest = self.backend.commit_terminal_with_authority(
            self.run_id,
            token=self.token,
            generation=self.generation,
            commit=commit,
        )
        self.terminal_committed = True
        return manifest

    def observe(self, event: RuntimeEvent) -> None:
        if event.run_id != self.run_id:
            raise ValueError("runtime event run id changed")
        durable = DurableEventInput(
            run_id=event.run_id,
            kind=f"runtime_{event.kind}",
            payload=_JSON_OBJECT.validate_python(
                to_jsonable_python(asdict(event)),
            ),
            occurred_at=event.observed_at,
        )
        if event.kind == "run_finished" and self.terminal_committed:
            self.backend.control.append_event(durable)
            return
        with self.write() as connection:
            self.backend.control.append_event_in_transaction(connection, durable)


class _ManagedRunStore:
    def __init__(self, authority: _ManagedExecutionAuthority) -> None:
        self._authority = authority

    def read_manifest(self, run_id: str) -> RunManifest:
        self._authority.for_run(run_id).fence()
        return self._authority.backend.runs.read_manifest(run_id)

    def write_manifest(self, manifest: RunManifest) -> None:
        self._authority.for_run(manifest.run_id).fence()
        with self._authority.write() as connection:
            self._authority.backend.runs.write_manifest_in_transaction(
                connection,
                manifest,
            )

    def read_config_profile_snapshot(self, run_id: str) -> ConfigProfileSnapshot:
        self._authority.for_run(run_id).fence()
        return self._authority.backend.runs.read_config_profile_snapshot(run_id)

    def commit_terminal(self, commit: TerminalRunCommit) -> RunManifest:
        self._authority.for_run(commit.manifest.run_id)
        return self._authority.commit_terminal(commit)


class _ManagedExecutionJournal:
    def __init__(self, authority: _ManagedExecutionAuthority) -> None:
        self._authority = authority
        self._repository = SQLiteExecutionJournal(
            authority.backend.runs,
            run_id=authority.run_id,
        )

    def append(self, entry: ExecutionTransition) -> ExecutionTransition:
        self._authority.fence()
        with self._authority.write() as connection:
            committed, created = self._repository.append_in_transaction(
                connection,
                entry,
            )
            if created:
                self._authority.effect_event(
                    connection,
                    "execution_transition_committed",
                    entry.operation_id,
                )
            return committed

    def entries(self) -> tuple[ExecutionTransition, ...]:
        self._authority.fence()
        return self._repository.entries()


class _ManagedMeasurements:
    def __init__(self, authority: _ManagedExecutionAuthority) -> None:
        self._authority = authority
        self._repository = SQLiteMeasurementDatasetRepository(
            authority.backend.runs,
            run_id=authority.run_id,
        )

    def append(
        self,
        append: MeasurementDatasetAppend,
    ) -> MeasurementDatasetReceipt:
        self._authority.fence()
        prepared = self._repository.prepare_append(append)
        with self._authority.write() as connection:
            receipt, created = self._repository.append_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self._authority.effect_event(
                    connection,
                    "measurements_appended",
                    append.operation_id,
                )
            return receipt

    def seal(self, seal: MeasurementDatasetSeal) -> MeasurementDatasetReceipt:
        self._authority.fence()
        prepared = self._repository.prepare_seal(seal)
        with self._authority.write() as connection:
            receipt, created = self._repository.seal_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self._authority.effect_event(
                    connection,
                    "measurements_sealed",
                    seal.operation_id,
                )
            return receipt

    def measurements(self) -> tuple[MeasurementRecord, ...]:
        self._authority.fence()
        return self._repository.measurements()

    def append_indices(self) -> tuple[MeasurementDatasetAppendIndex, ...]:
        self._authority.fence()
        return self._repository.append_indices()


class _ManagedCollections:
    def __init__(self, authority: _ManagedExecutionAuthority) -> None:
        self._authority = authority
        self._repository = SQLiteCollectionRecordRepository(
            authority.backend.runs,
            run_id=authority.run_id,
        )

    def commit(self, chunk: CollectionChunk) -> CollectionChunkReceipt:
        self._authority.fence()
        prepared = self._repository.prepare_commit(chunk)
        with self._authority.write() as connection:
            receipt, created = self._repository.commit_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self._authority.effect_event(
                    connection,
                    "collection_committed",
                    chunk.operation_id,
                )
            return receipt

    def resolve(self, receipt: CollectionChunkReceipt) -> CollectionChunk:
        self._authority.fence()
        return self._repository.resolve(receipt)

    def receipts(self) -> tuple[CollectionChunkReceipt, ...]:
        self._authority.fence()
        return self._repository.receipts()


class _ManagedPayloads:
    def __init__(self, authority: _ManagedExecutionAuthority) -> None:
        self._authority = authority
        self._repository = SQLitePayloadEvidenceCommitter(
            authority.backend.runs,
            run_id=authority.run_id,
        )

    def commit(self, evidence: PayloadEvidence) -> CommittedPayloadEvidence:
        self._authority.fence()
        prepared = self._repository.prepare_commit(evidence)
        with self._authority.write() as connection:
            committed, created = self._repository.commit_prepared_in_transaction(
                connection,
                prepared,
            )
            if created:
                self._authority.effect_event(
                    connection,
                    "payload_committed",
                    evidence.operation_id,
                )
            return committed


class _UnavailableResources:
    @contextmanager
    def acquire(
        self,
        claims: tuple[ResourceClaim, ...],
    ) -> Generator[None]:
        del claims
        raise RuntimeError("planning services cannot execute a run")
        yield


class _PreclaimedResources:
    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        run_id: str,
        token: str,
        generation: int,
        claims: tuple[ResourceClaim, ...],
    ) -> None:
        self._control = control
        self._run_id = run_id
        self._token = token
        self._generation = generation
        self._claims = claims

    @contextmanager
    def acquire(
        self,
        claims: tuple[ResourceClaim, ...],
    ) -> Generator[None]:
        if claims != self._claims:
            raise RuntimeError("execution claims changed after admission")
        self._control.validate_executor_lease(
            self._run_id,
            token=self._token,
            generation=self._generation,
        )
        yield


__all__ = ["SQLiteDaemonBackend"]
