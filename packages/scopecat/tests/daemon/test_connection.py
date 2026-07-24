from __future__ import annotations

import time
from base64 import b64decode
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import httpx
import pytest
from pydantic import BaseModel

import scopecat.daemon.connection as connection_module
from scopecat.analysis.service import AnalysisOutput, prepare_analysis_artifact
from scopecat.api.lab import LabClient
from scopecat.composition.embedded import embedded_workspace_services
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
from scopecat.daemon import (
    DaemonClient,
    DaemonConflictError,
    DaemonConnection,
    DaemonHealth,
    DelegatedExecutorLeaseLostError,
    DelegatedRunSubmission,
    ExecutionRecoverySnapshot,
    ExecutorLease,
    ExperimentCatalog,
    ManagedRunSubmission,
    RegisteredExperimentDescriptor,
    ResourceClaimDescriptor,
    RunAdmission,
    RunDetail,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigDraftPreview,
    ConfigEntryView,
    ConfigRegistryView,
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
    DeleteConfigParameterRows,
    DirectConfigDefaultCommand,
    DirectConfigImportCommand,
    InsertConfigParameterRows,
    ReplaceConfigParameter,
    UpdateConfigParameterRows,
)
from scopecat.execution.observation import RuntimeEvent, RuntimePayloadObservation
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
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import (
    load_config,
    load_invocation,
    load_prepared_invocation,
)

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)


def test_connection_exposes_browsing_and_managed_submission() -> None:
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

    def handler(http_request: httpx.Request) -> httpx.Response:
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
            assert http_request.url.params["state"] == "accepted"
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
    connection = DaemonConnection(client)

    assert connection.health().project_id == "project-1"
    assert connection.catalog().experiments[0].id == "ramsey"
    assert connection.runs(state="accepted").items == (run,)
    assert connection.get_run(run.run_id).control == run
    assert connection.events(run_id=run.run_id).items == (event,)
    admission = connection.submit_managed(
        "ramsey",
        "1",
        request,
        submission_id="managed-submission",
    )

    assert admission.submission_id == "managed-submission"
    assert seen_submission_ids == ["managed-submission"]
    connection.close()
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
    forwarded: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
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
        return _terminal_manifest(accepted)

    monkeypatch.setattr(connection_module, "execute_admitted_run", execute)

    def event_sink(_event: RuntimeEvent) -> None:
        pass

    def payload_observer(_event: RuntimePayloadObservation) -> None:
        pass

    result = DaemonConnection(_client(handler)).execute_delegated(
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
    assert forwarded == {
        "program": planned.program,
        "instrument_provider": (
            None if planned.system is None else planned.system.provider
        ),
        "event_sink": event_sink,
        "payload_observer": payload_observer,
    }
    assert result.status == "completed"
    assert completed_heartbeats >= 1
    assert heartbeat_count == completed_heartbeats


def test_execute_delegated_fences_effects_after_heartbeat_loses_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned = _planned(tmp_path)
    heartbeat_attempted = Event()

    def handler(http_request: httpx.Request) -> httpx.Response:
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
            return httpx.Response(409, json={"detail": "executor lease expired"})
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

    monkeypatch.setattr(connection_module, "execute_admitted_run", execute)

    with pytest.raises(
        DelegatedExecutorLeaseLostError,
        match="generation 7 is no longer live",
    ) as error:
        DaemonConnection(_client(handler)).execute_delegated(
            planned,
            executor_id="notebook-1",
        )

    assert isinstance(error.value.cause, DaemonConflictError)


def test_execute_delegated_requires_a_durable_request(tmp_path: Path) -> None:
    planned = _planned(tmp_path)
    connection = DaemonConnection(_client(lambda _request: httpx.Response(500)))

    with pytest.raises(ValueError, match="durable run request"):
        connection.execute_delegated(
            PlannedRun(
                config=planned.config,
                request=None,
                program=planned.program,
            ),
            executor_id="notebook-1",
        )


def test_connection_composes_config_registry_commands() -> None:
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

    def handler(http_request: httpx.Request) -> httpx.Response:
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

    connection = DaemonConnection(_client(handler))

    assert connection.config_registry().active_state == state
    assert connection.active_config().config == config
    assert connection.config_entry("baseline").config == config
    assert (
        connection.import_direct_config(
            config,
            entry_id="baseline",
            registered_by="notebook",
        ).entry
        == entry
    )
    previewed = connection.preview_config_draft(
        draft,
        candidate_id="manual-tuning",
    )
    registered = connection.register_config_draft(
        draft,
        preview=previewed,
        entry_id="manual-tuning",
        registered_by="notebook",
    )
    assert registered.entry.id == "manual-tuning"
    assert (
        connection.activate_config_entry(
            "baseline",
            operator="operator",
        ).active_state
        == state
    )
    assert (
        connection.rollback_config(
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


def test_connection_serializes_each_config_draft_update_shape() -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    seen: list[ConfigDraftCommand] = []
    preview = _config_draft_preview(
        config=config,
        entry=entry,
        state=state,
        candidate_id="all-update-shapes",
    )

    def handler(request: httpx.Request) -> httpx.Response:
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

    DaemonConnection(_client(handler)).preview_config_draft(
        draft,
        candidate_id="all-update-shapes",
    )

    assert [type(update) for update in seen[0].updates] == [
        ReplaceConfigParameter,
        UpdateConfigParameterRows,
        InsertConfigParameterRows,
        DeleteConfigParameterRows,
    ]


def test_connection_rejects_a_draft_from_a_different_active_snapshot() -> None:
    active_config = load_config()
    stale_config = active_config.model_copy(update={"id": "stale-config"})
    entry, state = _config_registry_records(active_config)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
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
        DaemonConnection(_client(handler)).preview_config_draft(draft)

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

    def handler(request: httpx.Request) -> httpx.Response:
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

    lab = LabClient(
        DaemonConnection(_client(handler)),
        operator="notebook-operator",
    )
    draft = lab.edit_config().replace_scalar(
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

    def handler(request: httpx.Request) -> httpx.Response:
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

    lab = LabClient(
        DaemonConnection(_client(handler)),
        operator="notebook-operator",
    )

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

    def handler(request: httpx.Request) -> httpx.Response:
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

    DaemonConnection(_client(handler)).save_analysis(
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
        self: DaemonConnection,
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

    monkeypatch.setattr(DaemonConnection, "execute_delegated", execute_delegated)

    experiment = load_prepared_invocation() if prepared else load_invocation()
    result = DaemonConnection(
        _client(lambda _request: httpx.Response(500)),
        build_system=lambda _config: system,
    ).run_scratch(
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

    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path == "/api/v1/config-registry/active"
        return _model(ActiveConfigView(entry=entry, active_state=state, config=config))

    def execute_delegated(
        self: DaemonConnection,
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

    monkeypatch.setattr(DaemonConnection, "execute_delegated", execute_delegated)

    def build_system(selected: ConfigProfileSnapshot) -> ExperimentSystem:
        built_from.append(selected)
        return system

    result = DaemonConnection(
        _client(handler),
        build_system=build_system,
    ).run_scratch(load_invocation())

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
    connection = DaemonConnection(
        _client(
            lambda request: pytest.fail(
                f"unexpected daemon request: {request.method} {request.url.path}"
            )
        )
    )

    with pytest.raises(ValueError, match="requires an experiment system"):
        connection.run_scratch(load_invocation(), config=load_config())


def test_preview_scratch_uses_active_config_without_admission() -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _model(ActiveConfigView(entry=entry, active_state=state, config=config))

    preview = DaemonConnection(
        _client(handler),
        build_system=lambda _config: ExperimentSystem(
            provider=TestSignalInstrumentProvider()
        ),
    ).preview_scratch(load_invocation())

    assert preview.point_count > 0
    assert [request.url.path for request in requests] == [
        "/api/v1/config-registry/active"
    ]


def _planned(tmp_path: Path) -> PlannedRun:
    provider = TestSignalInstrumentProvider()
    return plan_experiment(
        load_prepared_invocation(),
        config=load_config(),
        services=embedded_workspace_services(tmp_path),
        system=ExperimentSystem(provider=provider),
    )


def _client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> DaemonClient:
    return DaemonClient(
        "http://daemon.local",
        transport=httpx.MockTransport(handler),
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


def _model(model: BaseModel, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=model.model_dump(mode="json"))
