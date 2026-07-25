from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from fastapi.testclient import TestClient
from scopecat.config.changes import parameter_change_proposal_from_updates
from scopecat.config.drafts import ConfigDraft
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.profiles import load_config_profile
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    DirectConfigRegistrySource,
    ManualConfigDraftRegistrySource,
)
from scopecat.control.models import (
    ControlRun,
    DurableEvent,
    EventPage,
    RunAdmissionRecord,
    RunPage,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigDraftPreview,
    ConfigEntryView,
    ConfigRegistryView,
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
)
from scopecat.daemon.wire import (
    AnalysisNoteOutputPayload,
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
    ConfigDefaultReceipt,
    ConfigDraftCommand,
    ConfigDraftDefaultCommand,
    ConfigDraftDefaultReceipt,
    ConfigDraftRegistrationCommand,
    ConfigDraftRegistrationReceipt,
    ConfigEntryActivationCommand,
    ConfigImportReceipt,
    ConfigRollbackCommand,
    DirectConfigDefaultCommand,
    DirectConfigImportCommand,
    ExecutionRecoveryRequest,
    ExecutionRecoverySnapshot,
    ExecutionTransitionBatch,
    ExecutionTransitionBatchReceipt,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    ExperimentCatalog,
    ManagedRunSubmission,
    MeasurementAppendCommand,
    MeasurementAppendReceipt,
    MeasurementSealCommand,
    MeasurementSealReceipt,
    ParameterProposalDecisionCommand,
    ParameterProposalReviewCommand,
    ParameterProposalReviewReceipt,
    PayloadCommitCommand,
    PayloadCommitReceipt,
    RegisteredExperimentDescriptor,
    ReplaceConfigParameter,
    RunAdmission,
    RunAttachmentCommand,
    RunAttachmentReceipt,
    RunSubmission,
    RuntimeEventPublishCommand,
    RuntimeEventPublishReceipt,
    RuntimeProgressPayload,
    RuntimeTransitionEventPayload,
    TerminalRunCommitCommand,
    TerminalRunCommitReceipt,
)
from scopecat.measurements.results import MeasurementDataset, MeasurementDatasetSchema
from scopecat.records.analysis import AnalysisRecord
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.parameter import Quantity, ScalarParameterValue
from scopecat.records.parameter_change import (
    HumanDecisionAuthority,
    ParameterChangeDecisionRecord,
)
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.records.run_request import RunRequest

from scopecat_server import (
    BackendConflict,
    BackendNotFound,
    DaemonHealth,
    create_app,
)
from scopecat_server.transport import DaemonApplicationContract

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)
_HASH = f"sha256:{'a' * 64}"
_REQUEST = RunRequest(id="request-1")
_CONFIG_FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "core"
    / "simple_scan"
    / "config-profile.json"
)


def _content_entry(
    role: Literal["artifact", "dataset", "record"],
    entry_id: str,
    kind: str,
    *,
    filename: str | None = None,
) -> RunContentEntry:
    return RunContentEntry(
        role=role,
        id=entry_id,
        kind=kind,
        filename=filename,
        content_hash=f"sha256:{entry_id}",
    )


class FakeApplication:
    def __init__(self) -> None:
        self.run = _control_run()
        events = (
            DurableEvent(
                event_id=1,
                run_id="run-1",
                kind="run_admitted",
                payload={"state": "accepted"},
                occurred_at=_NOW,
            ),
            DurableEvent(
                event_id=2,
                run_id="run-1",
                kind="run_state_changed",
                payload={"state": "running"},
                occurred_at=_NOW + timedelta(seconds=1),
            ),
        )
        self.config = FakeConfig()
        self.runs = FakeRuns(run=self.run, events=events)
        self.executor = FakeExecutor(run=self.run)
        self.last_submission: RunSubmission | None = None
        self.last_attention: AttentionResolutionCommand | None = None

    def health(self) -> DaemonHealth:
        return DaemonHealth(
            status="ok",
            project_id="test-project",
            project_name="test-lab",
            project_root="/projects/test-lab",
        )

    def catalog(self) -> ExperimentCatalog:
        return ExperimentCatalog(
            revision="catalog-1",
            experiments=(
                RegisteredExperimentDescriptor(
                    id="ramsey",
                    version="1",
                    experiment_kind="quantum.ramsey",
                    title="Ramsey",
                ),
            ),
        )

    def submit_run(self, submission: RunSubmission) -> RunAdmission:
        if submission.submission_id == "duplicate":
            raise BackendConflict("submission already exists")
        self.last_submission = submission
        return _wire_admission(submission.submission_id)

    def resolve_attention(
        self,
        run_id: str,
        command: AttentionResolutionCommand,
    ) -> AttentionResolutionReceipt:
        assert run_id == self.run.run_id
        self.last_attention = command
        return AttentionResolutionReceipt(
            run_id=run_id,
            action=command.action,
            state="accepted",
            released_resource_count=1,
        )


class FakeConfig:
    def __init__(self) -> None:
        self.last_config_import: DirectConfigImportCommand | None = None
        self.last_config_default: DirectConfigDefaultCommand | None = None
        self.last_config_draft: ConfigDraftCommand | None = None
        self.last_config_draft_default: ConfigDraftDefaultCommand | None = None
        self.last_config_draft_registration: ConfigDraftRegistrationCommand | None = (
            None
        )
        self.last_config_activation: ConfigEntryActivationCommand | None = None
        self.last_config_rollback: ConfigRollbackCommand | None = None
        self.last_candidate: CandidateConfigActivationCommand | None = None

    def get_config_registry(self) -> ConfigRegistryView:
        entry, state = _config_registry_records()
        return ConfigRegistryView(entries=(entry,), active_state=state)

    def get_active_config(self) -> ActiveConfigView:
        entry, state = _config_registry_records()
        return ActiveConfigView(
            entry=entry,
            active_state=state,
            config=_config(),
        )

    def get_config_entry(self, entry_id: str) -> ConfigEntryView:
        entry, _state = _config_registry_records()
        assert entry_id == entry.id
        return ConfigEntryView(entry=entry, config=_config())

    def import_direct_config(
        self,
        command: DirectConfigImportCommand,
    ) -> ConfigImportReceipt:
        self.last_config_import = command
        entry, _state = _config_registry_records()
        return ConfigImportReceipt(entry=entry)

    def set_direct_config_default(
        self,
        command: DirectConfigDefaultCommand,
    ) -> ConfigDefaultReceipt:
        self.last_config_default = command
        entry, state = _config_registry_records()
        return ConfigDefaultReceipt(
            entry=entry,
            active_state=state,
            activation=state.history[-1],
        )

    def preview_config_draft(
        self,
        command: ConfigDraftCommand,
    ) -> ConfigDraftPreview:
        self.last_config_draft = command
        return _config_draft_preview(command)

    def register_config_draft(
        self,
        command: ConfigDraftRegistrationCommand,
    ) -> ConfigDraftRegistrationReceipt:
        self.last_config_draft_registration = command
        preview = _config_draft_preview(command.draft)
        assert preview.result_content_hash is not None
        entry = ConfigRegistryEntry(
            id=command.entry_id,
            config_ref=f"config-registry/entries/{command.entry_id}/config.json",
            content_hash=preview.result_content_hash,
            source=ManualConfigDraftRegistrySource(
                base_entry_id=command.draft.base_entry_id,
                base_config_content_hash=command.draft.base_content_hash,
                base_registry_generation=command.draft.base_generation,
            ),
            registered_by=command.registered_by,
            note=command.note,
        )
        return ConfigDraftRegistrationReceipt(
            entry=entry,
            result_content_hash=preview.result_content_hash,
            deltas=preview.deltas,
        )

    def set_config_draft_default(
        self,
        command: ConfigDraftDefaultCommand,
    ) -> ConfigDraftDefaultReceipt:
        self.last_config_draft_default = command
        entry, state = _config_registry_records()
        preview = _config_draft_preview(command.registration.draft)
        return ConfigDraftDefaultReceipt(
            entry=entry,
            result_content_hash=entry.content_hash,
            deltas=preview.deltas,
            active_state=state,
            activation=state.history[-1],
        )

    def activate_config_entry(
        self,
        command: ConfigEntryActivationCommand,
    ) -> ConfigActivationReceipt:
        self.last_config_activation = command
        _entry, state = _config_registry_records()
        return ConfigActivationReceipt(
            active_state=state,
            activation=state.history[-1],
        )

    def rollback_config(
        self,
        command: ConfigRollbackCommand,
    ) -> ConfigActivationReceipt:
        self.last_config_rollback = command
        _entry, state = _config_registry_records()
        return ConfigActivationReceipt(
            active_state=state,
            activation=state.history[-1],
        )

    def activate_candidate_config(
        self,
        command: CandidateConfigActivationCommand,
    ) -> CandidateConfigActivationReceipt:
        self.last_candidate = command
        entry, state = _config_registry_records()
        return CandidateConfigActivationReceipt(
            entry=entry,
            active_state=state,
            activation=state.history[-1],
        )


class FakeRuns:
    def __init__(
        self,
        *,
        run: ControlRun,
        events: tuple[DurableEvent, ...],
    ) -> None:
        self.run = run
        self.events = events
        self.event_afters: list[int | None] = []
        self.last_analysis: AnalysisSaveCommand | None = None
        self.last_attachment: RunAttachmentCommand | None = None
        self.last_review: ParameterProposalReviewCommand | None = None
        self.last_decision: ParameterProposalDecisionCommand | None = None

    def list_runs(
        self,
        *,
        limit: int,
        after: int | None,
        before: int | None,
        state: str | None,
        latest: bool,
    ) -> RunPage:
        del latest
        if state is not None and state != self.run.state:
            return RunPage(items=())
        if after is not None and after >= self.run.sequence:
            return RunPage(items=())
        if before is not None and before <= self.run.sequence:
            return RunPage(items=())
        return RunPage(items=(self.run,)[:limit])

    def get_run(self, run_id: str) -> RunDetail:
        if run_id != self.run.run_id:
            raise BackendNotFound(f"run was not found: {run_id}")
        return RunDetail(control=self.run, manifest=_accepted_manifest())

    def get_run_config(self, run_id: str) -> RunConfigView:
        assert run_id == self.run.run_id
        config = _config()
        return RunConfigView(
            run_id=run_id,
            config_content_hash=config_content_hash(config),
            config=config,
        )

    def get_run_request(self, run_id: str) -> RunRequestView:
        assert run_id == self.run.run_id
        return RunRequestView(run_id=run_id, request=_REQUEST)

    def list_run_analyses(self, run_id: str) -> RunAnalysisListView:
        return RunAnalysisListView(
            run_id=run_id,
            items=(self.get_run_analysis(run_id, "analysis-fit"),),
        )

    def get_run_analysis(self, run_id: str, selector: str) -> RunAnalysisView:
        assert run_id == self.run.run_id
        assert selector == "analysis-fit"
        return RunAnalysisView(
            run_id=run_id,
            entry=_content_entry("record", selector, "analysis"),
            analysis=AnalysisRecord(
                run_id=run_id,
                title="fit",
                key="fit",
                outputs=[],
            ),
        )

    def save_run_analysis(
        self,
        run_id: str,
        command: AnalysisSaveCommand,
    ) -> AnalysisSaveReceipt:
        assert run_id == self.run.run_id
        self.last_analysis = command
        return AnalysisSaveReceipt(
            record=RunContentEntry(
                role="record",
                id=f"analysis-{command.analysis_key}",
                kind="analysis",
                content_hash="sha256:analysis",
            ),
            analysis_key=command.analysis_key,
            inputs=command.inputs,
        )

    def get_run_artifact_bytes(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactBytesView:
        assert run_id == self.run.run_id
        assert expected_kind == "attachment"
        return RunArtifactBytesView(
            run_id=run_id,
            artifact=_content_entry("artifact", selector, "attachment"),
            content_base64="aGVsbG8=",
        )

    def get_run_artifact_text(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactTextView:
        assert run_id == self.run.run_id
        assert expected_kind == "attachment"
        return RunArtifactTextView(
            run_id=run_id,
            artifact=_content_entry("artifact", selector, "attachment"),
            content="hello",
        )

    def get_run_artifact_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunArtifactJsonView:
        assert run_id == self.run.run_id
        assert expected_kind == "result"
        return RunArtifactJsonView(
            run_id=run_id,
            artifact=_content_entry("artifact", selector, "result"),
            content={"ok": True},
        )

    def get_run_record_json(
        self,
        run_id: str,
        selector: str,
        *,
        expected_kind: str | None,
    ) -> RunRecordJsonView:
        assert run_id == self.run.run_id
        assert expected_kind == "analysis"
        return RunRecordJsonView(
            run_id=run_id,
            record=_content_entry("record", selector, "analysis"),
            content={"run_id": run_id},
        )

    def get_run_dataset_content(
        self,
        run_id: str,
        selector: str,
    ) -> RunDatasetContentView:
        assert run_id == self.run.run_id
        dataset = MeasurementDataset(
            dataset_id=selector,
            schema=MeasurementDatasetSchema(
                dataset_id=selector,
                dataset_role="raw",
            ),
            records=[],
        )
        return RunDatasetContentView(
            run_id=run_id,
            dataset=_content_entry("dataset", selector, "measurement_dataset"),
            content=dataset,
        )

    def attach_run_content(
        self,
        run_id: str,
        command: RunAttachmentCommand,
    ) -> RunAttachmentReceipt:
        assert run_id == self.run.run_id
        self.last_attachment = command
        return RunAttachmentReceipt(
            run_id=run_id,
            artifact=_content_entry(
                "artifact",
                command.key,
                command.kind,
                filename=command.filename,
            ),
        )

    def list_parameter_proposals(self, run_id: str) -> ParameterProposalListView:
        assert run_id == self.run.run_id
        return ParameterProposalListView(
            run_id=run_id,
            items=(ParameterProposalView(proposal=_proposal()),),
        )

    def review_parameter_proposal(
        self,
        run_id: str,
        command: ParameterProposalReviewCommand,
    ) -> ParameterProposalReviewReceipt:
        assert run_id == self.run.run_id
        self.last_review = command
        return ParameterProposalReviewReceipt(
            decision=ParameterChangeDecisionRecord(
                event_id="decision-1",
                run_id=run_id,
                proposal_id=command.proposal_id,
                decision=command.decision,
                authority=HumanDecisionAuthority(actor=command.reviewer),
            )
        )

    def decide_parameter_proposal(
        self,
        run_id: str,
        command: ParameterProposalDecisionCommand,
    ) -> ParameterProposalReviewReceipt:
        assert run_id == self.run.run_id
        self.last_decision = command
        return ParameterProposalReviewReceipt(
            decision=ParameterChangeDecisionRecord(
                event_id="decision-1",
                run_id=run_id,
                proposal_id=command.proposal_id,
                decision=command.decision,
                authority=command.authority,
            )
        )

    def measurements(
        self,
        run_id: str,
        *,
        limit: int,
        offset: int,
    ) -> MeasurementPage:
        assert run_id == self.run.run_id
        assert limit == 10
        assert offset == 5
        return MeasurementPage()

    def list_events(
        self,
        *,
        limit: int,
        after: int | None,
        run_id: str | None,
        latest: bool,
    ) -> EventPage:
        del latest
        self.event_afters.append(after)
        selected = tuple(
            event
            for event in self.events
            if event.event_id > (after or 0)
            and (run_id is None or event.run_id == run_id)
        )
        return EventPage(items=selected[:limit])


class FakeExecutor:
    def __init__(self, *, run: ControlRun) -> None:
        self.run = run
        self.last_start: ExecutorStartRequest | None = None
        self.last_heartbeat: ExecutorHeartbeat | None = None
        self.last_batch: ExecutionTransitionBatch | None = None
        self.last_runtime_event: RuntimeEventPublishCommand | None = None
        self.last_terminal: TerminalRunCommitCommand | None = None

    def start_executor(
        self,
        run_id: str,
        request: ExecutorStartRequest,
    ) -> ExecutorLease:
        if run_id != self.run.run_id:
            raise BackendNotFound(f"run was not found: {run_id}")
        self.last_start = request
        return _executor_lease()

    def heartbeat_executor(
        self,
        run_id: str,
        heartbeat: ExecutorHeartbeat,
    ) -> ExecutorLease:
        assert run_id == self.run.run_id
        if heartbeat.generation != 1:
            raise BackendConflict("executor lease is stale")
        self.last_heartbeat = heartbeat
        return _executor_lease()

    def append_transitions(
        self,
        run_id: str,
        batch: ExecutionTransitionBatch,
    ) -> ExecutionTransitionBatchReceipt:
        assert run_id == self.run.run_id
        self.last_batch = batch
        committed = tuple(
            transition.model_copy(update={"sequence": index})
            for index, transition in enumerate(batch.transitions, start=1)
        )
        return ExecutionTransitionBatchReceipt(
            batch_id=batch.batch_id,
            committed=committed,
        )

    def publish_runtime_event(
        self,
        run_id: str,
        command: RuntimeEventPublishCommand,
    ) -> RuntimeEventPublishReceipt:
        assert run_id == self.run.run_id
        self.last_runtime_event = command
        return RuntimeEventPublishReceipt(
            event_id=3,
            run_id=run_id,
            kind=command.event.kind,
        )

    def recover_execution(
        self,
        run_id: str,
        request: ExecutionRecoveryRequest,
    ) -> ExecutionRecoverySnapshot:
        assert run_id == request.run_id
        return ExecutionRecoverySnapshot()

    def append_measurements(
        self,
        run_id: str,
        command: MeasurementAppendCommand,
    ) -> MeasurementAppendReceipt:
        raise AssertionError((run_id, command))

    def seal_measurements(
        self,
        run_id: str,
        command: MeasurementSealCommand,
    ) -> MeasurementSealReceipt:
        raise AssertionError((run_id, command))

    def commit_collection(
        self,
        run_id: str,
        command: CollectionCommitCommand,
    ) -> CollectionCommitReceipt:
        raise AssertionError((run_id, command))

    def resolve_collection(
        self,
        run_id: str,
        command: CollectionResolveCommand,
    ) -> CollectionResolveReceipt:
        raise AssertionError((run_id, command))

    def commit_payload(
        self,
        run_id: str,
        command: PayloadCommitCommand,
    ) -> PayloadCommitReceipt:
        raise AssertionError((run_id, command))

    def commit_terminal(
        self,
        run_id: str,
        command: TerminalRunCommitCommand,
    ) -> TerminalRunCommitReceipt:
        assert run_id == self.run.run_id
        self.last_terminal = command
        return TerminalRunCommitReceipt(
            command_id=command.command_id,
            manifest=command.manifest,
        )


def test_health_catalog_and_run_queries() -> None:
    backend = FakeApplication()
    checked_backend: DaemonApplicationContract = backend
    client = TestClient(create_app(checked_backend))

    health = client.get("/api/v1/health")
    catalog = client.get("/api/v1/catalog")
    runs = client.get("/api/v1/runs", params={"state": "accepted"})
    older_runs = client.get("/api/v1/runs", params={"before": 1})
    run = client.get("/api/v1/runs/run-1")
    measurements = client.get(
        "/api/v1/runs/run-1/measurements",
        params={"limit": 10, "offset": 5},
    )

    assert health.status_code == 200
    assert health.json() == {
        "status": "ok",
        "project_id": "test-project",
        "project_name": "test-lab",
        "project_root": "/projects/test-lab",
    }
    assert catalog.json()["experiments"][0]["id"] == "ramsey"
    assert runs.json()["items"][0]["admission"]["run_id"] == "run-1"
    assert older_runs.json()["items"] == []
    assert run.json()["control"]["state"] == "accepted"
    assert measurements.json()["items"] == []


def test_run_queries_reject_conflicting_page_modes() -> None:
    client = TestClient(create_app(FakeApplication()))

    both_cursors = client.get(
        "/api/v1/runs",
        params={"after": 1, "before": 2},
    )
    latest_cursor = client.get(
        "/api/v1/runs",
        params={"latest": "true", "before": 2},
    )

    assert both_cursors.status_code == 422
    assert latest_cursor.status_code == 422


def test_config_registry_routes_use_typed_commands_and_views() -> None:
    backend = FakeApplication()
    client = TestClient(create_app(backend))
    config = _config()
    import_command = DirectConfigImportCommand(
        entry_id="baseline",
        config=config,
        registered_by="notebook",
    )
    activation_command = ConfigEntryActivationCommand(
        entry_id="baseline",
        operator="operator",
        expected_generation=0,
    )
    rollback_command = ConfigRollbackCommand(
        operator="operator",
        expected_generation=1,
    )
    base_entry, base_state = _config_registry_records()
    draft_command = ConfigDraftCommand(
        base_entry_id=base_entry.id,
        base_content_hash=base_entry.content_hash,
        base_generation=base_state.generation,
        candidate_id="manual-tuning",
        updates=(
            ReplaceConfigParameter(
                value=ScalarParameterValue(
                    id="drive_frequency",
                    value=Quantity(value=5.1, unit="GHz"),
                )
            ),
        ),
    )
    draft_preview = _config_draft_preview(draft_command)
    assert draft_preview.result_content_hash is not None
    registration_command = ConfigDraftRegistrationCommand(
        draft=draft_command,
        expected_result_content_hash=draft_preview.result_content_hash,
        entry_id="manual-tuning",
        registered_by="operator",
    )

    registry = client.get("/api/v1/config-registry")
    active = client.get("/api/v1/config-registry/active")
    entry = client.get("/api/v1/config-registry/entries/baseline")
    imported = client.post(
        "/api/v1/config-registry/entries",
        json=import_command.model_dump(mode="json"),
    )
    previewed = client.post(
        "/api/v1/config-registry/drafts/preview",
        json=draft_command.model_dump(mode="json"),
    )
    registered = client.post(
        "/api/v1/config-registry/drafts/register",
        json=registration_command.model_dump(mode="json"),
    )
    activated = client.post(
        "/api/v1/config-registry/active",
        json=activation_command.model_dump(mode="json"),
    )
    rolled_back = client.post(
        "/api/v1/config-registry/rollback",
        json=rollback_command.model_dump(mode="json"),
    )

    assert registry.status_code == 200
    assert registry.json()["entries"][0]["id"] == "baseline"
    assert registry.json()["active_state"]["history"][0]["generation"] == 1
    assert active.status_code == 200
    assert active.json()["config"]["id"] == config.id
    assert entry.status_code == 200
    assert entry.json()["entry"]["id"] == "baseline"
    assert entry.json()["config"]["id"] == config.id
    assert imported.status_code == 201
    assert imported.json()["entry"]["id"] == "baseline"
    assert previewed.status_code == 200
    assert previewed.json()["config"]["id"] == "manual-tuning"
    assert registered.status_code == 201
    assert registered.json()["entry"]["id"] == "manual-tuning"
    assert activated.json()["active_state"]["generation"] == 1
    assert rolled_back.status_code == 200
    assert backend.config.last_config_import == import_command
    assert backend.config.last_config_draft == draft_command
    assert backend.config.last_config_draft_registration == registration_command
    assert backend.config.last_config_activation == activation_command
    assert backend.config.last_config_rollback == rollback_command


def test_run_submission_and_backend_error_mapping() -> None:
    backend = FakeApplication()
    client = TestClient(create_app(backend))

    response = client.post("/api/v1/runs", json=_managed_submission("submission-1"))
    conflict = client.post("/api/v1/runs", json=_managed_submission("duplicate"))
    missing = client.get("/api/v1/runs/missing")
    invalid = client.post(
        "/api/v1/runs",
        json={**_managed_submission("invalid"), "unexpected": True},
    )

    assert response.status_code == 201
    assert response.json()["run_id"] == "run-1"
    assert isinstance(backend.last_submission, ManagedRunSubmission)
    assert conflict.status_code == 409
    assert conflict.json() == {"detail": "submission already exists"}
    assert missing.status_code == 404
    assert invalid.status_code == 422


def test_post_run_routes_use_typed_commands_and_views() -> None:
    backend = FakeApplication()
    client = TestClient(create_app(backend))
    analysis = AnalysisSaveCommand(
        run_id="run-1",
        title="fit",
        analysis_key="fit",
        outputs=(
            AnalysisNoteOutputPayload(
                kind="note",
                title="summary",
                content="fit converged",
            ),
        ),
    )
    review = ParameterProposalReviewCommand(
        run_id="run-1",
        proposal_id="drive-frequency",
        decision="approved",
        reviewer="operator",
    )
    candidate = CandidateConfigActivationCommand(
        run_id="run-1",
        proposal_ids=("drive-frequency",),
        entry_id="baseline",
        registered_by="operator",
        operator="operator",
        expected_generation=0,
    )

    config = client.get("/api/v1/runs/run-1/config")
    saved = client.post(
        "/api/v1/runs/run-1/analyses",
        json=analysis.model_dump(mode="json"),
    )
    proposals = client.get("/api/v1/runs/run-1/parameter-proposals")
    reviewed = client.post(
        "/api/v1/runs/run-1/parameter-proposals/drive-frequency/review",
        json=review.model_dump(mode="json"),
    )
    activated = client.post(
        "/api/v1/config-registry/candidates/activate",
        json=candidate.model_dump(mode="json"),
    )
    mismatch = client.post(
        "/api/v1/runs/other/analyses",
        json=analysis.model_dump(mode="json"),
    )

    assert config.json()["config"]["id"] == _config().id
    assert saved.status_code == 201
    assert proposals.json()["items"][0]["proposal"]["id"] == "drive-frequency"
    assert reviewed.json()["decision"]["decision"] == "approved"
    assert activated.json()["entry"]["id"] == "baseline"
    assert mismatch.status_code == 422
    assert backend.runs.last_analysis == analysis
    assert backend.runs.last_review == review
    assert backend.config.last_candidate == candidate


def test_run_content_routes_are_typed_and_run_scoped() -> None:
    backend = FakeApplication()
    client = TestClient(create_app(backend))
    attachment = RunAttachmentCommand(
        run_id="run-1",
        key="notes",
        text="hello",
        filename="notes.txt",
    )

    request = client.get("/api/v1/runs/run-1/request")
    analyses = client.get("/api/v1/runs/run-1/analyses")
    analysis = client.get("/api/v1/runs/run-1/analyses/analysis-fit")
    artifact_bytes = client.get(
        "/api/v1/runs/run-1/artifacts/notes/bytes",
        params={"expected_kind": "attachment"},
    )
    artifact_text = client.get(
        "/api/v1/runs/run-1/artifacts/notes/text",
        params={"expected_kind": "attachment"},
    )
    artifact_json = client.get(
        "/api/v1/runs/run-1/artifacts/result/json",
        params={"expected_kind": "result"},
    )
    record = client.get(
        "/api/v1/runs/run-1/records/analysis-fit/json",
        params={"expected_kind": "analysis"},
    )
    dataset = client.get("/api/v1/runs/run-1/datasets/raw-measurements")
    attached = client.post(
        "/api/v1/runs/run-1/attachments",
        json=attachment.model_dump(mode="json"),
    )
    mismatch = client.post(
        "/api/v1/runs/other/attachments",
        json=attachment.model_dump(mode="json"),
    )

    assert request.json()["request"]["id"] == _REQUEST.id
    assert analyses.json()["items"][0]["analysis"]["key"] == "fit"
    assert analysis.json()["entry"]["id"] == "analysis-fit"
    assert artifact_bytes.json()["content_base64"] == "aGVsbG8="
    assert artifact_text.json()["content"] == "hello"
    assert artifact_json.json()["content"] == {"ok": True}
    assert record.json()["content"] == {"run_id": "run-1"}
    assert dataset.json()["content"]["dataset_id"] == "raw-measurements"
    assert attached.status_code == 201
    assert attached.json()["artifact"]["filename"] == "notes.txt"
    assert mismatch.status_code == 422
    assert backend.runs.last_attachment == attachment


def test_attention_resolution_route() -> None:
    backend = FakeApplication()
    client = TestClient(create_app(backend))
    command = AttentionResolutionCommand(run_id="run-1", action="requeue")

    response = client.post(
        "/api/v1/runs/run-1/attention",
        json=command.model_dump(mode="json"),
    )

    assert response.status_code == 200
    assert response.json()["state"] == "accepted"
    assert backend.last_attention == command


def test_event_replay_and_sse_resume_from_durable_event_id() -> None:
    backend = FakeApplication()
    client = TestClient(create_app(backend))

    replay = client.get("/api/v1/events", params={"after": 1, "run_id": "run-1"})
    stream = client.get(
        "/api/v1/events/stream",
        params={"follow": "false"},
        headers={"Last-Event-ID": "1"},
    )
    reconnect = client.get(
        "/api/v1/events/stream",
        params={"after": 0, "follow": "false"},
        headers={"Last-Event-ID": "2"},
    )

    assert [item["event_id"] for item in replay.json()["items"]] == [2]
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "id: 2\nevent: project\ndata: " in stream.text
    assert '"event_id":2' in stream.text
    assert reconnect.text == ""
    assert backend.runs.event_afters[-1] == 2


def test_delegated_executor_routes() -> None:
    backend = FakeApplication()
    client = TestClient(create_app(backend))
    transition = _transition()
    runtime_event = RuntimeEventPublishCommand(
        run_id="run-1",
        lease_id="lease-1",
        generation=1,
        event=RuntimeTransitionEventPayload(
            run_id="run-1",
            experiment_id="scratch",
            observed_at=_NOW + timedelta(seconds=2),
            occurred_at=_NOW + timedelta(seconds=1),
            operation_id="point-1",
            stage="point",
            effect="acquisition",
            state="completed",
            progress=RuntimeProgressPayload(
                completed_points=1,
                total_points=2,
            ),
            point_index=0,
            point_indices=(0,),
            instrument_id="scope-1",
            metrics={"measurement_count": 1},
        ),
    )
    terminal = _terminal_command()

    lease = client.post(
        "/api/v1/runs/run-1/executor/start",
        json=ExecutorStartRequest(
            run_id="run-1",
            executor_id="notebook-1",
            manifest=_running_manifest(),
        ).model_dump(mode="json"),
    )
    heartbeat = client.post(
        "/api/v1/runs/run-1/executor/heartbeat",
        json=ExecutorHeartbeat(
            run_id="run-1",
            lease_id="lease-1",
            generation=1,
        ).model_dump(mode="json"),
    )
    transitions = client.post(
        "/api/v1/runs/run-1/transitions",
        json=ExecutionTransitionBatch(
            batch_id="batch-1",
            lease_id="lease-1",
            generation=1,
            run_id="run-1",
            transitions=(transition,),
        ).model_dump(mode="json"),
    )
    published = client.post(
        "/api/v1/runs/run-1/runtime-events",
        json=runtime_event.model_dump(mode="json"),
    )
    completed = client.post(
        "/api/v1/runs/run-1/terminal",
        json=terminal.model_dump(mode="json"),
    )

    assert lease.status_code == 200
    assert heartbeat.status_code == 200
    assert transitions.json()["committed"][0]["sequence"] == 1
    assert published.status_code == 200
    assert published.json()["event_id"] == 3
    assert completed.json()["manifest"]["lifecycle"] == "terminal"
    assert backend.executor.last_start is not None
    assert backend.executor.last_heartbeat is not None
    assert backend.executor.last_batch is not None
    assert backend.executor.last_runtime_event == runtime_event
    assert backend.executor.last_terminal == terminal


def test_delegated_path_and_body_run_ids_must_match() -> None:
    backend = FakeApplication()
    client = TestClient(create_app(backend))

    response = client.post(
        "/api/v1/runs/other/executor/start",
        json=ExecutorStartRequest(
            run_id="run-1",
            executor_id="notebook-1",
            manifest=_running_manifest(),
        ).model_dump(mode="json"),
    )

    assert response.status_code == 422
    assert backend.executor.last_start is None


def test_static_dist_serves_files_and_spa_without_shadowing_api(
    tmp_path: Path,
) -> None:
    (tmp_path / "index.html").write_text("<main>Scopecat GUI</main>")
    (tmp_path / "app.js").write_text("window.SCOPECAT = true")
    client = TestClient(create_app(FakeApplication(), static_dir=tmp_path))

    assert client.get("/").text == "<main>Scopecat GUI</main>"
    assert client.get("/runs/run-1").text == "<main>Scopecat GUI</main>"
    assert client.get("/app.js").text == "window.SCOPECAT = true"
    assert client.get("/api/v1/health").status_code == 200
    assert client.get("/api/v1/unknown").status_code == 404


def _control_run() -> ControlRun:
    return ControlRun(
        sequence=1,
        admission=RunAdmissionRecord(
            submission_id="submission-1",
            run_id="run-1",
            execution_mode="delegated",
            experiment_id="scratch",
            config_content_hash=_HASH,
            request=_REQUEST,
            admitted_at=_NOW,
        ),
        state="accepted",
        state_version=1,
        updated_at=_NOW,
    )


def _config() -> ConfigProfileSnapshot:
    return load_config_profile(_CONFIG_FIXTURE)


def _config_registry_records() -> tuple[
    ConfigRegistryEntry,
    ConfigRegistryActiveState,
]:
    config = _config()
    entry = ConfigRegistryEntry(
        id="baseline",
        config_ref="config-registry/entries/baseline/config.json",
        content_hash=config_content_hash(config),
        source=DirectConfigRegistrySource(),
        registered_by="notebook",
        registered_at=_NOW,
    )
    activation = ConfigRegistryActivationRecord(
        id="activation-1",
        generation=1,
        action="activation",
        entry_id=entry.id,
        entry_content_hash=entry.content_hash,
        operator="operator",
        recorded_at=_NOW,
    )
    state = ConfigRegistryActiveState(
        generation=1,
        active_entry_id=entry.id,
        active_entry_content_hash=entry.content_hash,
        history=(activation,),
        updated_at=_NOW,
    )
    return entry, state


def _config_draft_preview(command: ConfigDraftCommand) -> ConfigDraftPreview:
    base_entry, _state = _config_registry_records()
    check = (
        ConfigDraft(_config())
        .replace_scalar(
            "drive_frequency",
            Quantity(value=5.1, unit="GHz"),
        )
        .check(candidate_id=command.candidate_id)
    )
    assert check.candidate is not None
    result_content_hash = config_content_hash(check.candidate)
    return ConfigDraftPreview(
        valid=True,
        base_entry=base_entry,
        base_generation=command.base_generation,
        base_content_hash=command.base_content_hash,
        config=check.candidate,
        result_content_hash=result_content_hash,
        deltas=check.deltas,
        problems=check.problems,
    )


def _proposal():
    return parameter_change_proposal_from_updates(
        source_run_id="run-1",
        source_config=_config(),
        analysis_title="fit",
        analysis_record_id="analysis-fit",
        proposal_id="drive-frequency",
        updates=(
            replace_scalar_parameter(
                "drive_frequency",
                Quantity(value=5.1, unit="GHz"),
            ),
        ),
        reason="fit converged",
        confidence=0.9,
    )


def _wire_admission(submission_id: str) -> RunAdmission:
    return RunAdmission(
        run_id="run-1",
        submission_id=submission_id,
        execution_mode="managed",
        config_content_hash=_HASH,
        accepted_at=_NOW,
        event_cursor=1,
    )


def _managed_submission(submission_id: str) -> dict[str, object]:
    return ManagedRunSubmission(
        submission_id=submission_id,
        registration_id="ramsey",
        registration_version="1",
        request=_REQUEST,
    ).model_dump(mode="json")


def _executor_lease() -> ExecutorLease:
    return ExecutorLease(
        lease_id="lease-1",
        generation=1,
        run_id="run-1",
        executor_id="notebook-1",
        issued_at=_NOW,
        expires_at=_NOW + timedelta(seconds=30),
        heartbeat_interval_seconds=10,
    )


def _transition() -> ExecutionTransition:
    return ExecutionTransition(
        run_id="run-1",
        operation_id="operation-1",
        stage="compute",
        effect="pure",
        state="completed",
    )


def _running_manifest() -> RunManifest:
    return RunManifest(
        run_id="run-1",
        created_at=_NOW,
        lifecycle="running",
        config_content_hash=_HASH,
    )


def _accepted_manifest() -> RunManifest:
    return RunManifest(
        run_id="run-1",
        created_at=_NOW,
        lifecycle="accepted",
        config_content_hash=_HASH,
    )


def _terminal_manifest() -> RunManifest:
    outcome = RunOutcome(
        run_id="run-1",
        result="succeeded",
        certainty="known",
        termination_reason="completed",
        finished_at=_NOW + timedelta(seconds=2),
    )
    return RunManifest(
        run_id="run-1",
        created_at=_NOW,
        lifecycle="terminal",
        config_content_hash=_HASH,
        outcome=outcome,
    )


def _terminal_command() -> TerminalRunCommitCommand:
    return TerminalRunCommitCommand(
        command_id="terminal:run-1",
        run_id="run-1",
        lease_id="lease-1",
        generation=1,
        manifest=_terminal_manifest(),
    )
