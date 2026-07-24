"""Notebook-facing client connection to one local Scopecat project daemon."""

from __future__ import annotations

from base64 import b64encode
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from threading import Event, Lock, Thread
from types import TracebackType
from typing import Literal, Self, cast, override
from uuid import uuid4

from pydantic import JsonValue, RootModel, TypeAdapter

from scopecat.analysis.service import (
    AnalysisArtifactSpec,
    AnalysisInput,
    AnalysisOutput,
    SavedAnalysis,
)
from scopecat.authoring import MetadataValue
from scopecat.authoring.templates import ExperimentInvocation
from scopecat.compiler.frontend.invocation import (
    PreparedInvocation,
    prepare_invocation,
)
from scopecat.config.candidates import CandidateConfig
from scopecat.config.drafts import ConfigDraft
from scopecat.config.parameter_updates import (
    InsertParameterRows,
    ParameterUpdate,
    ReplaceParameter,
    UpdateParameterRows,
)
from scopecat.control.models import (
    ControlRunState,
    EventPage,
    RunPage,
)
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.execution import (
    DelegatedLeaseSupervisor,
    delegated_execution_services,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigDraftPreview,
    ConfigEntryView,
    ConfigRegistryView,
    DaemonHealth,
    MeasurementPage,
    ParameterProposalListView,
    RunAnalysisListView,
    RunAnalysisView,
    RunConfigView,
    RunDetail,
)
from scopecat.daemon.wire import (
    AnalysisArtifactOutputPayload,
    AnalysisInputPayload,
    AnalysisJsonOutputPayload,
    AnalysisNoteOutputPayload,
    AnalysisOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    AttentionResolutionAction,
    AttentionResolutionReceipt,
    CandidateConfigActivationCommand,
    CandidateConfigActivationReceipt,
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
    ExecutorLease,
    ExperimentCatalog,
    InsertConfigParameterRows,
    ManagedRunSubmission,
    ParameterProposalReviewCommand,
    ParameterProposalReviewReceipt,
    ReplaceConfigParameter,
    ResourceClaimDescriptor,
    RunAdmission,
    RunAttachmentCommand,
    UpdateConfigParameterRows,
)
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.execution.observation import RuntimeEventSink, RuntimePayloadObserver
from scopecat.measurements.results import MeasurementDataset
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.preview_models import ExperimentPreview
from scopecat.planning.system import (
    ExperimentSystemBuilder,
    build_experiment_system,
)
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.data_artifact import DataArrayArtifact, DataTableArtifact
from scopecat.records.parameter_change import (
    ParameterChangeProposal,
    ParameterChangeReviewState,
)
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.data import (
    RunArtifactBytesResult,
    RunArtifactJsonResult,
    RunArtifactTextResult,
    RunDataArrayResult,
    RunDataTableResult,
    RunMeasurementDatasetResult,
    RunRecordJsonResult,
)
from scopecat.runs.service import PlannedRun, plan_scratch_experiment


class DelegatedExecutorLeaseLostError(RuntimeError):
    """A delegated executor can no longer commit effects to its run."""

    def __init__(self, lease: ExecutorLease, cause: Exception) -> None:
        super().__init__(
            f"delegated executor for run {lease.run_id!r} generation "
            f"{lease.generation} is no longer live: {cause}"
        )
        self.lease = lease
        self.cause = cause


class DaemonConnection:
    """Synchronous project-daemon connection for operator and execution APIs."""

    def __init__(
        self,
        daemon: str | DaemonClient,
        *,
        build_system: ExperimentSystemBuilder | None = None,
    ) -> None:
        self._owns_client = isinstance(daemon, str)
        self._client = DaemonClient(daemon) if isinstance(daemon, str) else daemon
        self._build_system = build_system

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def health(self) -> DaemonHealth:
        return self._client.health()

    def catalog(self) -> ExperimentCatalog:
        return self._client.catalog()

    def config_registry(self) -> ConfigRegistryView:
        return self._client.config_registry()

    def active_config(self) -> ActiveConfigView:
        return self._client.active_config()

    def config_entry(self, entry_id: str) -> ConfigEntryView:
        return self._client.config_entry(entry_id)

    def import_direct_config(
        self,
        config: ConfigProfileSnapshot,
        *,
        entry_id: str,
        registered_by: str,
        note: str = "",
    ) -> ConfigImportReceipt:
        return self._client.import_direct_config(
            DirectConfigImportCommand(
                entry_id=entry_id,
                config=config,
                registered_by=registered_by,
                note=note,
            )
        )

    def preview_config_draft(
        self,
        draft: ConfigDraft,
        *,
        candidate_id: str | None = None,
    ) -> ConfigDraftPreview:
        active = self.active_config()
        if draft.base_content_hash != active.entry.content_hash:
            raise ValueError("config draft base is no longer the active configuration")
        return self._client.preview_config_draft(
            ConfigDraftCommand(
                base_entry_id=active.entry.id,
                base_content_hash=active.entry.content_hash,
                base_generation=active.active_state.generation,
                candidate_id=candidate_id or f"{active.config.id}.draft",
                updates=_config_parameter_updates(draft.updates),
            )
        )

    def register_config_draft(
        self,
        draft: ConfigDraft,
        *,
        preview: ConfigDraftPreview,
        entry_id: str,
        registered_by: str,
        note: str = "",
    ) -> ConfigDraftRegistrationReceipt:
        if (
            not preview.valid
            or preview.config is None
            or preview.result_content_hash is None
        ):
            raise ValueError("only a valid config draft preview can be registered")
        if draft.base_content_hash != preview.base_content_hash:
            raise ValueError("config draft does not match its reviewed preview base")
        return self._client.register_config_draft(
            ConfigDraftRegistrationCommand(
                draft=ConfigDraftCommand(
                    base_entry_id=preview.base_entry.id,
                    base_content_hash=preview.base_content_hash,
                    base_generation=preview.base_generation,
                    candidate_id=preview.config.id,
                    updates=_config_parameter_updates(draft.updates),
                ),
                expected_result_content_hash=preview.result_content_hash,
                entry_id=entry_id,
                registered_by=registered_by,
                note=note,
            )
        )

    def activate_config_entry(
        self,
        entry_id: str,
        *,
        operator: str,
        expected_generation: int | None = None,
        note: str = "",
    ) -> ConfigActivationReceipt:
        generation = (
            self._config_generation()
            if expected_generation is None
            else expected_generation
        )
        return self._client.activate_config_entry(
            ConfigEntryActivationCommand(
                entry_id=entry_id,
                operator=operator,
                expected_generation=generation,
                note=note,
            )
        )

    def rollback_config(
        self,
        *,
        operator: str,
        expected_generation: int,
        note: str = "",
    ) -> ConfigActivationReceipt:
        return self._client.rollback_config(
            ConfigRollbackCommand(
                operator=operator,
                expected_generation=expected_generation,
                note=note,
            )
        )

    def activate_candidate_config(
        self,
        candidate: CandidateConfig,
        *,
        entry_id: str | None = None,
        registered_by: str,
        operator: str,
        expected_generation: int | None = None,
        note: str = "",
        activation_note: str | None = None,
    ) -> CandidateConfigActivationReceipt:
        generation = (
            self._config_generation()
            if expected_generation is None
            else expected_generation
        )
        return self._client.activate_candidate_config(
            CandidateConfigActivationCommand(
                run_id=candidate.source_run_id,
                proposal_ids=candidate.proposal_ids,
                entry_id=entry_id,
                registered_by=registered_by,
                operator=operator,
                expected_generation=generation,
                note=note,
                activation_note=activation_note,
            )
        )

    def runs(
        self,
        *,
        limit: int = 50,
        after: int | None = None,
        state: ControlRunState | None = None,
        latest: bool = True,
    ) -> RunPage:
        return self._client.list_runs(
            limit=limit,
            after=after,
            state=state,
            latest=latest,
        )

    def get_run(self, run_id: str) -> RunDetail:
        return self._client.get_run(run_id)

    def run_config(self, run_id: str) -> RunConfigView:
        return self._client.run_config(run_id)

    def run_request(self, run_id: str) -> RunRequest | None:
        return self._client.run_request(run_id).request

    def analyses(self, run_id: str) -> RunAnalysisListView:
        return self._client.analyses(run_id)

    def analysis(self, run_id: str, selector: str) -> RunAnalysisView:
        return self._client.analysis(run_id, selector)

    def attach(
        self,
        *,
        run_id: str,
        path: str | Path | None = None,
        key: str,
        kind: str = "attachment",
        text: str | None = None,
        content: bytes | None = None,
        filename: str | None = None,
        media_type: str | None = None,
        metadata: Mapping[str, JsonValue] | None = None,
    ) -> RunContentEntry:
        source_path = None if path is None else Path(path)
        if source_path is not None:
            if text is not None or content is not None:
                raise ValueError("run attachment requires exactly one content source")
            content = source_path.read_bytes()
            filename = filename or source_path.name
        encoded = None if content is None else b64encode(content).decode("ascii")
        return self._client.attach(
            RunAttachmentCommand(
                run_id=run_id,
                key=key,
                kind=kind,
                text=text,
                content_base64=encoded,
                filename=filename,
                media_type=media_type,
                metadata=dict(metadata or {}),
            )
        ).artifact

    def artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactBytesResult:
        view = self._client.artifact_bytes(
            run_id,
            selector,
            expected_kind=expected_kind,
        )
        return RunArtifactBytesResult(
            artifact=view.artifact,
            content=view.content_bytes(),
        )

    def artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactTextResult:
        view = self._client.artifact_text(
            run_id,
            selector,
            expected_kind=expected_kind,
        )
        return RunArtifactTextResult(artifact=view.artifact, content=view.content)

    def artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunArtifactJsonResult:
        view = self._client.artifact_json(
            run_id,
            selector,
            expected_kind=expected_kind,
        )
        return RunArtifactJsonResult(artifact=view.artifact, content=view.content)

    def record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None = None,
    ) -> RunRecordJsonResult:
        view = self._client.record_json(
            run_id,
            selector,
            expected_kind=expected_kind,
        )
        return RunRecordJsonResult(record=view.record, content=view.content)

    def measurement_dataset(
        self,
        run_id: str,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        view = self._client.dataset_content(run_id, selector)
        if not isinstance(view.content, MeasurementDataset):
            raise ValueError("run dataset is not a measurement dataset")
        return RunMeasurementDatasetResult(
            dataset_entry=view.dataset,
            dataset=view.content,
        )

    def data_table(self, run_id: str, selector: str) -> RunDataTableResult:
        view = self._client.dataset_content(run_id, selector)
        if not isinstance(view.content, DataTableArtifact):
            raise ValueError("run dataset is not a data table")
        return RunDataTableResult(dataset_entry=view.dataset, table=view.content)

    def data_array(self, run_id: str, selector: str) -> RunDataArrayResult:
        view = self._client.dataset_content(run_id, selector)
        if not isinstance(view.content, DataArrayArtifact):
            raise ValueError("run dataset is not a data array")
        return RunDataArrayResult(dataset_entry=view.dataset, array=view.content)

    def save_analysis(
        self,
        *,
        run_id: str,
        title: str,
        analysis_key: str,
        step_id: str | None,
        inputs: Sequence[AnalysisInput],
        outputs: Sequence[AnalysisOutput],
        parameter_proposals: Sequence[ParameterChangeProposal],
    ) -> SavedAnalysis:
        payloads = tuple(_analysis_output_payload(output) for output in outputs)
        output_proposals = tuple(
            payload.content
            for payload in payloads
            if isinstance(payload, AnalysisParameterProposalOutputPayload)
        )
        if output_proposals != tuple(parameter_proposals):
            raise ValueError("analysis parameter proposals must match proposal outputs")
        receipt = self._client.save_analysis(
            AnalysisSaveCommand(
                run_id=run_id,
                title=title,
                analysis_key=analysis_key,
                step_id=step_id,
                inputs=tuple(_analysis_input_payload(item) for item in inputs),
                outputs=payloads,
            )
        )
        return SavedAnalysis(
            record=receipt.record,
            analysis_key=receipt.analysis_key,
            inputs=tuple(inputs),
            output_artifacts=receipt.output_artifacts,
        )

    def parameter_proposals(self, run_id: str) -> ParameterProposalListView:
        return self._client.parameter_proposals(run_id)

    def review_parameter_proposal(
        self,
        run_id: str,
        proposal_id: str,
        *,
        reviewer: str,
        decision: ParameterChangeReviewState = "approved",
        note: str = "",
    ) -> ParameterProposalReviewReceipt:
        return self._client.review_parameter_proposal(
            ParameterProposalReviewCommand(
                run_id=run_id,
                proposal_id=proposal_id,
                decision=decision,
                reviewer=reviewer,
                note=note,
            )
        )

    def resolve_attention(
        self,
        run_id: str,
        action: AttentionResolutionAction,
    ) -> AttentionResolutionReceipt:
        """Release, requeue, or abort a quarantined run."""

        return self._client.resolve_attention(run_id, action)

    def measurements(
        self,
        run_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> MeasurementPage:
        return self._client.measurements(run_id, limit=limit, offset=offset)

    def events(
        self,
        *,
        limit: int = 100,
        after: int | None = None,
        run_id: str | None = None,
        latest: bool = True,
    ) -> EventPage:
        return self._client.replay_events(
            limit=limit,
            after=after,
            run_id=run_id,
            latest=latest,
        )

    def submit_managed(
        self,
        registration_id: str,
        registration_version: str,
        request: RunRequest,
        *,
        submission_id: str | None = None,
    ) -> RunAdmission:
        return self._client.submit_managed(
            ManagedRunSubmission(
                submission_id=submission_id or uuid4().hex,
                registration_id=registration_id,
                registration_version=registration_version,
                request=request,
            )
        )

    def execute_delegated(
        self,
        planned: PlannedRun,
        *,
        executor_id: str = "notebook",
        submission_id: str | None = None,
        event_sink: RuntimeEventSink | None = None,
        payload_observer: RuntimePayloadObserver | None = None,
    ) -> RunManifest:
        """Admit a plan remotely while executing its Python closures locally."""

        if planned.request is None:
            raise ValueError("delegated execution requires a durable run request")
        submission = DelegatedRunSubmission(
            submission_id=submission_id or uuid4().hex,
            executor_id=executor_id,
            config=planned.config,
            request=planned.request,
            plan=_delegated_plan_summary(planned),
        )
        admission = self._client.submit_delegated(submission)
        lease_heartbeat = _LeaseHeartbeat()
        services = delegated_execution_services(
            self._client,
            submission,
            admission,
            lease_supervisor=lease_heartbeat,
        )
        try:
            return execute_admitted_run(
                run_id=admission.run_id,
                program=planned.program,
                services=services,
                instrument_provider=(
                    None if planned.system is None else planned.system.provider
                ),
                event_sink=event_sink,
                payload_observer=payload_observer,
            )
        finally:
            lease_heartbeat.close()

    def run_scratch(
        self,
        experiment: ExperimentInvocation | PreparedInvocation,
        *,
        config: ConfigProfileSnapshot | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
        executor_id: str = "notebook",
        submission_id: str | None = None,
        event_sink: RuntimeEventSink | None = None,
        payload_observer: RuntimePayloadObserver | None = None,
    ) -> RunManifest:
        """Plan notebook code locally and persist all run effects through the daemon."""

        planned = self._plan_scratch(
            experiment,
            config=config,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return self.execute_delegated(
            planned,
            executor_id=executor_id,
            submission_id=submission_id,
            event_sink=event_sink,
            payload_observer=payload_observer,
        )

    def preview_scratch(
        self,
        experiment: ExperimentInvocation | PreparedInvocation,
        *,
        config: ConfigProfileSnapshot | None = None,
        name: str | None = None,
        tags: tuple[str, ...] = (),
        description: str | None = None,
        metadata: Mapping[str, MetadataValue] | None = None,
        operator: str | None = None,
    ) -> ExperimentPreview:
        """Plan notebook code without admission or durable effects."""

        planned = self._plan_scratch(
            experiment,
            config=config,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return build_run_program_preview(planned.program)

    def _plan_scratch(
        self,
        experiment: ExperimentInvocation | PreparedInvocation,
        *,
        config: ConfigProfileSnapshot | None,
        name: str | None,
        tags: tuple[str, ...],
        description: str | None,
        metadata: Mapping[str, MetadataValue] | None,
        operator: str | None,
    ) -> PlannedRun:
        selected_config = self.active_config().config if config is None else config
        selected_system = build_experiment_system(
            self._build_system,
            selected_config,
        )
        if selected_system is None:
            raise ValueError("scratch execution requires an experiment system")
        prepared = (
            experiment
            if isinstance(experiment, PreparedInvocation)
            else prepare_invocation(experiment)
        )
        prepared = _prepared_invocation_with_metadata(
            prepared,
            name=name,
            tags=tags,
            description=description,
            metadata=metadata,
            operator=operator,
        )
        return plan_scratch_experiment(
            prepared,
            config=selected_config,
            system=selected_system,
        )

    def _config_generation(self) -> int:
        state = self.config_registry().active_state
        return 0 if state is None else state.generation


def _config_parameter_updates(
    updates: Sequence[ParameterUpdate],
) -> tuple[
    ReplaceConfigParameter
    | UpdateConfigParameterRows
    | InsertConfigParameterRows
    | DeleteConfigParameterRows,
    ...,
]:
    payloads: list[
        ReplaceConfigParameter
        | UpdateConfigParameterRows
        | InsertConfigParameterRows
        | DeleteConfigParameterRows
    ] = []
    for update in updates:
        if isinstance(update, ReplaceParameter):
            payloads.append(ReplaceConfigParameter(value=update.value))
        elif isinstance(update, UpdateParameterRows):
            payloads.append(
                UpdateConfigParameterRows(
                    parameter_id=update.parameter_id,
                    key=dict(update.key),
                    values=dict(update.values),
                )
            )
        elif isinstance(update, InsertParameterRows):
            payloads.append(
                InsertConfigParameterRows(
                    parameter_id=update.parameter_id,
                    rows=tuple(dict(row) for row in update.rows),
                )
            )
        else:
            payloads.append(
                DeleteConfigParameterRows(
                    parameter_id=update.parameter_id,
                    key=dict(update.key),
                )
            )
    return tuple(payloads)


_JSON_MAPPING = TypeAdapter(dict[str, JsonValue])


class _JsonValue(RootModel[JsonValue]):
    pass


def _prepared_invocation_with_metadata(
    prepared: PreparedInvocation,
    *,
    name: str | None,
    tags: tuple[str, ...],
    description: str | None,
    metadata: Mapping[str, MetadataValue] | None,
    operator: str | None,
) -> PreparedInvocation:
    selected_metadata = dict(prepared.request_context.metadata)
    selected_metadata.update(metadata or {})
    if name is not None:
        selected_metadata["name"] = name
    if tags:
        selected_metadata["tags"] = list(tags)
    if description is not None:
        selected_metadata["description"] = description
    return replace(
        prepared,
        request_context=replace(
            prepared.request_context,
            metadata=selected_metadata,
            operator=(
                prepared.request_context.operator if operator is None else operator
            ),
        ),
    )


def _analysis_input_payload(value: AnalysisInput) -> AnalysisInputPayload:
    return AnalysisInputPayload(
        target=value.target,
        kind=value.kind,
        role=value.role,
        title=value.title,
        metadata=(
            None
            if value.metadata is None
            else _JSON_MAPPING.validate_python(value.metadata)
        ),
    )


def _analysis_output_payload(value: AnalysisOutput) -> AnalysisOutputPayload:
    metadata = _JSON_MAPPING.validate_python(value.metadata)
    if value.kind == "note":
        if not isinstance(value.content, str):
            raise ValueError("remote analysis note content must be text")
        return AnalysisNoteOutputPayload(
            kind=value.kind,
            title=value.title,
            content=value.content,
            metadata=metadata,
        )
    if value.kind in {"table", "array", "figure"}:
        return AnalysisJsonOutputPayload(
            kind=cast("Literal['table', 'array', 'figure']", value.kind),
            title=value.title,
            content=_JsonValue.model_validate(value.content).root,
            metadata=metadata,
        )
    if value.kind == "artifact":
        if not isinstance(value.content, AnalysisArtifactSpec):
            raise ValueError("remote analysis artifact output has invalid content")
        return AnalysisArtifactOutputPayload(
            kind=value.kind,
            title=value.title,
            artifact_kind=value.content.kind,
            content_base64=b64encode(value.content.content_bytes()).decode("ascii"),
            artifact_id=value.content.artifact_id,
            filename=value.content.filename,
            media_type=value.content.media_type,
            source_default_filename=value.content.source_default_filename(),
            source_default_extension=value.content.source_default_extension(),
            source_default_media_type=value.content.source_default_media_type(),
            source_content_hash=value.content.source_content_hash(),
            artifact_metadata=_JSON_MAPPING.validate_python(value.content.metadata),
            metadata=metadata,
        )
    if value.kind == "parameter_change_proposal":
        if not isinstance(value.content, ParameterChangeProposal):
            raise ValueError("remote analysis proposal output has invalid content")
        return AnalysisParameterProposalOutputPayload(
            kind=value.kind,
            title=value.title,
            content=value.content,
            metadata=metadata,
        )
    raise ValueError(
        "remote analysis supports note, table, array, figure, artifact, "
        "and parameter change proposal outputs"
    )


def connect(
    daemon: str,
    *,
    build_system: ExperimentSystemBuilder | None = None,
) -> DaemonConnection:
    """Connect low-level notebook code to an explicit daemon endpoint."""

    return DaemonConnection(daemon, build_system=build_system)


class _LeaseHeartbeat(DelegatedLeaseSupervisor):
    def __init__(self) -> None:
        self._stop = Event()
        self._lock = Lock()
        self._failure: tuple[ExecutorLease, Exception] | None = None
        self._thread: Thread | None = None

    @override
    def start(
        self,
        lease: ExecutorLease,
        heartbeat: Callable[[], ExecutorLease],
    ) -> None:
        self._thread = Thread(
            target=self._run,
            args=(lease, heartbeat),
            name=f"scopecat-lease-{lease.run_id}",
            daemon=True,
        )
        self._thread.start()

    @override
    def require_live(self) -> None:
        with self._lock:
            failure = self._failure
        if failure is not None:
            lease, cause = failure
            raise DelegatedExecutorLeaseLostError(lease, cause) from cause

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join()

    def _run(
        self,
        lease: ExecutorLease,
        heartbeat: Callable[[], ExecutorLease],
    ) -> None:
        current = lease
        while not self._stop.wait(current.heartbeat_interval_seconds):
            try:
                current = heartbeat()
            except Exception as error:
                with self._lock:
                    self._failure = (current, error)
                return


def _delegated_plan_summary(planned: PlannedRun) -> DelegatedPlanSummary:
    preview = build_run_program_preview(planned.program)
    return DelegatedPlanSummary(
        experiment_id=preview.experiment_id,
        experiment_kind=preview.experiment_kind,
        point_count=preview.point_count,
        coordinate_ids=preview.coordinate_ids,
        record_ids=tuple(record.id for record in preview.records),
        run_resource_claims=tuple(
            ResourceClaimDescriptor(id=claim.id, kind=claim.kind)
            for claim in planned.program.resource_claims
        ),
    )


__all__ = ["DaemonConnection", "DelegatedExecutorLeaseLostError", "connect"]
