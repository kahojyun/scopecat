from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import httpx
import pytest
from pydantic import BaseModel

import scopecat.daemon.workspace as workspace_module
from scopecat.composition.embedded import embedded_workspace_services
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
    DaemonClient,
    DaemonConflictError,
    DaemonHealth,
    DaemonWorkspace,
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
    ConfigEntryView,
    ConfigRegistryView,
)
from scopecat.daemon.wire import (
    ConfigActivationReceipt,
    ConfigEntryActivationCommand,
    ConfigImportReceipt,
    ConfigRollbackCommand,
    DirectConfigImportCommand,
)
from scopecat.execution.observation import RuntimeEvent, RuntimePayloadObservation
from scopecat.execution.program import RunProgram
from scopecat.execution.services import ExecutionServices
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.run import RunManifest, RunOutcome
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


def test_workspace_exposes_browsing_and_managed_submission() -> None:
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
            return _model(DaemonHealth(status="ok", workspace_id="workspace-1"))
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
    workspace = DaemonWorkspace(client)

    assert workspace.health().workspace_id == "workspace-1"
    assert workspace.catalog().experiments[0].id == "ramsey"
    assert workspace.runs(state="accepted").items == (run,)
    assert workspace.get_run(run.run_id).control == run
    assert workspace.events(run_id=run.run_id).items == (event,)
    admission = workspace.submit_managed(
        "ramsey",
        "1",
        request,
        submission_id="managed-submission",
    )

    assert admission.submission_id == "managed-submission"
    assert seen_submission_ids == ["managed-submission"]
    workspace.close()
    assert client.health().status == "ok"


def test_execute_delegated_submits_complete_plan_and_heartbeats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned = _planned(tmp_path)
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

    monkeypatch.setattr(workspace_module, "execute_admitted_run", execute)
    provider = TestSignalInstrumentProvider()

    def event_sink(_event: RuntimeEvent) -> None:
        pass

    def payload_observer(_event: RuntimePayloadObservation) -> None:
        pass

    result = DaemonWorkspace(_client(handler)).execute_delegated(
        planned,
        executor_id="notebook-1",
        submission_id="delegated-submission",
        instrument_provider=provider,
        event_sink=event_sink,
        payload_observer=payload_observer,
    )
    completed_heartbeats = heartbeat_count
    time.sleep(0.03)

    [submission] = delegated_submissions
    assert submission.submission_id == "delegated-submission"
    assert submission.config == planned.config
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
        "instrument_provider": provider,
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

    monkeypatch.setattr(workspace_module, "execute_admitted_run", execute)

    with pytest.raises(
        DelegatedExecutorLeaseLostError,
        match="generation 7 is no longer live",
    ) as error:
        DaemonWorkspace(_client(handler)).execute_delegated(
            planned,
            executor_id="notebook-1",
        )

    assert isinstance(error.value.cause, DaemonConflictError)


def test_execute_delegated_requires_a_durable_request(tmp_path: Path) -> None:
    planned = _planned(tmp_path)
    workspace = DaemonWorkspace(_client(lambda _request: httpx.Response(500)))

    with pytest.raises(ValueError, match="durable run request"):
        workspace.execute_delegated(
            PlannedRun(
                config=planned.config,
                request=None,
                program=planned.program,
            ),
            executor_id="notebook-1",
        )


def test_workspace_composes_config_registry_commands() -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    seen: list[object] = []

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

    workspace = DaemonWorkspace(_client(handler))

    assert workspace.config_registry().active_state == state
    assert workspace.active_config().config == config
    assert workspace.config_entry("baseline").config == config
    assert (
        workspace.import_direct_config(
            config,
            entry_id="baseline",
            registered_by="notebook",
        ).entry
        == entry
    )
    assert (
        workspace.activate_config_entry(
            "baseline",
            operator="operator",
        ).active_state
        == state
    )
    assert (
        workspace.rollback_config(
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
        self: DaemonWorkspace,
        planned: PlannedRun,
        *,
        executor_id: str,
        submission_id: str | None = None,
        instrument_provider: InstrumentProvider | None = None,
        event_sink: Callable[[RuntimeEvent], None] | None = None,
        payload_observer: Callable[[RuntimePayloadObservation], None] | None = None,
    ) -> RunManifest:
        del self, event_sink, payload_observer
        captured.update(
            planned=planned,
            executor_id=executor_id,
            submission_id=submission_id,
            instrument_provider=instrument_provider,
        )
        accepted = RunManifest(
            run_id="run-scratch",
            lifecycle="accepted",
            config_content_hash=planned.program.config_content_hash,
        )
        return _terminal_manifest(accepted)

    monkeypatch.setattr(DaemonWorkspace, "execute_delegated", execute_delegated)

    experiment = load_prepared_invocation() if prepared else load_invocation()
    result = DaemonWorkspace(_client(lambda _request: httpx.Response(500))).run_scratch(
        experiment,
        config=config,
        system=system,
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
    assert captured["instrument_provider"] is provider
    assert result.status == "completed"


def test_run_scratch_uses_active_config_and_bound_system(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    provider = TestSignalInstrumentProvider()
    system = ExperimentSystem(provider=provider)
    captured: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        assert http_request.url.path == "/api/v1/config-registry/active"
        return _model(ActiveConfigView(entry=entry, active_state=state, config=config))

    def execute_delegated(
        self: DaemonWorkspace,
        planned: PlannedRun,
        *,
        executor_id: str,
        submission_id: str | None = None,
        instrument_provider: InstrumentProvider | None = None,
        event_sink: Callable[[RuntimeEvent], None] | None = None,
        payload_observer: Callable[[RuntimePayloadObservation], None] | None = None,
    ) -> RunManifest:
        del self, executor_id, submission_id, event_sink, payload_observer
        captured.update(
            planned=planned,
            instrument_provider=instrument_provider,
        )
        return _terminal_manifest(
            RunManifest(
                run_id="run-scratch",
                lifecycle="accepted",
                config_content_hash=planned.program.config_content_hash,
            )
        )

    monkeypatch.setattr(DaemonWorkspace, "execute_delegated", execute_delegated)

    result = DaemonWorkspace(
        _client(handler),
        system=system,
    ).run_scratch(load_invocation())

    planned = captured["planned"]
    assert isinstance(planned, PlannedRun)
    assert planned.config == config
    assert captured["instrument_provider"] is provider
    assert result.status == "completed"


def test_run_scratch_requires_an_explicit_or_bound_system() -> None:
    workspace = DaemonWorkspace(
        _client(
            lambda request: pytest.fail(
                f"unexpected daemon request: {request.method} {request.url.path}"
            )
        )
    )

    with pytest.raises(ValueError, match="requires an experiment system"):
        workspace.run_scratch(load_invocation(), config=load_config())


def test_preview_scratch_uses_active_config_without_admission() -> None:
    config = load_config()
    entry, state = _config_registry_records(config)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _model(ActiveConfigView(entry=entry, active_state=state, config=config))

    preview = DaemonWorkspace(
        _client(handler),
        system=ExperimentSystem(provider=TestSignalInstrumentProvider()),
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
