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

import scopecat.api._runner as runner_module
from scopecat.analysis.service import AnalysisOutput, prepare_analysis_artifact
from scopecat.api._remote import RemoteRunOperations
from scopecat.api._runner import _DaemonRunner
from scopecat.api.lab import LabClient
from scopecat.config.drafts import ConfigDraft
from scopecat.config.registry.records import (
    ConfigRegistryActivationRecord,
    ConfigRegistryActiveState,
    ConfigRegistryEntry,
    DirectConfigRegistrySource,
    ManualConfigDraftRegistrySource,
)
from scopecat.config.resolution import config_revision_entry_id
from scopecat.control.models import ResourceKey
from scopecat.daemon.client import DaemonClient, DaemonConflictError
from scopecat.daemon.execution import ExecutorLeaseLostError
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigDraftPreview,
    ConfigRegistryView,
)
from scopecat.daemon.wire import (
    AnalysisArtifactOutputPayload,
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
    ConfigActivationReceipt,
    ConfigDefaultReceipt,
    ConfigDraftDefaultCommand,
    ConfigDraftDefaultReceipt,
    ConfigDraftRegistrationCommand,
    ConfigDraftRegistrationReceipt,
    ConfigRollbackCommand,
    DirectConfigDefaultCommand,
    ExecutorLease,
    RunAdmission,
    RunSubmission,
)
from scopecat.execution.program import RunProgram
from scopecat.execution.services import ExecutionSession
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.planning.preview import build_run_program_preview
from scopecat.planning.service import PlannedRun
from scopecat.planning.system import ExperimentSystem
from scopecat.records.artifact import RunContentEntry
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.run import (
    ConfigRegistryRunConfigSource,
    RunManifest,
)
from scopecat.runs.repository import TerminalRunCommit
from scopecat.sdk.instruments.contracts import InstrumentProvider
from tests.testkit.runtime import plan_experiment, sqlite_project_services
from tests.testkit.signal_instruments import TestSignalInstrumentProvider
from tests.testkit.workflow_fixtures import (
    load_config,
    load_invocation,
)

_NOW = datetime(2026, 7, 23, 9, tzinfo=UTC)


def test_execute_submits_complete_plan_and_heartbeats(
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

    def fail_preview(_program: RunProgram) -> None:
        pytest.fail("execution admission must not build a preview")

    monkeypatch.setattr(
        runner_module,
        "build_run_program_preview",
        fail_preview,
    )
    heartbeat_seen = Event()
    heartbeat_count = 0
    submissions: list[RunSubmission] = []
    forwarded: dict[str, object] = {}

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        nonlocal heartbeat_count
        path = http_request.url.path
        if path.endswith("/runs"):
            submission = RunSubmission.model_validate_json(http_request.content)
            submissions.append(submission)
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
        program: RunProgram,
        session: ExecutionSession,
        instrument_provider: InstrumentProvider | None,
    ) -> RunManifest:
        forwarded.update(
            program=program,
            instrument_provider=instrument_provider,
        )
        accepted = session.accepted
        assert session.config == planned.config
        session.begin()
        assert heartbeat_seen.wait(timeout=1)
        return _terminal_manifest(accepted)

    monkeypatch.setattr(runner_module, "execute_admitted_run", execute)

    result = _DaemonRunner(_client(handler), None).execute(
        planned,
        executor_id="notebook-1",
        submission_id="submission-1",
    )
    completed_heartbeats = heartbeat_count
    time.sleep(0.03)

    [submission] = submissions
    assert submission.submission_id == "submission-1"
    assert submission.config == planned.config
    assert submission.config_source == planned.config_source
    assert submission.request == planned.request
    assert submission.plan.experiment_id == preview.experiment_id
    assert submission.plan.experiment_kind == preview.experiment_kind
    assert submission.plan.point_count == preview.point_count
    assert submission.plan.coordinate_ids == preview.coordinate_ids
    assert submission.plan.record_ids == tuple(record.id for record in preview.records)
    assert submission.plan.run_resource_claims == tuple(
        ResourceKey(id=claim.id, kind=claim.kind)
        for claim in planned.program.resource_claims
    )
    assert forwarded["program"] == planned.program
    assert forwarded["instrument_provider"] == (
        None if planned.system is None else planned.system.provider
    )
    assert result.status == "completed"
    assert completed_heartbeats >= 1
    assert heartbeat_count == completed_heartbeats


def test_execute_fences_effects_after_heartbeat_loses_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planned = _planned(tmp_path)
    heartbeat_attempted = Event()
    admissions: list[RunAdmission] = []

    def handler(http_request: httpx2.Request) -> httpx2.Response:
        path = http_request.url.path
        if path.endswith("/runs"):
            submission = RunSubmission.model_validate_json(http_request.content)
            admission = _admission(submission)
            admissions.append(admission)
            return _model(admission, status_code=201)
        if path.endswith("/executor/start"):
            return _model(_lease(heartbeat_interval=0.005))
        if path.endswith("/executor/heartbeat"):
            heartbeat_attempted.set()
            return httpx2.Response(409, json={"detail": "executor lease expired"})
        if path.endswith("/terminal"):
            return _model(
                admissions[-1].manifest.model_copy(
                    update={
                        "outcome": RunOutcome(
                            run_id=admissions[-1].manifest.run_id,
                            result="succeeded",
                            certainty="known",
                        )
                    }
                )
            )
        raise AssertionError(f"unexpected request: {http_request.method} {path}")

    def execute(
        *,
        program: RunProgram,
        session: ExecutionSession,
        instrument_provider: InstrumentProvider | None,
    ) -> RunManifest:
        del program, instrument_provider
        session.begin()
        assert heartbeat_attempted.wait(timeout=1)
        terminal = TerminalRunCommit(
            run_id=session.run_id,
            outcome=RunOutcome(
                run_id=session.run_id,
                result="succeeded",
                certainty="known",
            ),
        )
        deadline = time.monotonic() + 1
        while True:
            try:
                session.commit_terminal(terminal)
            except ExecutorLeaseLostError:
                raise
            if time.monotonic() >= deadline:
                raise AssertionError("heartbeat failure did not fence effects")
            time.sleep(0.001)

    monkeypatch.setattr(runner_module, "execute_admitted_run", execute)

    with pytest.raises(
        ExecutorLeaseLostError,
        match=r"lease 'lease-1'.*is no longer live",
    ) as error:
        _DaemonRunner(_client(handler), None).execute(
            planned,
            executor_id="notebook-1",
        )

    assert isinstance(error.value.cause, DaemonConflictError)


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


def test_remote_analysis_artifacts_send_prepared_snapshots() -> None:
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
        json_output.filename,
        json_output.media_type,
        b64decode(json_output.content_base64),
    ) == ("fit-json.json", "application/json", b'{\n  "ok": true\n}\n')
    assert (
        text_output.filename,
        text_output.media_type,
        b64decode(text_output.content_base64),
    ) == ("fit-text.txt", "text/plain", b"fit converged\n")


def test_run_scratch_plans_against_explicit_snapshot_without_local_storage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = load_config()
    provider = TestSignalInstrumentProvider()
    system = ExperimentSystem(provider=provider)
    captured: dict[str, object] = {}

    def execute_run(
        self: _DaemonRunner,
        planned: PlannedRun,
        *,
        executor_id: str,
        submission_id: str | None = None,
    ) -> RunManifest:
        del self
        captured.update(
            planned=planned,
            executor_id=executor_id,
            submission_id=submission_id,
        )
        accepted = RunManifest(
            run_id="run-scratch",
            config_content_hash=planned.program.config_content_hash,
        )
        return _terminal_manifest(accepted)

    monkeypatch.setattr(_DaemonRunner, "execute", execute_run)

    result = _DaemonRunner(
        _client(lambda _request: httpx2.Response(500)),
        lambda _config: system,
    ).run(
        load_invocation(),
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

    def execute_run(
        self: _DaemonRunner,
        planned: PlannedRun,
        *,
        executor_id: str,
        submission_id: str | None = None,
    ) -> RunManifest:
        del self, executor_id, submission_id
        captured["planned"] = planned
        return _terminal_manifest(
            RunManifest(
                run_id="run-scratch",
                config_content_hash=planned.program.config_content_hash,
            )
        )

    monkeypatch.setattr(_DaemonRunner, "execute", execute_run)

    def build_system(selected: ConfigProfileSnapshot) -> ExperimentSystem:
        built_from.append(selected)
        return system

    result = _DaemonRunner(
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
    runner = _DaemonRunner(
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

    preview = _DaemonRunner(
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
        load_invocation(),
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


def _admission(submission: RunSubmission) -> RunAdmission:
    return RunAdmission(
        submission_id=submission.submission_id,
        manifest=RunManifest(
            run_id="run-1",
            created_at=_NOW,
            config_content_hash=config_content_hash(submission.config),
            config_source=submission.config_source,
        ),
    )


def _lease(*, heartbeat_interval: float) -> ExecutorLease:
    return ExecutorLease(
        lease_id="lease-1",
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
    )
    return accepted.model_copy(
        update={
            "outcome": outcome,
        }
    )


def _model(model: BaseModel, *, status_code: int = 200) -> httpx2.Response:
    return httpx2.Response(status_code, json=model.model_dump(mode="json"))
