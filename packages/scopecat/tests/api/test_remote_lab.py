from __future__ import annotations

import time
from base64 import b64decode
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import httpx2
import pytest
from pydantic import BaseModel

import scopecat.api._delegated as delegated_module
from scopecat.analysis.service import AnalysisOutput, prepare_analysis_artifact
from scopecat.api._delegated import _DelegatedRunner
from scopecat.api._remote import RemoteRunOperations
from scopecat.api.lab import LabClient
from scopecat.config.drafts import ConfigDraft
from scopecat.config.parameters import (
    delete_parameter_rows,
    insert_parameter_rows,
    replace_scalar_parameter,
    update_parameter_rows,
)
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    DirectConfigRegistrySource,
    ManualConfigDraftRegistrySource,
)
from scopecat.config.resolution import config_revision_entry_id
from scopecat.control.models import (
    ControlRun,
    DurableEvent,
    EventPage,
    RunAdmissionRecord,
    RunPage,
)
from scopecat.daemon.client import DaemonClient, DaemonConflictError
from scopecat.daemon.execution import DelegatedExecutorLeaseLostError
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigDraftPreview,
    ConfigEntryView,
    ConfigRegistryView,
    DaemonHealth,
    RunDetail,
)
from scopecat.daemon.wire import (
    AnalysisArtifactOutputPayload,
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
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
    DelegatedRunSubmission,
    DeleteConfigParameterRows,
    DirectConfigDefaultCommand,
    DirectConfigImportCommand,
    ExecutionRecoverySnapshot,
    ExecutorLease,
    ExperimentCatalog,
    InsertConfigParameterRows,
    ManagedRunSubmission,
    RegisteredExperimentDescriptor,
    ReplaceConfigParameter,
    ResourceClaimDescriptor,
    RunAdmission,
    RuntimeEventPublishCommand,
    RuntimeEventPublishReceipt,
    UpdateConfigParameterRows,
)
from scopecat.execution.observation import (
    RuntimeEvent,
    RuntimePayloadObservation,
    RuntimeProgress,
    RuntimeTransitionEvent,
)
from scopecat.execution.program import RunProgram
from scopecat.execution.services import ExecutionServices
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.system import ExperimentSystem
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.parameter import Quantity
from scopecat.records.run import (
    ConfigRegistryRunConfigSource,
    RunManifest,
    RunOutcome,
)
from scopecat.records.run_request import RunRequest
from scopecat.runs.service import PlannedRun, plan_experiment
from scopecat.sdk.instruments.contracts import InstrumentProvider
from scopecat.testing import sqlite_project_services
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import (
    load_config,
    load_invocation,
    load_prepared_invocation,
)

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)


def test_control_operations_expose_browsing_and_managed_submission() -> None:
    request = RunRequest(id="managed-request")
    admission_record = RunAdmissionRecord(
        submission_id="existing-submission",
        run_id="run-existing",
        execution_mode="managed",
        experiment_id="ramsey",
        config_content_hash=f"sha256:{'1' * 64}",
        request=request,
        admitted_at=_NOW,
    )
    run = ControlRun(
        sequence=1,
        admission=admission_record,
        state="accepted",
        state_version=1,
        updated_at=_NOW,
    )
    event = DurableEvent(
        event_id=1,
        run_id=run.run_id,
        kind="run.admitted",
        occurred_at=_NOW,
    )
    seen_submission_ids: list[str] = []

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        path = http_request.url.path
        if path.endswith("/health"):
            return _model(
                DaemonHealth(
                    status="ok",
                    project_id="project-1",
                    project_name="test-lab",
                    project_root="/projects/test-lab",
                )
            )
        if path.endswith("/catalog"):
            return _model(
                ExperimentCatalog(
                    revision="catalog-1",
                    experiments=(
                        RegisteredExperimentDescriptor(
                            id="ramsey",
                            version="1",
                            experiment_kind="calibration",
                        ),
                    ),
                )
            )
        if path.endswith("/runs") and http_request.method == "GET":
            if "before" in http_request.url.params:
                assert http_request.url.params["before"] == "10"
                assert "latest" not in http_request.url.params
            else:
                assert http_request.url.params["state"] == "accepted"
                assert http_request.url.params["latest"] == "true"
            return _model(RunPage(items=(run,)))
        if path.endswith(f"/runs/{run.run_id}"):
            return _model(
                RunDetail(
                    control=run,
                    manifest=RunManifest(
                        run_id=run.run_id,
                        created_at=_NOW,
                        lifecycle="accepted",
                        config_content_hash=run.admission.config_content_hash,
                    ),
                )
            )
        if path.endswith("/events"):
            assert http_request.url.params["run_id"] == run.run_id
            return _model(EventPage(items=(event,)))
        if path.endswith("/runs") and http_request.method == "POST":
            submission = ManagedRunSubmission.model_validate_json(http_request.content)
            seen_submission_ids.append(submission.submission_id)
            return _model(
                RunAdmission(
                    run_id="run-managed",
                    submission_id=submission.submission_id,
                    execution_mode="managed",
                    config_content_hash=f"sha256:{'2' * 64}",
                    accepted_at=_NOW,
                    event_cursor=2,
                ),
                status_code=201,
            )
        raise AssertionError(f"unexpected request: {http_request.method} {path}")

    client = _client(handler)
    lab = LabClient(client)

    assert lab.control.health().project_id == "project-1"
    assert lab.control.catalog().experiments[0].id == "ramsey"
    assert lab.control.runs(state="accepted").items == (run,)
    assert lab.control.runs(before=10).items == (run,)
    assert lab.control.run_detail(run.run_id).control == run
    assert lab.control.events(run_id=run.run_id).items == (event,)
    admission = lab.control.submit_managed(
        "ramsey",
        "1",
        request,
        submission_id="managed-submission",
    )

    assert admission.submission_id == "managed-submission"
    assert seen_submission_ids == ["managed-submission"]
    lab.close()
    assert client.health().status == "ok"


def test_execute_delegated_submits_complete_plan_and_heartbeats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned_without_source = _planned(tmp_path)
    planned = replace(
        planned_without_source,
        config_source=ConfigRegistryRunConfigSource(
            selector="active",
            entry_id="baseline",
            config_ref="config-registry/configs/baseline.json",
            content_hash=config_content_hash(planned_without_source.config),
            registry_generation=3,
        ),
    )
    preview = build_run_program_preview(planned.program)
    heartbeat_seen = Event()
    heartbeat_count = 0
    delegated_submissions: list[DelegatedRunSubmission] = []
    published_events: list[RuntimeEventPublishCommand] = []
    local_events: list[RuntimeEvent] = []
    forwarded: dict[str, object] = {}
    transition_event = RuntimeTransitionEvent(
        run_id="run-1",
        experiment_id=preview.experiment_id,
        observed_at=_NOW,
        occurred_at=_NOW,
        operation_id="point-0",
        stage="point",
        effect="pure",
        state="completed",
        progress=RuntimeProgress(completed_points=1, total_points=1),
        point_index=0,
    )
    compute_event = replace(
        transition_event,
        operation_id="compute-0",
        stage="compute",
    )

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        nonlocal heartbeat_count
        path = http_request.url.path
        if path.endswith("/runs"):
            submission = DelegatedRunSubmission.model_validate_json(
                http_request.content
            )
            delegated_submissions.append(submission)
            return _model(_admission(submission), status_code=201)
        if path.endswith("/executor/start"):
            return _model(_lease(heartbeat_interval=0.01))
        if path.endswith("/executor/heartbeat"):
            heartbeat_count += 1
            heartbeat_seen.set()
            return _model(_lease(heartbeat_interval=0.01))
        if path.endswith("/runtime-events"):
            command = RuntimeEventPublishCommand.model_validate_json(
                http_request.content
            )
            published_events.append(command)
            return _model(
                RuntimeEventPublishReceipt(
                    event_id=2,
                    run_id=command.run_id,
                    kind=command.event.kind,
                )
            )
        raise AssertionError(f"unexpected request: {http_request.method} {path}")

    def execute(
        *,
        run_id: str,
        program: RunProgram,
        services: ExecutionServices,
        instrument_provider: InstrumentProvider | None,
        event_sink: Callable[[RuntimeEvent], None] | None,
        payload_observer: Callable[[RuntimePayloadObservation], None] | None,
    ) -> RunManifest:
        forwarded.update(
            program=program,
            instrument_provider=instrument_provider,
            event_sink=event_sink,
            payload_observer=payload_observer,
        )
        accepted = services.runs.read_manifest(run_id)
        services.runs.write_manifest(
            accepted.model_copy(update={"lifecycle": "running"})
        )
        with services.resources.acquire(program.resource_claims):
            assert heartbeat_seen.wait(timeout=1)
            assert event_sink is not None
            event_sink(compute_event)
            event_sink(transition_event)
        return _terminal_manifest(accepted)

    monkeypatch.setattr(delegated_module, "execute_admitted_run", execute)

    def event_sink(event: RuntimeEvent) -> None:
        local_events.append(event)

    def payload_observer(_event: RuntimePayloadObservation) -> None:
        pass

    result = _DelegatedRunner(_client(handler), None).execute(
        planned,
        executor_id="notebook-1",
        submission_id="delegated-submission",
        event_sink=event_sink,
        payload_observer=payload_observer,
    )
    completed_heartbeats = heartbeat_count
    time.sleep(0.03)

    [submission] = delegated_submissions
    assert submission.submission_id == "delegated-submission"
    assert submission.config == planned.config
    assert submission.config_source == planned.config_source
    assert submission.request == planned.request
    assert submission.plan.experiment_id == preview.experiment_id
    assert submission.plan.experiment_kind == preview.experiment_kind
    assert submission.plan.point_count == preview.point_count
    assert submission.plan.coordinate_ids == preview.coordinate_ids
    assert submission.plan.record_ids == tuple(record.id for record in preview.records)
    assert submission.plan.run_resource_claims == tuple(
        ResourceClaimDescriptor(id=claim.id, kind=claim.kind)
        for claim in planned.program.resource_claims
    )
    assert forwarded["program"] == planned.program
    assert forwarded["instrument_provider"] == (
        None if planned.system is None else planned.system.provider
    )
    assert forwarded["event_sink"] is not event_sink
    assert forwarded["payload_observer"] is payload_observer
    assert local_events == [compute_event, transition_event]
    assert len(published_events) == 1
    assert published_events[0].event.progress.completed_points == 1
    assert published_events[0].event.progress.total_points == 1
    assert result.status == "completed"
    assert completed_heartbeats >= 1
    assert heartbeat_count == completed_heartbeats


def test_execute_delegated_fences_effects_after_heartbeat_loses_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned = _planned(tmp_path)
    heartbeat_attempted = Event()

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        path = http_request.url.path
        if path.endswith("/runs"):
            submission = DelegatedRunSubmission.model_validate_json(
                http_request.content
            )
            return _model(_admission(submission), status_code=201)
        if path.endswith("/executor/start"):
            return _model(_lease(heartbeat_interval=0.005))
        if path.endswith("/executor/heartbeat"):
            heartbeat_attempted.set()
            return httpx2.Response(409, json={"detail": "executor lease expired"})
        if path.endswith("/execution/recovery"):
            return _model(ExecutionRecoverySnapshot())
        raise AssertionError(f"unexpected request: {http_request.method} {path}")

    def execute(
        *,
        run_id: str,
        program: RunProgram,
        services: ExecutionServices,
        instrument_provider: InstrumentProvider | None,
        event_sink: Callable[[RuntimeEvent], None] | None,
        payload_observer: Callable[[RuntimePayloadObservation], None] | None,
    ) -> RunManifest:
        del instrument_provider, event_sink, payload_observer
        accepted = services.runs.read_manifest(run_id)
        services.runs.write_manifest(
            accepted.model_copy(update={"lifecycle": "running"})
        )
        with services.resources.acquire(program.resource_claims):
            assert heartbeat_attempted.wait(timeout=1)
            deadline = time.monotonic() + 1
            while True:
                try:
                    services.journal_for(run_id).entries()
                except DelegatedExecutorLeaseLostError:
                    raise
                if time.monotonic() >= deadline:
                    raise AssertionError("heartbeat failure did not fence effects")
                time.sleep(0.001)

    monkeypatch.setattr(delegated_module, "execute_admitted_run", execute)

    with pytest.raises(
        DelegatedExecutorLeaseLostError,
        match="generation 7 is no longer live",
    ) as error:
        _DelegatedRunner(_client(handler), None).execute(
            planned,
            executor_id="notebook-1",
        )

    assert isinstance(error.value.cause, DaemonConflictError)


def test_execute_delegated_requires_a_durable_request(tmp_path: Path) -> None:
    planned = _planned(tmp_path)
    runner = _DelegatedRunner(
        _client(lambda _request: httpx2.Response(500)),
        None,
    )

    with pytest.raises(ValueError, match="durable run request"):
        runner.execute(
            PlannedRun(
                config=planned.config,
                request=None,
                program=planned.program,
            ),
            executor_id="notebook-1",
        )


def test_config_operations_compose_registry_commands() -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    seen: list[object] = []
    scalar_update = replace_scalar_parameter(
        "drive_frequency",
        Quantity(value=5.1, unit="GHz"),
    )
    draft = ConfigDraft(config).apply(scalar_update)
    draft_preview = _config_draft_preview(
        config=config,
        entry=entry,
        state=state,
        candidate_id="manual-tuning",
    )
    assert draft_preview.result_content_hash is not None

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        path = http_request.url.path
        if path == "/api/v1/config-registry":
            return _model(ConfigRegistryView(entries=(entry,), active_state=state))
        if path == "/api/v1/config-registry/active" and http_request.method == "GET":
            return _model(
                ActiveConfigView(entry=entry, active_state=state, config=config)
            )
        if path == "/api/v1/config-registry/entries/baseline":
            return _model(ConfigEntryView(entry=entry, config=config))
        if path == "/api/v1/config-registry/entries":
            command = DirectConfigImportCommand.model_validate_json(
                http_request.content
            )
            seen.append(command)
            return _model(ConfigImportReceipt(entry=entry), status_code=201)
        if path == "/api/v1/config-registry/drafts/preview":
            command = ConfigDraftCommand.model_validate_json(http_request.content)
            seen.append(command)
            return _model(draft_preview)
        if path == "/api/v1/config-registry/drafts/register":
            command = ConfigDraftRegistrationCommand.model_validate_json(
                http_request.content
            )
            seen.append(command)
            return _model(
                _config_draft_registration_receipt(command, draft_preview),
                status_code=201,
            )
        if path == "/api/v1/config-registry/active":
            command = ConfigEntryActivationCommand.model_validate_json(
                http_request.content
            )
            seen.append(command)
            return _model(
                ConfigActivationReceipt(
                    active_state=state,
                    activation=state.history[-1],
                )
            )
        if path == "/api/v1/config-registry/rollback":
            command = ConfigRollbackCommand.model_validate_json(http_request.content)
            seen.append(command)
            return _model(
                ConfigActivationReceipt(
                    active_state=state,
                    activation=state.history[-1],
                )
            )
        raise AssertionError(f"unexpected request: {http_request.method} {path}")

    config_ops = LabClient(_client(handler)).config

    assert config_ops.registry().active_state == state
    assert config_ops.active().config == config
    assert config_ops.entry("baseline").config == config
    assert (
        config_ops.import_snapshot(
            config,
            entry_id="baseline",
            registered_by="notebook",
        ).entry
        == entry
    )
    previewed = config_ops.preview(
        draft,
        candidate_id="manual-tuning",
    )
    registered = config_ops.register(
        draft,
        preview=previewed,
        entry_id="manual-tuning",
        registered_by="notebook",
    )
    assert registered.entry.id == "manual-tuning"
    assert (
        config_ops.activate_entry(
            "baseline",
            operator="operator",
        ).active_state
        == state
    )
    assert (
        config_ops.rollback(
            operator="operator",
            expected_generation=1,
        ).active_state
        == state
    )

    assert seen == [
        DirectConfigImportCommand(
            entry_id="baseline",
            config=config,
            registered_by="notebook",
        ),
        ConfigDraftCommand(
            base_entry_id=entry.id,
            base_content_hash=entry.content_hash,
            base_generation=state.generation,
            candidate_id="manual-tuning",
            updates=(
                ReplaceConfigParameter(
                    value=scalar_update.value,
                ),
            ),
        ),
        ConfigDraftRegistrationCommand(
            draft=ConfigDraftCommand(
                base_entry_id=entry.id,
                base_content_hash=entry.content_hash,
                base_generation=state.generation,
                candidate_id="manual-tuning",
                updates=(
                    ReplaceConfigParameter(
                        value=scalar_update.value,
                    ),
                ),
            ),
            expected_result_content_hash=draft_preview.result_content_hash,
            entry_id="manual-tuning",
            registered_by="notebook",
        ),
        ConfigEntryActivationCommand(
            entry_id="baseline",
            operator="operator",
            expected_generation=1,
        ),
        ConfigRollbackCommand(
            operator="operator",
            expected_generation=1,
        ),
    ]


def test_config_operations_serialize_each_draft_update_shape() -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    seen: list[ConfigDraftCommand] = []
    preview = _config_draft_preview(
        config=config,
        entry=entry,
        state=state,
        candidate_id="all-update-shapes",
    )

    def handler(request: httpx2.Request) -> httpx2.Response:
        if (
            request.url.path == "/api/v1/config-registry/active"
            and request.method == "GET"
        ):
            return _model(
                ActiveConfigView(entry=entry, active_state=state, config=config)
            )
        command = ConfigDraftCommand.model_validate_json(request.content)
        seen.append(command)
        return _model(preview)

    draft = ConfigDraft(config).apply(
        replace_scalar_parameter(
            "drive_frequency",
            Quantity(value=5.1, unit="GHz"),
        ),
        update_parameter_rows(
            "channels",
            key={"id": "q0"},
            values={"gain": 0.75},
        ),
        insert_parameter_rows(
            "channels",
            rows=[{"id": "q1", "gain": 0.25}],
        ),
        delete_parameter_rows("channels", key={"id": "q2"}),
    )

    LabClient(_client(handler)).config.preview(
        draft,
        candidate_id="all-update-shapes",
    )

    assert [type(update) for update in seen[0].updates] == [
        ReplaceConfigParameter,
        UpdateConfigParameterRows,
        InsertConfigParameterRows,
        DeleteConfigParameterRows,
    ]


def test_config_operations_reject_a_draft_from_a_different_active_snapshot() -> None:
    active_config = load_config()
    stale_config = active_config.model_copy(update={"id": "stale-config"})
    entry, state = _config_registry_records(active_config)
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        assert request.url.path == "/api/v1/config-registry/active"
        return _model(
            ActiveConfigView(
                entry=entry,
                active_state=state,
                config=active_config,
            )
        )

    draft = ConfigDraft(stale_config).replace_scalar(
        "drive_frequency",
        Quantity(value=5.1, unit="GHz"),
    )

    with pytest.raises(ValueError, match="no longer the active"):
        LabClient(_client(handler)).config.preview(draft)

    assert len(requests) == 1


def test_lab_client_owns_local_config_draft_workflow() -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    preview = _config_draft_preview(
        config=config,
        entry=entry,
        state=state,
        candidate_id="notebook-tuning",
    )
    defaults: list[ConfigDraftDefaultCommand] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/api/v1/config-registry":
            return _model(ConfigRegistryView(entries=(entry,), active_state=state))
        if path == "/api/v1/config-registry/active" and request.method == "GET":
            return _model(
                ActiveConfigView(entry=entry, active_state=state, config=config)
            )
        if path == "/api/v1/config-registry/drafts/preview":
            return _model(preview)
        if path == "/api/v1/config-registry/drafts/set-default":
            command = ConfigDraftDefaultCommand.model_validate_json(request.content)
            defaults.append(command)
            return _model(
                _config_draft_default_receipt(command, preview, state),
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    lab = LabClient(_client(handler), operator="notebook-operator")
    draft = lab.config.edit().replace_scalar(
        "drive_frequency",
        Quantity(value=5.1, unit="GHz"),
    )
    receipt = lab.config.set_default(
        draft,
        entry_id="notebook-tuning",
        note="typed notebook edit",
    )

    assert receipt.entry.id == "notebook-tuning"
    assert defaults[0].registration.registered_by == "notebook-operator"
    assert (
        defaults[0].registration.expected_result_content_hash
        == preview.result_content_hash
    )
    assert defaults[0].operator == "notebook-operator"


def test_lab_config_intents_hide_registry_coordination() -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    seen: list[DirectConfigDefaultCommand | ConfigRollbackCommand] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        if path == "/api/v1/config-registry":
            return _model(ConfigRegistryView(entries=(entry,), active_state=state))
        if path == "/api/v1/config-registry/active" and request.method == "GET":
            return _model(
                ActiveConfigView(entry=entry, active_state=state, config=config)
            )
        if path == "/api/v1/config-registry/default":
            command = DirectConfigDefaultCommand.model_validate_json(request.content)
            seen.append(command)
            return _model(
                ConfigDefaultReceipt(
                    entry=entry,
                    active_state=state,
                    activation=state.history[-1],
                )
            )
        if path == "/api/v1/config-registry/rollback":
            command = ConfigRollbackCommand.model_validate_json(request.content)
            seen.append(command)
            return _model(
                ConfigActivationReceipt(
                    active_state=state,
                    activation=state.history[-1],
                )
            )
        raise AssertionError(f"unexpected request: {request.method} {path}")

    lab = LabClient(_client(handler), operator="notebook-operator")

    set_receipt = lab.config.set_default(config, note="use tuned values")
    undo_receipt = lab.config.undo(note="restore prior values")

    assert set_receipt.entry == entry
    assert undo_receipt.active_state == state
    assert seen == [
        DirectConfigDefaultCommand(
            entry_id=config_revision_entry_id(config),
            config=config,
            registered_by="notebook-operator",
            operator="notebook-operator",
            expected_generation=state.generation,
            note="use tuned values",
        ),
        ConfigRollbackCommand(
            operator="notebook-operator",
            expected_generation=state.generation,
            note="restore prior values",
        ),
    ]


def test_remote_analysis_artifacts_preserve_source_defaults() -> None:
    commands: list[AnalysisSaveCommand] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        command = AnalysisSaveCommand.model_validate_json(request.content)
        commands.append(command)
        return _model(
            AnalysisSaveReceipt(
                record=RunContentEntry(
                    role="record",
                    id="analysis-fit",
                    kind="analysis",
                    content_hash="sha256:analysis",
                ),
                analysis_key=command.analysis_key,
            ),
            status_code=201,
        )

    json_spec = prepare_analysis_artifact(
        title="JSON result",
        kind="fit_json",
        artifact_id="fit-json",
        filename=None,
        model=None,
        json_content={"ok": True},
        text=None,
        content=None,
        path=None,
        media_type=None,
        metadata=None,
    )
    text_spec = prepare_analysis_artifact(
        title="Text result",
        kind="fit_text",
        artifact_id="fit-text",
        filename=None,
        model=None,
        json_content=None,
        text="fit converged",
        content=None,
        path=None,
        media_type=None,
        metadata=None,
    )

    RemoteRunOperations(_client(handler)).save_analysis(
        run_id="run-1",
        title="fit",
        analysis_key="fit",
        step_id=None,
        inputs=(),
        outputs=(
            AnalysisOutput(
                kind="artifact",
                title=json_spec.title,
                content=json_spec,
                metadata={},
            ),
            AnalysisOutput(
                kind="artifact",
                title=text_spec.title,
                content=text_spec,
                metadata={},
            ),
        ),
        parameter_proposals=(),
    )

    [command] = commands
    json_output, text_output = command.outputs
    assert isinstance(json_output, AnalysisArtifactOutputPayload)
    assert isinstance(text_output, AnalysisArtifactOutputPayload)
    assert (
        json_output.source_default_extension,
        json_output.source_default_media_type,
        b64decode(json_output.content_base64),
    ) == (".json", "application/json", b'{\n  "ok": true\n}\n')
    assert (
        text_output.source_default_extension,
        text_output.source_default_media_type,
        b64decode(text_output.content_base64),
    ) == (".txt", "text/plain", b"fit converged\n")


@pytest.mark.parametrize("prepared", [False, True])
def test_run_scratch_plans_against_explicit_snapshot_without_local_storage(
    monkeypatch: pytest.MonkeyPatch,
    *,
    prepared: bool,
) -> None:
    config = load_config()
    provider = TestSignalInstrumentProvider()
    system = ExperimentSystem(provider=provider)
    captured: dict[str, object] = {}

    def execute_delegated(
        self: _DelegatedRunner,
        planned: PlannedRun,
        *,
        executor_id: str,
        submission_id: str | None = None,
        event_sink: Callable[[RuntimeEvent], None] | None = None,
        payload_observer: Callable[[RuntimePayloadObservation], None] | None = None,
    ) -> RunManifest:
        del self, event_sink, payload_observer
        captured.update(
            planned=planned,
            executor_id=executor_id,
            submission_id=submission_id,
        )
        accepted = RunManifest(
            run_id="run-scratch",
            lifecycle="accepted",
            config_content_hash=planned.program.config_content_hash,
        )
        return _terminal_manifest(accepted)

    monkeypatch.setattr(_DelegatedRunner, "execute", execute_delegated)

    experiment = load_prepared_invocation() if prepared else load_invocation()
    result = _DelegatedRunner(
        _client(lambda _request: httpx2.Response(500)),
        lambda _config: system,
    ).run(
        experiment,
        config=config,
        name="scratch fit",
        tags=("calibration", "demo"),
        description="fit one trace",
        metadata={"sample": "q0"},
        operator="alice",
        executor_id="notebook-1",
        submission_id="scratch-submission",
    )

    planned = captured["planned"]
    assert isinstance(planned, PlannedRun)
    assert planned.config == config
    assert planned.request is not None
    assert planned.request.operator == "alice"
    assert planned.request.metadata == {
        "sample": "q0",
        "name": "scratch fit",
        "tags": ["calibration", "demo"],
        "description": "fit one trace",
    }
    assert captured["executor_id"] == "notebook-1"
    assert captured["submission_id"] == "scratch-submission"
    planned_system = planned.system
    assert planned_system is not None
    assert planned_system is system
    assert planned_system.provider is provider
    assert result.status == "completed"


def test_run_scratch_uses_active_config_and_bound_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    provider = TestSignalInstrumentProvider()
    system = ExperimentSystem(provider=provider)
    captured: dict[str, object] = {}
    built_from: list[ConfigProfileSnapshot] = []

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        assert http_request.url.path == "/api/v1/config-registry/active"
        return _model(ActiveConfigView(entry=entry, active_state=state, config=config))

    def execute_delegated(
        self: _DelegatedRunner,
        planned: PlannedRun,
        *,
        executor_id: str,
        submission_id: str | None = None,
        event_sink: Callable[[RuntimeEvent], None] | None = None,
        payload_observer: Callable[[RuntimePayloadObservation], None] | None = None,
    ) -> RunManifest:
        del self, executor_id, submission_id, event_sink, payload_observer
        captured["planned"] = planned
        return _terminal_manifest(
            RunManifest(
                run_id="run-scratch",
                lifecycle="accepted",
                config_content_hash=planned.program.config_content_hash,
            )
        )

    monkeypatch.setattr(_DelegatedRunner, "execute", execute_delegated)

    def build_system(selected: ConfigProfileSnapshot) -> ExperimentSystem:
        built_from.append(selected)
        return system

    result = _DelegatedRunner(
        _client(handler),
        build_system,
    ).run(load_invocation())

    planned = captured["planned"]
    assert isinstance(planned, PlannedRun)
    assert planned.config == config
    planned_system = planned.system
    assert planned_system is not None
    assert planned_system is system
    assert planned_system.provider is provider
    assert built_from == [config]
    assert result.status == "completed"


def test_run_scratch_requires_an_explicit_or_bound_system() -> None:
    runner = _DelegatedRunner(
        _client(
            lambda request: pytest.fail(
                f"unexpected daemon request: {request.method} {request.url.path}"
            )
        ),
        None,
    )

    with pytest.raises(ValueError, match="requires an experiment system"):
        runner.run(load_invocation(), config=load_config())


def test_preview_scratch_uses_active_config_without_admission() -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return _model(ActiveConfigView(entry=entry, active_state=state, config=config))

    preview = _DelegatedRunner(
        _client(handler),
        lambda _config: ExperimentSystem(provider=TestSignalInstrumentProvider()),
    ).preview(load_invocation())

    assert preview.point_count > 0
    assert [request.url.path for request in requests] == [
        "/api/v1/config-registry/active"
    ]


def _planned(tmp_path: Path) -> PlannedRun:
    provider = TestSignalInstrumentProvider()
    return plan_experiment(
        load_prepared_invocation(),
        config=load_config(),
        services=sqlite_project_services(tmp_path),
        system=ExperimentSystem(provider=provider),
    )


def _client(
    handler: Callable[[httpx2.Request], httpx2.Response],
) -> DaemonClient:
    return DaemonClient(
        "http://daemon.local",
        transport=httpx2.MockTransport(handler),
    )


def _config_registry_records(
    config: ConfigProfileSnapshot,
) -> tuple[ConfigRegistryEntry, ConfigRegistryActiveState]:
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


def _config_draft_preview(
    *,
    config: ConfigProfileSnapshot,
    entry: ConfigRegistryEntry,
    state: ConfigRegistryActiveState,
    candidate_id: str,
) -> ConfigDraftPreview:
    check = (
        ConfigDraft(config)
        .replace_scalar(
            "drive_frequency",
            Quantity(value=5.1, unit="GHz"),
        )
        .check(candidate_id=candidate_id)
    )
    assert check.candidate is not None
    return ConfigDraftPreview(
        valid=True,
        base_entry=entry,
        base_generation=state.generation,
        base_content_hash=entry.content_hash,
        config=check.candidate,
        result_content_hash=config_content_hash(check.candidate),
        deltas=check.deltas,
        problems=check.problems,
    )


def _config_draft_registration_receipt(
    command: ConfigDraftRegistrationCommand,
    preview: ConfigDraftPreview,
) -> ConfigDraftRegistrationReceipt:
    assert preview.result_content_hash is not None
    return ConfigDraftRegistrationReceipt(
        entry=ConfigRegistryEntry(
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
        ),
        result_content_hash=preview.result_content_hash,
        deltas=preview.deltas,
    )


def _config_draft_default_receipt(
    command: ConfigDraftDefaultCommand,
    preview: ConfigDraftPreview,
    previous_state: ConfigRegistryActiveState,
) -> ConfigDraftDefaultReceipt:
    registration = _config_draft_registration_receipt(
        command.registration,
        preview,
    )
    activation = ConfigRegistryActivationRecord(
        id="activation-2",
        generation=previous_state.generation + 1,
        action="activation",
        entry_id=registration.entry.id,
        entry_content_hash=registration.entry.content_hash,
        previous_entry_id=previous_state.active_entry_id,
        previous_entry_content_hash=previous_state.active_entry_content_hash,
        operator=command.operator,
        note=command.activation_note or command.registration.note,
        recorded_at=_NOW + timedelta(seconds=1),
    )
    state = ConfigRegistryActiveState(
        generation=activation.generation,
        active_entry_id=activation.entry_id,
        active_entry_content_hash=activation.entry_content_hash,
        history=(*previous_state.history, activation),
        updated_at=activation.recorded_at,
    )
    return ConfigDraftDefaultReceipt(
        entry=registration.entry,
        result_content_hash=registration.result_content_hash,
        deltas=registration.deltas,
        active_state=state,
        activation=activation,
    )


def _admission(submission: DelegatedRunSubmission) -> RunAdmission:
    return RunAdmission(
        run_id="run-1",
        submission_id=submission.submission_id,
        execution_mode="delegated",
        config_content_hash=submission.config_content_hash,
        accepted_at=_NOW,
        event_cursor=1,
    )


def _lease(*, heartbeat_interval: float) -> ExecutorLease:
    return ExecutorLease(
        lease_id="lease-1",
        generation=7,
        run_id="run-1",
        executor_id="notebook-1",
        issued_at=_NOW,
        expires_at=_NOW + timedelta(seconds=30),
        heartbeat_interval_seconds=heartbeat_interval,
    )


def _terminal_manifest(accepted: RunManifest) -> RunManifest:
    outcome = RunOutcome(
        run_id=accepted.run_id,
        result="succeeded",
        certainty="known",
        termination_reason="completed",
    )
    return accepted.model_copy(
        update={
            "lifecycle": "terminal",
            "outcome": outcome,
        }
    )


def _model(model: BaseModel, *, status_code: int = 200) -> httpx2.Response:
    return httpx2.Response(status_code, json=model.model_dump(mode="json"))
