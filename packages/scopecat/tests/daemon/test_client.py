from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

import httpx
import pytest
from pydantic import BaseModel

from scopecat.config.changes import parameter_change_proposal_from_updates
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    DirectConfigRegistrySource,
)
from scopecat.control.models import (
    ControlRun,
    DurableEvent,
    EventPage,
    RunAdmissionRecord,
    RunPage,
)
from scopecat.daemon import (
    AttentionResolutionReceipt,
    DaemonClient,
    DaemonConflictError,
    DaemonNotFoundError,
    DelegatedPlanSummary,
    DelegatedRunSubmission,
    ExecutionTransitionBatch,
    ExecutionTransitionBatchReceipt,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    ExperimentCatalog,
    ManagedRunSubmission,
    MeasurementPage,
    RegisteredExperimentDescriptor,
    RunAdmission,
    RunDetail,
    TerminalRunCommitCommand,
    TerminalRunCommitReceipt,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigEntryView,
    ConfigRegistryView,
    ParameterProposalListView,
    ParameterProposalView,
    RunAnalysisListView,
    RunAnalysisView,
    RunArtifactBytesView,
    RunArtifactJsonView,
    RunArtifactTextView,
    RunConfigView,
    RunDatasetContentView,
    RunRecordJsonView,
    RunRequestView,
)
from scopecat.daemon.wire import (
    AnalysisNoteOutputPayload,
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
    CandidateConfigActivationCommand,
    CandidateConfigActivationReceipt,
    ConfigActivationReceipt,
    ConfigEntryActivationCommand,
    ConfigImportReceipt,
    ConfigRollbackCommand,
    DirectConfigImportCommand,
    ParameterProposalReviewCommand,
    ParameterProposalReviewReceipt,
    RunAttachmentCommand,
    RunAttachmentReceipt,
)
from scopecat.measurements.results import MeasurementDataset, MeasurementDatasetSchema
from scopecat.records.analysis import AnalysisRecord
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import config_content_hash
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.parameter import Quantity
from scopecat.records.parameter_change import ParameterChangeDecisionRecord
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.records.run_request import RunRequest
from tests.testkit.workflow_fixtures import load_config

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)
_HASH = f"sha256:{'a' * 64}"
_REQUEST = RunRequest(id="request-1")


def test_queries_and_run_submissions_use_typed_wire_models() -> None:
    requests: list[httpx.Request] = []
    client = _client(requests)

    health = client.health()
    catalog = client.catalog()
    runs = client.list_runs(limit=5, after=2, state="accepted")
    run = client.get_run("run-1")
    measurements = client.measurements("run-1", limit=10, offset=5)
    events = client.replay_events(limit=25, after=3, run_id="run-1")
    managed = client.submit_managed(_managed_submission("managed-1"))
    delegated = client.submit_delegated(_delegated_submission())

    assert health.status == "ok"
    assert health.project_id == "project-1"
    assert health.project_name == "test-lab"
    assert health.project_root == "/projects/test-lab"
    assert isinstance(catalog, ExperimentCatalog)
    assert catalog.experiments[0].id == "ramsey"
    assert isinstance(runs, RunPage)
    assert runs.items == (run.control,)
    assert measurements.items[0].point_index == 0
    assert isinstance(events, EventPage)
    assert events.items[0].event_id == 4
    assert managed.execution_mode == "managed"
    assert delegated.execution_mode == "delegated"

    list_request = requests[2]
    assert dict(list_request.url.params) == {
        "limit": "5",
        "after": "2",
        "state": "accepted",
    }
    measurement_request = requests[4]
    assert dict(measurement_request.url.params) == {
        "limit": "10",
        "offset": "5",
    }
    event_request = requests[5]
    assert dict(event_request.url.params) == {
        "limit": "25",
        "after": "3",
        "run_id": "run-1",
    }
    assert requests[6].method == "POST"
    assert b'"execution_mode":"managed"' in requests[6].content
    assert b'"execution_mode":"delegated"' in requests[7].content


def test_delegated_executor_commands_follow_run_scoped_routes() -> None:
    requests: list[httpx.Request] = []
    client = _client(requests)
    start_request = ExecutorStartRequest(
        run_id="run-1",
        executor_id="notebook-1",
        manifest=_running_manifest(),
    )
    heartbeat = ExecutorHeartbeat(
        run_id="run-1",
        lease_id="lease-1",
        generation=1,
    )
    batch = ExecutionTransitionBatch(
        batch_id="batch-1",
        lease_id="lease-1",
        generation=1,
        run_id="run-1",
        transitions=(_transition(),),
    )
    terminal = _terminal_command()

    lease = client.start_executor(start_request)
    renewed = client.heartbeat_executor("run-1", heartbeat)
    receipt = client.append_transitions(batch)
    completed = client.commit_terminal(terminal)

    assert isinstance(lease, ExecutorLease)
    assert renewed.expires_at == lease.expires_at
    assert isinstance(receipt, ExecutionTransitionBatchReceipt)
    assert receipt.committed[0].sequence == 1
    assert completed.manifest.lifecycle == "terminal"
    assert [request.url.path for request in requests] == [
        "/api/v1/runs/run-1/executor/start",
        "/api/v1/runs/run-1/executor/heartbeat",
        "/api/v1/runs/run-1/transitions",
        "/api/v1/runs/run-1/terminal",
    ]


def test_attention_resolution_uses_operator_route() -> None:
    requests: list[httpx.Request] = []
    client = _client(requests)

    receipt = client.resolve_attention("run-1", "requeue")

    assert receipt == AttentionResolutionReceipt(
        run_id="run-1",
        action="requeue",
        state="accepted",
        released_resource_count=1,
    )
    assert requests[0].url.path == "/api/v1/runs/run-1/attention"


def test_config_registry_client_uses_typed_routes() -> None:
    requests: list[httpx.Request] = []
    client = _client(requests)
    config = load_config()
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

    registry = client.config_registry()
    active = client.active_config()
    entry = client.config_entry("baseline")
    imported = client.import_direct_config(import_command)
    activated = client.activate_config_entry(activation_command)
    rolled_back = client.rollback_config(rollback_command)

    assert registry.entries[0].id == "baseline"
    assert active.config == config
    assert entry == ConfigEntryView(entry=registry.entries[0], config=config)
    assert imported.entry == registry.entries[0]
    assert activated.active_state == registry.active_state
    assert rolled_back.active_state == registry.active_state
    assert [request.url.path for request in requests] == [
        "/api/v1/config-registry",
        "/api/v1/config-registry/active",
        "/api/v1/config-registry/entries/baseline",
        "/api/v1/config-registry/entries",
        "/api/v1/config-registry/active",
        "/api/v1/config-registry/rollback",
    ]
    assert (
        DirectConfigImportCommand.model_validate_json(requests[3].content)
        == import_command
    )
    assert (
        ConfigEntryActivationCommand.model_validate_json(requests[4].content)
        == activation_command
    )
    assert (
        ConfigRollbackCommand.model_validate_json(requests[5].content)
        == rollback_command
    )


def test_post_run_client_uses_run_scoped_typed_routes() -> None:
    requests: list[httpx.Request] = []
    client = _client(requests)
    proposal = _proposal()
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
        proposal_id=proposal.id,
        decision="approved",
        reviewer="operator",
    )
    candidate = CandidateConfigActivationCommand(
        run_id="run-1",
        proposal_ids=(proposal.id,),
        entry_id="baseline",
        registered_by="operator",
        operator="operator",
        expected_generation=0,
    )

    config = client.run_config("run-1")
    saved = client.save_analysis(analysis)
    proposals = client.parameter_proposals("run-1")
    reviewed = client.review_parameter_proposal(review)
    activated = client.activate_candidate_config(candidate)

    assert config.config == load_config()
    assert saved.analysis_key == "fit"
    assert proposals.items[0].proposal == proposal
    assert reviewed.decision.proposal_id == proposal.id
    assert activated.entry.id == "baseline"
    assert [request.url.path for request in requests] == [
        "/api/v1/runs/run-1/config",
        "/api/v1/runs/run-1/analyses",
        "/api/v1/runs/run-1/parameter-proposals",
        "/api/v1/runs/run-1/parameter-proposals/drive-frequency/review",
        "/api/v1/config-registry/candidates/activate",
    ]


def test_run_content_client_uses_symmetric_typed_routes() -> None:
    requests: list[httpx.Request] = []
    client = _client(requests)
    attachment = RunAttachmentCommand(
        run_id="run-1",
        key="notes",
        text="hello",
        filename="notes.txt",
    )

    request = client.run_request("run-1")
    analyses = client.analyses("run-1")
    analysis = client.analysis("run-1", "analysis-fit")
    artifact_bytes = client.artifact_bytes(
        "run-1",
        "notes",
        expected_kind="attachment",
    )
    artifact_text = client.artifact_text(
        "run-1",
        "notes",
        expected_kind="attachment",
    )
    artifact_json = client.artifact_json(
        "run-1",
        "result",
        expected_kind="result",
    )
    record = client.record_json(
        "run-1",
        "analysis-fit",
        expected_kind="analysis",
    )
    dataset = client.dataset_content("run-1", "raw-measurements")
    attached = client.attach(attachment)

    assert request.request == _REQUEST
    assert analyses.items[0] == analysis
    assert artifact_bytes.content_bytes() == b"hello"
    assert artifact_text.content == "hello"
    assert artifact_json.content == {"ok": True}
    assert record.content == {"run_id": "run-1"}
    assert isinstance(dataset.content, MeasurementDataset)
    assert attached.artifact.filename == "notes.txt"
    assert [request.url.path for request in requests] == [
        "/api/v1/runs/run-1/request",
        "/api/v1/runs/run-1/analyses",
        "/api/v1/runs/run-1/analyses/analysis-fit",
        "/api/v1/runs/run-1/artifacts/notes/bytes",
        "/api/v1/runs/run-1/artifacts/notes/text",
        "/api/v1/runs/run-1/artifacts/result/json",
        "/api/v1/runs/run-1/records/analysis-fit/json",
        "/api/v1/runs/run-1/datasets/raw-measurements",
        "/api/v1/runs/run-1/attachments",
    ]
    assert dict(requests[3].url.params) == {"expected_kind": "attachment"}
    assert RunAttachmentCommand.model_validate_json(requests[-1].content) == attachment


def test_not_found_and_conflict_are_typed_and_other_http_errors_raise() -> None:
    client = _client([])

    with pytest.raises(DaemonNotFoundError) as missing:
        client.get_run("missing")
    with pytest.raises(DaemonConflictError) as conflict:
        client.submit_managed(_managed_submission("duplicate"))
    with pytest.raises(httpx.HTTPStatusError):
        client.get_run("invalid")

    assert missing.value.detail == "run was not found: missing"
    assert missing.value.response.status_code == 404
    assert conflict.value.detail == "submission already exists"
    assert conflict.value.response.status_code == 409


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


def _analysis_view() -> RunAnalysisView:
    return RunAnalysisView(
        run_id="run-1",
        entry=_content_entry("record", "analysis-fit", "analysis"),
        analysis=AnalysisRecord(
            run_id="run-1",
            title="fit",
            key="fit",
            outputs=[],
        ),
    )


def _run_content_response(request: httpx.Request) -> httpx.Response | None:
    path = request.url.path
    if path == "/api/v1/runs/run-1/request":
        return _model(RunRequestView(run_id="run-1", request=_REQUEST))
    if path == "/api/v1/runs/run-1/analyses" and request.method == "GET":
        return _model(RunAnalysisListView(run_id="run-1", items=(_analysis_view(),)))
    if path == "/api/v1/runs/run-1/analyses/analysis-fit":
        return _model(_analysis_view())
    if path == "/api/v1/runs/run-1/analyses" and request.method == "POST":
        command = AnalysisSaveCommand.model_validate_json(request.content)
        return _model(
            AnalysisSaveReceipt(
                record=_content_entry(
                    "record",
                    f"analysis-{command.analysis_key}",
                    "analysis",
                ),
                analysis_key=command.analysis_key,
                inputs=command.inputs,
            ),
            status_code=201,
        )
    if path == "/api/v1/runs/run-1/artifacts/notes/bytes":
        return _model(
            RunArtifactBytesView(
                run_id="run-1",
                artifact=_content_entry("artifact", "notes", "attachment"),
                content_base64="aGVsbG8=",
            )
        )
    if path == "/api/v1/runs/run-1/artifacts/notes/text":
        return _model(
            RunArtifactTextView(
                run_id="run-1",
                artifact=_content_entry("artifact", "notes", "attachment"),
                content="hello",
            )
        )
    if path == "/api/v1/runs/run-1/artifacts/result/json":
        return _model(
            RunArtifactJsonView(
                run_id="run-1",
                artifact=_content_entry("artifact", "result", "result"),
                content={"ok": True},
            )
        )
    if path == "/api/v1/runs/run-1/records/analysis-fit/json":
        return _model(
            RunRecordJsonView(
                run_id="run-1",
                record=_content_entry("record", "analysis-fit", "analysis"),
                content={"run_id": "run-1"},
            )
        )
    if path == "/api/v1/runs/run-1/datasets/raw-measurements":
        return _model(
            RunDatasetContentView(
                run_id="run-1",
                dataset=_content_entry(
                    "dataset",
                    "raw-measurements",
                    "measurement_dataset",
                ),
                content=MeasurementDataset(
                    dataset_id="raw-measurements",
                    schema=MeasurementDatasetSchema(
                        dataset_id="raw-measurements",
                        dataset_role="raw",
                    ),
                    records=[],
                ),
            )
        )
    if path == "/api/v1/runs/run-1/attachments":
        command = RunAttachmentCommand.model_validate_json(request.content)
        return _model(
            RunAttachmentReceipt(
                run_id="run-1",
                artifact=_content_entry(
                    "artifact",
                    command.key,
                    command.kind,
                    filename=command.filename,
                ),
            ),
            status_code=201,
        )
    return None


def _client(requests: list[httpx.Request]) -> DaemonClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        path = request.url.path
        if path == "/api/v1/health":
            return _json(
                {
                    "schema_version": "scopecat.daemon_health.v2",
                    "status": "ok",
                    "project_id": "project-1",
                    "project_name": "test-lab",
                    "project_root": "/projects/test-lab",
                }
            )
        if path == "/api/v1/catalog":
            return _model(_catalog())
        if path == "/api/v1/config-registry" and request.method == "GET":
            entry, state = _config_registry_records()
            return _model(ConfigRegistryView(entries=(entry,), active_state=state))
        if path == "/api/v1/config-registry/active" and request.method == "GET":
            entry, state = _config_registry_records()
            return _model(
                ActiveConfigView(
                    entry=entry,
                    active_state=state,
                    config=load_config(),
                )
            )
        if path == "/api/v1/config-registry/entries/baseline":
            entry, _state = _config_registry_records()
            return _model(ConfigEntryView(entry=entry, config=load_config()))
        if path == "/api/v1/config-registry/entries":
            entry, _state = _config_registry_records()
            return _model(ConfigImportReceipt(entry=entry), status_code=201)
        if path == "/api/v1/config-registry/candidates/activate":
            entry, state = _config_registry_records()
            return _model(
                CandidateConfigActivationReceipt(
                    entry=entry,
                    active_state=state,
                    activation=state.history[-1],
                )
            )
        if path in {
            "/api/v1/config-registry/active",
            "/api/v1/config-registry/rollback",
        }:
            _entry, state = _config_registry_records()
            return _model(
                ConfigActivationReceipt(
                    active_state=state,
                    activation=state.history[-1],
                )
            )
        if path == "/api/v1/runs" and request.method == "GET":
            return _model(RunPage(items=(_control_run(),)))
        if path == "/api/v1/events":
            return _model(
                EventPage(
                    items=(
                        DurableEvent(
                            event_id=4,
                            run_id="run-1",
                            kind="run_state_changed",
                            payload={"state": "running"},
                            occurred_at=_NOW,
                        ),
                    )
                )
            )
        if path == "/api/v1/runs/missing":
            return _json({"detail": "run was not found: missing"}, status_code=404)
        if path == "/api/v1/runs/invalid":
            return _json({"detail": "invalid request"}, status_code=422)
        if path == "/api/v1/runs/run-1" and request.method == "GET":
            return _model(
                RunDetail(
                    control=_control_run(),
                    manifest=_accepted_manifest(),
                )
            )
        if path == "/api/v1/runs/run-1/config":
            config = load_config()
            return _model(
                RunConfigView(
                    run_id="run-1",
                    config_content_hash=config_content_hash(config),
                    config=config,
                )
            )
        if (content_response := _run_content_response(request)) is not None:
            return content_response
        if path == "/api/v1/runs/run-1/parameter-proposals":
            return _model(
                ParameterProposalListView(
                    run_id="run-1",
                    items=(ParameterProposalView(proposal=_proposal()),),
                )
            )
        if path.endswith("/parameter-proposals/drive-frequency/review"):
            command = ParameterProposalReviewCommand.model_validate_json(
                request.content
            )
            return _model(
                ParameterProposalReviewReceipt(
                    decision=ParameterChangeDecisionRecord(
                        event_id="decision-1",
                        run_id=command.run_id,
                        proposal_id=command.proposal_id,
                        decision=command.decision,
                        actor=command.reviewer,
                    )
                )
            )
        if path == "/api/v1/runs/run-1/attention":
            return _model(
                AttentionResolutionReceipt(
                    run_id="run-1",
                    action="requeue",
                    state="accepted",
                    released_resource_count=1,
                )
            )
        if path == "/api/v1/runs/run-1/measurements":
            return _model(
                MeasurementPage(
                    items=(
                        MeasurementRecord(
                            run_id="run-1",
                            logical_point_id="point-0",
                            point_index=0,
                            coordinates={},
                            observables={"signal": Quantity(value=1.0, unit="ratio")},
                        ),
                    )
                )
            )
        if path == "/api/v1/runs" and request.method == "POST":
            if b'"submission_id":"duplicate"' in request.content:
                return _json(
                    {"detail": "submission already exists"},
                    status_code=409,
                )
            mode = (
                "delegated"
                if b'"execution_mode":"delegated"' in request.content
                else "managed"
            )
            submission_id = "delegated-1" if mode == "delegated" else "managed-1"
            return _model(_admission(submission_id, mode), status_code=201)
        if path == "/api/v1/runs/run-1/executor/start":
            return _model(_lease())
        if path == "/api/v1/runs/run-1/executor/heartbeat":
            return _model(_lease())
        if path == "/api/v1/runs/run-1/transitions":
            return _model(
                ExecutionTransitionBatchReceipt(
                    batch_id="batch-1",
                    committed=(_transition().model_copy(update={"sequence": 1}),),
                )
            )
        if path == "/api/v1/runs/run-1/terminal":
            return _model(
                TerminalRunCommitReceipt(
                    command_id="terminal:run-1",
                    manifest=_terminal_manifest(),
                )
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    return DaemonClient(
        "http://daemon.local/",
        transport=httpx.MockTransport(handler),
    )


def _model(model: BaseModel, *, status_code: int = 200) -> httpx.Response:
    return _json(model.model_dump(mode="json"), status_code=status_code)


def _json(content: object, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=content)


def _catalog() -> ExperimentCatalog:
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


def _control_run() -> ControlRun:
    return ControlRun(
        sequence=1,
        admission=RunAdmissionRecord(
            submission_id="delegated-1",
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


def _config_registry_records() -> tuple[
    ConfigRegistryEntry,
    ConfigRegistryActiveState,
]:
    config = load_config()
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


def _admission(
    submission_id: str,
    execution_mode: Literal["managed", "delegated"],
) -> RunAdmission:
    return RunAdmission(
        run_id="run-1",
        submission_id=submission_id,
        execution_mode=execution_mode,
        config_content_hash=_HASH,
        accepted_at=_NOW,
        event_cursor=1,
    )


def _managed_submission(submission_id: str) -> ManagedRunSubmission:
    return ManagedRunSubmission(
        submission_id=submission_id,
        registration_id="ramsey",
        registration_version="1",
        request=_REQUEST,
    )


def _delegated_submission() -> DelegatedRunSubmission:
    return DelegatedRunSubmission(
        submission_id="delegated-1",
        executor_id="notebook-1",
        config=load_config(),
        request=_REQUEST,
        plan=DelegatedPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
        ),
    )


def _proposal():
    return parameter_change_proposal_from_updates(
        source_run_id="run-1",
        source_config=load_config(),
        analysis_title="fit",
        proposal_id="drive-frequency",
        updates=(
            replace_scalar_parameter(
                "drive_frequency",
                Quantity(value=5.1, unit="GHz"),
            ),
        ),
        reason="fit converged",
        confidence=0.9,
    ).model_copy(update={"proposed_at": _NOW})


def _lease() -> ExecutorLease:
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
