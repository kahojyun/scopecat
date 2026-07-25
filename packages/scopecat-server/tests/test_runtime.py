from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Never

import pytest
from fastapi.testclient import TestClient
from scopecat.adapters.sqlite import SQLiteControlPlane, SQLiteRunRepository
from scopecat.application import LabApplication
from scopecat.authoring import ExperimentBody, experiment, template
from scopecat.config.changes import parameter_change_proposal_from_updates
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.profiles import load_config_profile
from scopecat.control.models import (
    ControlRun,
    DurableEvent,
    DurableEventInput,
    EventPage,
    ResourceLease,
)
from scopecat.daemon.catalog import (
    RegisteredExperiment,
    RegisteredExperimentCatalog,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigDraftPreview,
    ConfigRegistryView,
    ParameterProposalListView,
    RunConfigView,
    RunDetail,
)
from scopecat.daemon.wire import (
    AnalysisArtifactOutputPayload,
    AnalysisJsonOutputPayload,
    AnalysisNoteOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
    AttentionResolutionCommand,
    CandidateConfigActivationCommand,
    CandidateConfigActivationReceipt,
    ConfigActivationReceipt,
    ConfigDefaultReceipt,
    ConfigDraftCommand,
    ConfigDraftDefaultCommand,
    ConfigDraftDefaultReceipt,
    ConfigDraftRegistrationCommand,
    ConfigEntryActivationCommand,
    ConfigImportReceipt,
    ConfigRollbackCommand,
    DelegatedPlanSummary,
    DelegatedRunSubmission,
    DirectConfigDefaultCommand,
    DirectConfigImportCommand,
    ExecutionRecoveryRequest,
    ExecutionTransitionBatch,
    ExecutorLease,
    ExecutorStartRequest,
    ManagedRunSubmission,
    MeasurementAppendCommand,
    ParameterProposalDecisionCommand,
    ParameterProposalReviewReceipt,
    RegisteredExperimentDescriptor,
    ReplaceConfigParameter,
    ResourceClaimDescriptor,
    RunAdmission,
    RunAttachmentCommand,
    RuntimeEventPublishCommand,
    RuntimeProgressPayload,
    RuntimeTransitionEventPayload,
    TerminalRunCommitCommand,
)
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import MeasurementDatasetAppend
from scopecat.records.parameter import Quantity, ScalarParameterValue
from scopecat.records.parameter_change import (
    AutomaticPolicyDecisionAuthority,
    ParameterChangeProposal,
)
from scopecat.records.run import RunManifest, RunOutcome
from scopecat.records.run_request import RunRequest
from scopecat.runs.refs import artifact_content_ref, record_content_ref
from scopecat.sdk.instruments import (
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)

import scopecat_server.services as daemon_services
from scopecat_server import BackendConflict, LocalDaemonRuntime

_FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "core"
    / "simple_scan"
    / "config-profile.json"
)


def _config() -> ConfigProfileSnapshot:
    return load_config_profile(_FIXTURE)


def _run_detail(runtime: LocalDaemonRuntime, run_id: str) -> RunDetail:
    return runtime.application.runs.get_run(run_id)


def _control_run(runtime: LocalDaemonRuntime, run_id: str) -> ControlRun:
    return _run_detail(runtime, run_id).control


def _manifest(runtime: LocalDaemonRuntime, run_id: str) -> RunManifest:
    return _run_detail(runtime, run_id).manifest


def _events(
    runtime: LocalDaemonRuntime,
    *,
    run_id: str | None = None,
) -> EventPage:
    return runtime.application.runs.list_events(
        limit=500,
        after=None,
        run_id=run_id,
    )


def _resource_leases(project_root: Path) -> tuple[ResourceLease, ...]:
    return SQLiteControlPlane(
        project_root / ".scopecat" / "control.sqlite3"
    ).list_resource_leases()


def _run_repository(project_root: Path) -> SQLiteRunRepository:
    state = project_root / ".scopecat"
    return SQLiteRunRepository(state / "control.sqlite3", state / "objects")


def _managed_components(
    runtime: LocalDaemonRuntime,
) -> tuple[daemon_services.ManagedRunSupervisor, daemon_services.AdmissionService]:
    """Reach private collaborators only for supervisor lifecycle fault tests."""

    return runtime.application._managed, runtime.application._admission


class _EmptyInstrumentProvider:
    @property
    def provider_id(self) -> str:
        return "tests.empty"

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        del context
        return InstrumentProviderDescription(provider_id=self.provider_id)

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        del context
        return InstrumentProviderResult(drivers=())


@template(id="tests.managed", kind="managed")
def _managed_experiment() -> ExperimentBody:
    return experiment()


def _managed_catalog() -> RegisteredExperimentCatalog:
    return RegisteredExperimentCatalog(
        (
            RegisteredExperiment(
                id="simple-scan",
                version="1",
                descriptor=RegisteredExperimentDescriptor(
                    id="simple-scan",
                    version="1",
                    experiment_kind="managed",
                    title="Managed smoke test",
                ),
                factory=lambda _request: _managed_experiment(),
            ),
        )
    )


def _submission(
    submission_id: str = "submission-1",
) -> DelegatedRunSubmission:
    return DelegatedRunSubmission(
        submission_id=submission_id,
        executor_id="notebook-1",
        config=_config(),
        request=RunRequest(id="scratch-request"),
        plan=DelegatedPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
            run_resource_claims=(
                ResourceClaimDescriptor(id="scope-1", kind="instrument"),
            ),
        ),
    )


def _analysis_proposal(run_id: str) -> ParameterChangeProposal:
    return parameter_change_proposal_from_updates(
        source_run_id=run_id,
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


def _analysis_command(
    run_id: str,
    proposal: ParameterChangeProposal,
) -> AnalysisSaveCommand:
    return AnalysisSaveCommand(
        run_id=run_id,
        title="fit",
        analysis_key="fit",
        outputs=(
            AnalysisNoteOutputPayload(
                kind="note",
                title="summary",
                content="fit converged",
            ),
            AnalysisJsonOutputPayload(
                kind="table",
                title="fit parameters",
                content=[{"frequency": 5.1}],
            ),
            AnalysisJsonOutputPayload(
                kind="figure",
                title="fit curve",
                content={"x": [1, 2], "y": [3, 4]},
            ),
            AnalysisParameterProposalOutputPayload(
                kind="parameter_change_proposal",
                title=proposal.id,
                content=proposal,
            ),
            AnalysisArtifactOutputPayload(
                kind="artifact",
                title="fit report",
                artifact_kind="fit_report",
                artifact_id="fit-report",
                content_base64="eyJvayI6IHRydWV9Cg==",
                source_default_extension=".json",
                source_default_media_type="application/json",
            ),
            AnalysisArtifactOutputPayload(
                kind="artifact",
                title="fit summary",
                artifact_kind="fit_summary",
                artifact_id="fit-summary",
                content_base64="Zml0IGNvbnZlcmdlZAo=",
                source_default_extension=".txt",
                source_default_media_type="text/plain",
            ),
        ),
    )


def test_runtime_bootstraps_project_control_plane_and_health(tmp_path: Path) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        response = TestClient(runtime.app()).get("/api/v1/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["project_id"].startswith("local:")
        assert response.json()["project_name"] == tmp_path.name
        assert response.json()["project_root"] == str(tmp_path)
        assert (tmp_path / ".scopecat" / "control.sqlite3").is_file()
        assert (tmp_path / ".scopecat" / "objects").is_dir()


@pytest.mark.parametrize("failure_point", ["reconciliation", "thread"])
def test_runtime_cleans_up_partially_started_supervisor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: Literal["reconciliation", "thread"],
) -> None:
    class TrackingWorkers:
        def __init__(self) -> None:
            self.shutdown_called = False

        def shutdown(self, *, wait: bool, cancel_futures: bool) -> None:
            assert wait
            assert not cancel_futures
            self.shutdown_called = True

    workers = TrackingWorkers()

    def build_workers(
        *,
        max_workers: int,
        thread_name_prefix: str,
    ) -> TrackingWorkers:
        del max_workers, thread_name_prefix
        return workers

    monkeypatch.setattr(
        daemon_services,
        "ThreadPoolExecutor",
        build_workers,
    )

    if failure_point == "reconciliation":

        def fail_reconciliation(_supervisor: object) -> Never:
            raise RuntimeError("startup reconciliation failed")

        monkeypatch.setattr(
            daemon_services.ManagedRunSupervisor,
            "_reconcile_startup",
            fail_reconciliation,
        )
    else:

        class FailingThread:
            def start(self) -> Never:
                raise RuntimeError("supervisor thread failed to start")

        def build_thread(
            *,
            target: object,
            name: str,
            daemon: bool,
        ) -> FailingThread:
            del target, name, daemon
            return FailingThread()

        monkeypatch.setattr(daemon_services, "Thread", build_thread)

    with pytest.raises(RuntimeError, match=r"(reconciliation|thread) failed"):
        LocalDaemonRuntime(tmp_path)

    assert workers.shutdown_called


def test_runtime_exclusively_owns_one_project(tmp_path: Path) -> None:
    factory_calls = 0

    def application_factory(_project_root: Path) -> Never:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("factory must not run before project ownership")

    with (
        LocalDaemonRuntime(tmp_path),
        pytest.raises(RuntimeError, match="already has a running daemon"),
    ):
        LocalDaemonRuntime(tmp_path, application_factory=application_factory)

    assert factory_calls == 0
    with LocalDaemonRuntime(tmp_path) as reopened:
        assert reopened.application.health().status == "ok"


def test_bootstrap_config_is_active_and_idempotent_across_restarts(
    tmp_path: Path,
) -> None:
    bootstrap_calls = 0

    def bootstrap_config() -> ConfigProfileSnapshot:
        nonlocal bootstrap_calls
        bootstrap_calls += 1
        if bootstrap_calls > 1:
            raise AssertionError("an initialized registry must not resolve its seed")
        return _config()

    def factory(_root: Path) -> LabApplication:
        return LabApplication(bootstrap_config=bootstrap_config)

    with LocalDaemonRuntime(tmp_path, application_factory=factory) as runtime:
        first = runtime.application.config.get_active_config().active_state
        first_events = _events(runtime).items

    with LocalDaemonRuntime(tmp_path, application_factory=factory) as reopened:
        second = reopened.application.config.get_active_config().active_state
        second_events = _events(reopened).items

    assert first.active_entry_id.startswith("daemon-")
    assert second == first
    assert [event.kind for event in first_events] == [
        "config_imported",
        "config_activated",
    ]
    assert second_events == first_events
    assert bootstrap_calls == 1


def test_bootstrap_config_does_not_replace_later_activation(
    tmp_path: Path,
) -> None:
    bootstrap = _config()
    selected = bootstrap.model_copy(update={"id": "operator-selected"})

    def factory(_root: Path) -> LabApplication:
        return LabApplication(bootstrap_config=lambda: bootstrap)

    with LocalDaemonRuntime(tmp_path, application_factory=factory) as runtime:
        activation = runtime.application.config.set_direct_config_default(
            DirectConfigDefaultCommand(
                config=selected,
                entry_id="operator-selected",
                registered_by="operator",
                operator="operator",
                expected_generation=1,
            )
        )

    with LocalDaemonRuntime(tmp_path, application_factory=factory) as reopened:
        state = reopened.application.config.get_active_config().active_state

    assert state.active_entry_id == "operator-selected"
    assert state == activation.active_state


def test_explicit_runtime_bootstrap_overrides_application_seed(
    tmp_path: Path,
) -> None:
    def unavailable_bootstrap() -> ConfigProfileSnapshot:
        raise AssertionError("explicit test config must take precedence")

    def factory(_root: Path) -> LabApplication:
        return LabApplication(bootstrap_config=unavailable_bootstrap)

    explicit = _config().model_copy(update={"id": "explicit-test-bootstrap"})
    with LocalDaemonRuntime(
        tmp_path,
        application_factory=factory,
        bootstrap_config=explicit,
    ) as runtime:
        state = runtime.application.config.get_active_config().active_state

    assert state.active_entry_content_hash == config_content_hash(explicit)


def test_config_registry_http_workflow_persists_and_publishes_events(
    tmp_path: Path,
) -> None:
    baseline = _config().model_copy(update={"id": "baseline"})
    updated = baseline.model_copy(update={"id": "updated"})
    with LocalDaemonRuntime(tmp_path) as runtime:
        client = TestClient(runtime.app())

        empty = ConfigRegistryView.model_validate(
            client.get("/api/v1/config-registry").json()
        )
        missing = client.get("/api/v1/config-registry/active")
        baseline_import = client.post(
            "/api/v1/config-registry/entries",
            json=DirectConfigImportCommand(
                entry_id="baseline",
                config=baseline,
                registered_by="notebook",
            ).model_dump(mode="json"),
        )
        updated_import = client.post(
            "/api/v1/config-registry/entries",
            json=DirectConfigImportCommand(
                entry_id="updated",
                config=updated,
                registered_by="notebook",
            ).model_dump(mode="json"),
        )
        first_activation = client.post(
            "/api/v1/config-registry/active",
            json=ConfigEntryActivationCommand(
                entry_id="baseline",
                operator="operator",
                expected_generation=0,
            ).model_dump(mode="json"),
        )
        second_activation = client.post(
            "/api/v1/config-registry/active",
            json=ConfigEntryActivationCommand(
                entry_id="updated",
                operator="operator",
                expected_generation=1,
            ).model_dump(mode="json"),
        )
        stale_activation = client.post(
            "/api/v1/config-registry/active",
            json=ConfigEntryActivationCommand(
                entry_id="baseline",
                operator="stale-notebook",
                expected_generation=1,
            ).model_dump(mode="json"),
        )
        rollback_response = client.post(
            "/api/v1/config-registry/rollback",
            json=ConfigRollbackCommand(
                operator="operator",
                expected_generation=2,
            ).model_dump(mode="json"),
        )

        registry = ConfigRegistryView.model_validate(
            client.get("/api/v1/config-registry").json()
        )
        active = ActiveConfigView.model_validate(
            client.get("/api/v1/config-registry/active").json()
        )
        events = _events(runtime).items

        assert empty == ConfigRegistryView()
        assert missing.status_code == 404
        assert baseline_import.status_code == 201
        assert updated_import.status_code == 201
        assert (
            ConfigImportReceipt.model_validate(baseline_import.json()).entry.id
            == "baseline"
        )
        assert (
            ConfigActivationReceipt.model_validate(
                first_activation.json()
            ).active_state.generation
            == 1
        )
        assert (
            ConfigActivationReceipt.model_validate(
                second_activation.json()
            ).active_state.generation
            == 2
        )
        assert stale_activation.status_code == 409
        rollback = ConfigActivationReceipt.model_validate(rollback_response.json())
        assert rollback.activation.action == "rollback"
        assert rollback.active_state.generation == 3
        assert rollback.active_state.active_entry_id == "baseline"
        assert [entry.id for entry in registry.entries] == ["baseline", "updated"]
        assert registry.active_state is not None
        assert [record.action for record in registry.active_state.history] == [
            "activation",
            "activation",
            "rollback",
        ]
        assert active.entry.id == "baseline"
        assert active.config == baseline
        assert [(event.kind, event.payload, event.run_id) for event in events] == [
            ("config_imported", {"entry_id": "baseline"}, None),
            ("config_imported", {"entry_id": "updated"}, None),
            (
                "config_activated",
                {"entry_id": "baseline", "generation": 1},
                None,
            ),
            (
                "config_activated",
                {"entry_id": "updated", "generation": 2},
                None,
            ),
            (
                "config_rolled_back",
                {"entry_id": "baseline", "generation": 3},
                None,
            ),
        ]

    with LocalDaemonRuntime(tmp_path) as reopened:
        active = reopened.application.config.get_active_config()
        events = _events(reopened).items

        assert active.entry.id == "baseline"
        assert active.config == baseline
        assert events[-1].kind == "config_rolled_back"


def test_direct_config_set_default_is_atomic_idempotent_and_durable(
    tmp_path: Path,
) -> None:
    baseline = _config()
    tuned = baseline.model_copy(update={"id": "tuned"})
    with LocalDaemonRuntime(tmp_path) as runtime:
        client = TestClient(runtime.app())
        initialized = client.post(
            "/api/v1/config-registry/default",
            json=DirectConfigDefaultCommand(
                entry_id="baseline",
                config=baseline,
                registered_by="notebook",
                operator="notebook",
                expected_generation=0,
                note="initialize the default",
            ).model_dump(mode="json"),
        )
        imported = client.post(
            "/api/v1/config-registry/entries",
            json=DirectConfigImportCommand(
                entry_id="tuned-existing",
                config=tuned,
                registered_by="earlier-notebook",
                note="saved before it became the default",
            ).model_dump(mode="json"),
        )
        command = DirectConfigDefaultCommand(
            entry_id="tuned-generated",
            config=tuned,
            registered_by="notebook",
            operator="notebook",
            expected_generation=1,
            note="use tuned values",
        )

        first_response = client.post(
            "/api/v1/config-registry/default",
            json=command.model_dump(mode="json"),
        )
        retry_response = client.post(
            "/api/v1/config-registry/default",
            json=command.model_dump(mode="json"),
        )
        first = ConfigDefaultReceipt.model_validate(first_response.json())
        retry = ConfigDefaultReceipt.model_validate(retry_response.json())

        assert first_response.status_code == 200
        assert retry_response.status_code == 200
        assert initialized.status_code == 200
        assert imported.status_code == 201
        assert retry == first
        assert first.entry.id == "tuned-existing"
        assert first.active_state.generation == 2
        assert [
            entry.id
            for entry in runtime.application.config.get_config_registry().entries
            if entry.content_hash == config_content_hash(tuned)
        ] == ["tuned-existing"]
        assert [
            event.kind
            for event in _events(runtime).items
            if event.kind in {"config_imported", "config_activated"}
        ][-2:] == ["config_imported", "config_activated"]

    with LocalDaemonRuntime(tmp_path) as reopened:
        active = reopened.application.config.get_active_config()
        assert active.entry.id == "tuned-existing"
        assert active.config == tuned


def test_config_default_rolls_back_registry_and_event_when_event_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = DirectConfigDefaultCommand(
        entry_id="baseline",
        config=_config(),
        registered_by="notebook",
        operator="notebook",
        expected_generation=0,
    )
    append_event = SQLiteControlPlane.append_event_in_transaction

    def fail_activation_event(
        control: SQLiteControlPlane,
        connection: sqlite3.Connection,
        event: DurableEventInput,
    ) -> DurableEvent:
        if event.kind == "config_activated":
            raise RuntimeError("event publication failed")
        return append_event(control, connection, event)

    with LocalDaemonRuntime(tmp_path) as runtime:
        with monkeypatch.context() as patch:
            patch.setattr(
                SQLiteControlPlane,
                "append_event_in_transaction",
                fail_activation_event,
            )
            with pytest.raises(RuntimeError, match="event publication failed"):
                runtime.application.config.set_direct_config_default(command)

        assert runtime.application.config.get_config_registry() == ConfigRegistryView()
        assert _events(runtime).items == ()

        receipt = runtime.application.config.set_direct_config_default(command)

        assert receipt.active_state.generation == 1
        assert [
            entry.id
            for entry in runtime.application.config.get_config_registry().entries
        ] == ["baseline"]
        assert [event.kind for event in _events(runtime).items] == [
            "config_imported",
            "config_activated",
        ]


def test_config_draft_http_workflow_previews_and_atomically_sets_default(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        client = TestClient(runtime.app())
        active = ActiveConfigView.model_validate(
            client.get("/api/v1/config-registry/active").json()
        )
        draft = ConfigDraftCommand(
            base_entry_id=active.entry.id,
            base_content_hash=active.entry.content_hash,
            base_generation=active.active_state.generation,
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

        preview_response = client.post(
            "/api/v1/config-registry/drafts/preview",
            json=draft.model_dump(mode="json"),
        )
        preview = ConfigDraftPreview.model_validate(preview_response.json())
        assert preview.result_content_hash is not None
        default_response = client.post(
            "/api/v1/config-registry/drafts/set-default",
            json=ConfigDraftDefaultCommand(
                registration=ConfigDraftRegistrationCommand(
                    draft=draft,
                    expected_result_content_hash=preview.result_content_hash,
                    entry_id="manual-tuning",
                    registered_by="operator",
                ),
                operator="operator",
            ).model_dump(mode="json"),
        )
        default = ConfigDraftDefaultReceipt.model_validate(default_response.json())

        assert preview_response.status_code == 200
        assert preview.valid
        assert default_response.status_code == 200
        assert default.result_content_hash == preview.result_content_hash
        assert default.active_state.active_entry_id == "manual-tuning"
        assert default.active_state.generation == active.active_state.generation + 1

    with LocalDaemonRuntime(tmp_path) as reopened:
        active = reopened.application.config.get_active_config()
        parameter = active.config.parameter_snapshot.get("drive_frequency")

        assert active.entry.id == "manual-tuning"
        assert isinstance(parameter, ScalarParameterValue)
        assert parameter.value == Quantity(value=5.1, unit="GHz")


def test_delegated_admission_is_durably_idempotent(tmp_path: Path) -> None:
    submission = _submission()
    with LocalDaemonRuntime(tmp_path) as runtime:
        client = TestClient(runtime.app())
        first = client.post(
            "/api/v1/runs",
            json=submission.model_dump(mode="json"),
        )
        retry = client.post(
            "/api/v1/runs",
            json=submission.model_dump(mode="json"),
        )
        changed = client.post(
            "/api/v1/runs",
            json=submission.model_copy(
                update={"executor_id": "other-notebook"}
            ).model_dump(mode="json"),
        )

        assert first.status_code == 201
        assert retry.status_code == 201
        assert retry.json() == first.json()
        assert changed.status_code == 409
        run_id = RunAdmission.model_validate(first.json()).run_id
        assert _manifest(runtime, run_id).lifecycle == "accepted"
        assert [
            event.kind
            for event in _events(runtime, run_id=run_id).items
            if event.kind == "run_admitted"
        ] == ["run_admitted"]

    with LocalDaemonRuntime(tmp_path) as reopened:
        persisted = reopened.application.submit_run(submission)
        assert persisted.run_id == run_id


def test_post_run_analysis_policy_acceptance_and_candidate_activation_closed_loop(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        client = TestClient(runtime.app())
        admission = runtime.application.submit_run(_submission("post-run-loop"))
        proposal = _analysis_proposal(admission.run_id)
        analysis_command = _analysis_command(admission.run_id, proposal)
        analysis_url = f"/api/v1/runs/{admission.run_id}/analyses"
        first_save = client.post(
            analysis_url,
            json=analysis_command.model_dump(mode="json"),
        )
        retry_save = client.post(
            analysis_url,
            json=analysis_command.model_dump(mode="json"),
        )
        analyses = client.get(analysis_url)
        analysis_detail = client.get(
            f"{analysis_url}/analysis-{analysis_command.analysis_key}"
        )
        analysis_record = client.get(
            f"/api/v1/runs/{admission.run_id}/records/"
            f"analysis-{analysis_command.analysis_key}/json",
            params={"expected_kind": "analysis"},
        )
        analysis_artifact = client.get(
            f"/api/v1/runs/{admission.run_id}/artifacts/fit-report/json",
            params={"expected_kind": "fit_report"},
        )
        analysis_summary = client.get(
            f"/api/v1/runs/{admission.run_id}/artifacts/fit-summary/text",
            params={"expected_kind": "fit_summary"},
        )
        attachment_command = RunAttachmentCommand(
            run_id=admission.run_id,
            key="notebook-notes",
            text="operator notes",
            filename="notes.md",
            media_type="text/markdown",
        )
        attachment = client.post(
            f"/api/v1/runs/{admission.run_id}/attachments",
            json=attachment_command.model_dump(mode="json"),
        )
        attachment_text = client.get(
            f"/api/v1/runs/{admission.run_id}/artifacts/notebook-notes/text",
            params={"expected_kind": "attachment"},
        )
        config = RunConfigView.model_validate(
            client.get(f"/api/v1/runs/{admission.run_id}/config").json()
        )
        proposals = ParameterProposalListView.model_validate(
            client.get(f"/api/v1/runs/{admission.run_id}/parameter-proposals").json()
        )
        decision_command = ParameterProposalDecisionCommand(
            run_id=admission.run_id,
            proposal_id=proposal.id,
            decision="approved",
            authority=AutomaticPolicyDecisionAuthority(
                actor="nightly-calibration",
                policy_id="fit-confidence",
                policy_version="2",
            ),
            note="fit evidence accepted",
        )
        decided = client.post(
            f"/api/v1/runs/{admission.run_id}/parameter-proposals/"
            f"{proposal.id}/decision",
            json=decision_command.model_dump(mode="json"),
        )
        decided_proposals = ParameterProposalListView.model_validate(
            client.get(f"/api/v1/runs/{admission.run_id}/parameter-proposals").json()
        )
        activated = client.post(
            "/api/v1/config-registry/candidates/activate",
            json=CandidateConfigActivationCommand(
                run_id=admission.run_id,
                proposal_ids=(proposal.id,),
                entry_id="candidate-fit",
                registered_by="notebook",
                operator="operator",
                expected_generation=1,
            ).model_dump(mode="json"),
        )

        saved = AnalysisSaveReceipt.model_validate(first_save.json())
        retry = AnalysisSaveReceipt.model_validate(retry_save.json())
        decision = ParameterProposalReviewReceipt.model_validate(decided.json())
        activation = CandidateConfigActivationReceipt.model_validate(activated.json())
        events = _events(runtime, run_id=admission.run_id).items

        assert first_save.status_code == 201
        assert retry == saved
        assert analyses.json()["items"][0]["analysis"]["key"] == "fit"
        assert analysis_detail.json()["entry"]["id"] == "analysis-fit"
        assert analysis_record.json()["content"]["title"] == "fit"
        assert analysis_artifact.json()["content"] == {"ok": True}
        assert [artifact.filename for artifact in saved.output_artifacts] == [
            "fit-report.json",
            "fit-summary.txt",
        ]
        assert [artifact.media_type for artifact in saved.output_artifacts] == [
            "application/json",
            "text/plain",
        ]
        assert analysis_summary.json()["content"] == "fit converged\n"
        assert attachment.json()["artifact"]["filename"] == "notes.md"
        assert attachment_text.json()["content"] == "operator notes\n"
        assert config.config == _config()
        assert proposals.items[0].proposal == proposal
        assert proposals.items[0].decisions == ()
        assert decision.decision.decision == "approved"
        assert decision.decision.authority == decision_command.authority
        assert decided_proposals.items[0].decisions == (decision.decision,)
        assert activation.entry.id == "candidate-fit"
        assert activation.active_state.generation == 2
        assert [
            event.kind
            for event in events
            if event.kind
            in {
                "analysis_saved",
                "parameter_proposal_decided",
                "config_activated",
            }
        ] == [
            "analysis_saved",
            "parameter_proposal_decided",
            "config_activated",
        ]


def test_analysis_publication_rolls_back_refs_manifest_and_event_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        admission = runtime.application.submit_run(_submission("analysis-atomic"))
        proposal = _analysis_proposal(admission.run_id)
        command = _analysis_command(admission.run_id, proposal)
        before = _manifest(runtime, admission.run_id)
        append_event = SQLiteControlPlane.append_event_in_transaction

        def fail_analysis_event(
            control: SQLiteControlPlane,
            connection: sqlite3.Connection,
            event: DurableEventInput,
        ) -> DurableEvent:
            if event.kind == "analysis_saved":
                raise RuntimeError("analysis event publication failed")
            return append_event(control, connection, event)

        with monkeypatch.context() as patch:
            patch.setattr(
                SQLiteControlPlane,
                "append_event_in_transaction",
                fail_analysis_event,
            )
            with pytest.raises(
                RuntimeError,
                match="analysis event publication failed",
            ):
                runtime.application.runs.save_run_analysis(
                    admission.run_id,
                    command,
                )

        repository = _run_repository(tmp_path)
        assert _manifest(runtime, admission.run_id) == before
        assert runtime.application.runs.list_run_analyses(admission.run_id).items == ()
        assert (
            runtime.application.runs.list_parameter_proposals(admission.run_id).items
            == ()
        )
        assert not repository.exists(
            admission.run_id,
            record_content_ref(record_id="analysis-fit", kind="analysis"),
        )
        assert not repository.exists(
            admission.run_id,
            artifact_content_ref(artifact_id="fit-report", kind="fit_report"),
        )
        assert [
            event.kind
            for event in _events(runtime, run_id=admission.run_id).items
            if event.kind == "analysis_saved"
        ] == []

        saved = runtime.application.runs.save_run_analysis(
            admission.run_id,
            command,
        )

        assert saved.record.id == "analysis-fit"
        assert (
            len(runtime.application.runs.list_run_analyses(admission.run_id).items) == 1
        )
        assert [
            event.kind
            for event in _events(runtime, run_id=admission.run_id).items
            if event.kind == "analysis_saved"
        ] == ["analysis_saved"]


def test_parameter_decision_publication_rolls_back_with_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        admission = runtime.application.submit_run(_submission("decision-atomic"))
        proposal = _analysis_proposal(admission.run_id)
        runtime.application.runs.save_run_analysis(
            admission.run_id,
            _analysis_command(admission.run_id, proposal),
        )
        command = ParameterProposalDecisionCommand(
            run_id=admission.run_id,
            proposal_id=proposal.id,
            decision="approved",
            authority=AutomaticPolicyDecisionAuthority(
                actor="nightly-calibration",
                policy_id="fit-confidence",
                policy_version="2",
            ),
        )
        before = _manifest(runtime, admission.run_id)
        append_event = SQLiteControlPlane.append_event_in_transaction

        def fail_decision_event(
            control: SQLiteControlPlane,
            connection: sqlite3.Connection,
            event: DurableEventInput,
        ) -> DurableEvent:
            if event.kind == "parameter_proposal_decided":
                raise RuntimeError("decision event publication failed")
            return append_event(control, connection, event)

        with monkeypatch.context() as patch:
            patch.setattr(
                SQLiteControlPlane,
                "append_event_in_transaction",
                fail_decision_event,
            )
            with pytest.raises(
                RuntimeError,
                match="decision event publication failed",
            ):
                runtime.application.runs.decide_parameter_proposal(
                    admission.run_id,
                    command,
                )

        proposals = runtime.application.runs.list_parameter_proposals(admission.run_id)
        assert _manifest(runtime, admission.run_id) == before
        assert proposals.items[0].decisions == ()
        assert [
            event.kind
            for event in _events(runtime, run_id=admission.run_id).items
            if event.kind == "parameter_proposal_decided"
        ] == []

        receipt = runtime.application.runs.decide_parameter_proposal(
            admission.run_id,
            command,
        )
        proposals = runtime.application.runs.list_parameter_proposals(admission.run_id)

        assert proposals.items[0].decisions == (receipt.decision,)
        assert [
            event.kind
            for event in _events(runtime, run_id=admission.run_id).items
            if event.kind == "parameter_proposal_decided"
        ] == ["parameter_proposal_decided"]


def test_executor_start_is_atomic_idempotent_and_quiet_when_resources_busy(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        first = runtime.application.submit_run(_submission("executor-first"))
        first_manifest = _manifest(runtime, first.run_id)
        request = ExecutorStartRequest(
            run_id=first.run_id,
            executor_id="notebook-1",
            manifest=first_manifest.model_copy(update={"lifecycle": "running"}),
        )

        lease = runtime.application.executor.start_executor(first.run_id, request)
        retry = runtime.application.executor.start_executor(first.run_id, request)

        assert retry == lease
        assert (
            len(
                [
                    event
                    for event in _events(runtime, run_id=first.run_id).items
                    if event.kind == "executor_lease_granted"
                ]
            )
            == 1
        )

        waiting = runtime.application.submit_run(_submission("executor-waiting"))
        waiting_manifest = _manifest(runtime, waiting.run_id)
        with pytest.raises(BackendConflict, match="resources are busy"):
            runtime.application.executor.start_executor(
                waiting.run_id,
                ExecutorStartRequest(
                    run_id=waiting.run_id,
                    executor_id="notebook-2",
                    manifest=waiting_manifest.model_copy(
                        update={"lifecycle": "running"}
                    ),
                ),
            )

        assert _control_run(runtime, waiting.run_id).state == "accepted"
        assert _manifest(runtime, waiting.run_id).lifecycle == "accepted"
        assert [
            event.kind for event in _events(runtime, run_id=waiting.run_id).items
        ] == ["run_admitted"]


def test_executor_start_preserves_content_published_after_manifest_read(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        admission = runtime.application.submit_run(_submission("executor-content-race"))
        stale = _manifest(runtime, admission.run_id)
        attachment = runtime.application.runs.attach_run_content(
            admission.run_id,
            RunAttachmentCommand(
                run_id=admission.run_id,
                key="operator-notes",
                text="keep me",
            ),
        )
        running = stale.model_copy(update={"lifecycle": "running"})

        lease = runtime.application.executor.start_execution(
            admission.run_id,
            executor_id="notebook-1",
            manifest=running,
        )
        retry = runtime.application.executor.start_execution(
            admission.run_id,
            executor_id="notebook-1",
            manifest=running,
        )

        manifest = _manifest(runtime, admission.run_id)
        assert retry == lease
        assert manifest.lifecycle == "running"
        assert attachment.artifact in manifest.artifacts


def test_managed_submission_executes_registered_experiment(tmp_path: Path) -> None:
    with LocalDaemonRuntime(
        tmp_path,
        catalog=_managed_catalog(),
        build_system=lambda _config: ExperimentSystem(
            provider=_EmptyInstrumentProvider()
        ),
        bootstrap_config=_config(),
    ) as runtime:
        client = TestClient(runtime.app())
        response = client.post(
            "/api/v1/runs",
            json=ManagedRunSubmission(
                submission_id="managed-1",
                registration_id="simple-scan",
                registration_version="1",
                request=RunRequest(id="managed-request"),
            ).model_dump(mode="json"),
        )

        assert response.status_code == 201
        run_id = RunAdmission.model_validate(response.json()).run_id
        deadline = time.monotonic() + 3
        while (
            _control_run(runtime, run_id).state != "terminal"
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        run = _control_run(runtime, run_id)
        assert run.state == "terminal"
        assert run.outcome is not None
        assert run.outcome.result == "succeeded"
        assert (
            client.get(f"/api/v1/runs/{run_id}").json()["manifest"]["lifecycle"]
            == "terminal"
        )
        assert client.get(f"/api/v1/runs/{run_id}/measurements").json() == {
            "items": [],
            "next_offset": None,
        }


def test_managed_worker_manifest_read_failure_releases_active_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with LocalDaemonRuntime(
        tmp_path,
        catalog=_managed_catalog(),
        build_system=lambda _config: ExperimentSystem(
            provider=_EmptyInstrumentProvider()
        ),
        bootstrap_config=_config(),
    ) as runtime:
        managed, admission = _managed_components(runtime)
        managed.close()
        admitted = admission.submit_run(
            ManagedRunSubmission(
                submission_id="managed-retry",
                registration_id="simple-scan",
                registration_version="1",
                request=RunRequest(id="managed-request"),
            )
        )
        planned = admitted.managed_plan
        assert planned is not None
        run_id = admitted.receipt.run_id
        managed._managed_plans[run_id] = planned
        managed._managed_active.add(run_id)

        def fail_read(
            _repository: SQLiteRunRepository,
            _run_id: str,
        ) -> RunManifest:
            raise RuntimeError("manifest read failure")

        with monkeypatch.context() as patch:
            patch.setattr(SQLiteRunRepository, "read_manifest", fail_read)
            managed._execute_managed(run_id, planned)

        assert run_id not in managed._managed_active
        assert managed._managed_plans[run_id] is planned
        assert _control_run(runtime, run_id).state == "accepted"
        assert "managed worker stopped unexpectedly" in caplog.text


def test_supervisor_forgets_terminal_plan_after_worker_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with LocalDaemonRuntime(
        tmp_path,
        catalog=_managed_catalog(),
        build_system=lambda _config: ExperimentSystem(
            provider=_EmptyInstrumentProvider()
        ),
        bootstrap_config=_config(),
    ) as runtime:
        managed, admission = _managed_components(runtime)
        managed.close()
        admitted = admission.submit_run(
            ManagedRunSubmission(
                submission_id="managed-cleanup",
                registration_id="simple-scan",
                registration_version="1",
                request=RunRequest(id="managed-request"),
            )
        )
        planned = admitted.managed_plan
        assert planned is not None
        run_id = admitted.receipt.run_id
        managed._managed_plans[run_id] = planned
        managed._managed_active.add(run_id)
        read_attempts = 0

        def fail_post_run_read(
            _control: SQLiteControlPlane,
            _run_id: str,
        ) -> Never:
            nonlocal read_attempts
            read_attempts += 1
            raise RuntimeError("post-run read failure")

        with monkeypatch.context() as patch:
            patch.setattr(SQLiteControlPlane, "get_run", fail_post_run_read)
            managed._execute_managed(run_id, planned)

        assert read_attempts == 1
        assert _control_run(runtime, run_id).state == "terminal"
        manifest = _manifest(runtime, run_id)
        assert manifest.lifecycle == "terminal"
        assert run_id not in managed._managed_active
        assert run_id not in managed._managed_plans
        assert "managed worker stopped unexpectedly" in caplog.text


def test_unbuildable_managed_run_is_failed_durably_on_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    descriptor = RegisteredExperimentDescriptor(
        id="simple-scan",
        version="1",
        experiment_kind="managed",
    )
    catalog = RegisteredExperimentCatalog(
        (
            RegisteredExperiment(
                id="simple-scan",
                version="1",
                descriptor=descriptor,
                factory=lambda _request: _managed_experiment(),
            ),
        )
    )
    with LocalDaemonRuntime(
        tmp_path,
        catalog=catalog,
        build_system=lambda _config: ExperimentSystem(
            provider=_EmptyInstrumentProvider()
        ),
        bootstrap_config=_config(),
    ) as runtime:

        def skip_schedule(
            _supervisor: daemon_services.ManagedRunSupervisor,
            _run_id: str,
            _managed: object,
        ) -> None:
            return

        with monkeypatch.context() as patch:
            patch.setattr(
                daemon_services.ManagedRunSupervisor,
                "schedule",
                skip_schedule,
            )
            admission = runtime.application.submit_run(
                ManagedRunSubmission(
                    submission_id="managed-restart",
                    registration_id="simple-scan",
                    registration_version="1",
                    request=RunRequest(id="managed-request"),
                )
            )
        assert _control_run(runtime, admission.run_id).state == "accepted"

    def unavailable_factory(_request: RunRequest) -> Never:
        raise RuntimeError("definition is unavailable")

    broken_catalog = RegisteredExperimentCatalog(
        (
            RegisteredExperiment(
                id="simple-scan",
                version="1",
                descriptor=descriptor,
                factory=unavailable_factory,
            ),
        )
    )
    with LocalDaemonRuntime(
        tmp_path,
        catalog=broken_catalog,
        build_system=lambda _config: ExperimentSystem(
            provider=_EmptyInstrumentProvider()
        ),
    ) as reopened:
        control = _control_run(reopened, admission.run_id)

        assert control.state == "terminal"
        assert control.outcome is not None
        assert control.outcome.problems[0].code == "daemon.managed_plan_unavailable"
        assert _manifest(reopened, admission.run_id).lifecycle == "terminal"


def test_restarted_managed_run_builds_from_its_admitted_config(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accepted_config = _config().model_copy(update={"id": "accepted-config"})
    later_config = accepted_config.model_copy(update={"id": "later-config"})
    catalog = RegisteredExperimentCatalog(
        (
            RegisteredExperiment(
                id="simple-scan",
                version="1",
                descriptor=RegisteredExperimentDescriptor(
                    id="simple-scan",
                    version="1",
                    experiment_kind="managed",
                ),
                factory=lambda _request: _managed_experiment(),
            ),
        )
    )
    with LocalDaemonRuntime(
        tmp_path,
        catalog=catalog,
        build_system=lambda _config: ExperimentSystem(
            provider=_EmptyInstrumentProvider()
        ),
        bootstrap_config=accepted_config,
    ) as runtime:

        def skip_schedule(
            _supervisor: daemon_services.ManagedRunSupervisor,
            _run_id: str,
            _planned: object,
        ) -> None:
            return

        with monkeypatch.context() as patch:
            patch.setattr(
                daemon_services.ManagedRunSupervisor,
                "schedule",
                skip_schedule,
            )
            admission = runtime.application.submit_run(
                ManagedRunSubmission(
                    submission_id="managed-config-restart",
                    registration_id="simple-scan",
                    registration_version="1",
                    request=RunRequest(id="managed-request"),
                )
            )
        runtime.application.config.set_direct_config_default(
            DirectConfigDefaultCommand(
                config=later_config,
                entry_id="later-config",
                registered_by="operator",
                operator="operator",
                expected_generation=1,
            )
        )

    built_from: list[ConfigProfileSnapshot] = []

    def build_system(config: ConfigProfileSnapshot) -> ExperimentSystem:
        built_from.append(config)
        return ExperimentSystem(provider=_EmptyInstrumentProvider())

    with LocalDaemonRuntime(
        tmp_path,
        catalog=catalog,
        build_system=build_system,
    ) as reopened:
        deadline = time.monotonic() + 3
        while (
            _control_run(reopened, admission.run_id).state != "terminal"
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        assert _control_run(reopened, admission.run_id).state == "terminal"
        assert built_from == [accepted_config]
        assert (
            reopened.application.config.get_active_config().active_state.active_entry_id
            == "later-config"
        )


def test_delegated_effect_is_fenced_and_terminal_updates_control(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        client = TestClient(runtime.app())
        admission_response = client.post(
            "/api/v1/runs",
            json=_submission().model_dump(mode="json"),
        )
        run_id = RunAdmission.model_validate(admission_response.json()).run_id
        accepted = _manifest(runtime, run_id)
        lease_response = client.post(
            f"/api/v1/runs/{run_id}/executor/start",
            json=ExecutorStartRequest(
                run_id=run_id,
                executor_id="notebook-1",
                manifest=accepted.model_copy(update={"lifecycle": "running"}),
            ).model_dump(mode="json"),
        )
        lease = ExecutorLease.model_validate(lease_response.json())
        measurement = MeasurementRecord(
            run_id=run_id,
            logical_point_id="point-0",
            point_index=0,
            coordinates={},
            observables={"signal": Quantity(value=1.25, unit="ratio")},
        )
        measurement_append = MeasurementDatasetAppend(
            run_id=run_id,
            dataset_id="raw-measurements",
            recording_contract_fingerprint="test.recording.v1",
            start_index=0,
            records=(measurement,),
        )
        measurement_response = client.post(
            f"/api/v1/runs/{run_id}/measurements/append",
            json=MeasurementAppendCommand(
                command_id=measurement_append.operation_id,
                run_id=run_id,
                lease_id=lease.lease_id,
                generation=lease.generation,
                append=measurement_append,
            ).model_dump(mode="json"),
        )
        detail = client.get(f"/api/v1/runs/{run_id}")
        measurements = client.get(
            f"/api/v1/runs/{run_id}/measurements",
            params={"limit": 100},
        )
        transition = ExecutionTransition(
            run_id=run_id,
            operation_id="compute-1",
            stage="compute",
            effect="pure",
            state="completed",
        )
        batch = ExecutionTransitionBatch(
            batch_id="batch-1",
            run_id=run_id,
            lease_id=lease.lease_id,
            generation=lease.generation,
            transitions=(transition,),
        )

        committed = client.post(
            f"/api/v1/runs/{run_id}/transitions",
            json=batch.model_dump(mode="json"),
        )
        retry = client.post(
            f"/api/v1/runs/{run_id}/transitions",
            json=batch.model_dump(mode="json"),
        )
        stale = client.post(
            f"/api/v1/runs/{run_id}/transitions",
            json=batch.model_copy(
                update={
                    "batch_id": "batch-stale",
                    "generation": lease.generation + 1,
                }
            ).model_dump(mode="json"),
        )

        assert measurement_response.status_code == 200
        assert detail.json()["manifest"]["lifecycle"] == "running"
        assert detail.json()["resources"][0]["status"] == "active"
        assert measurements.json()["items"][0]["point_index"] == 0
        assert committed.status_code == 200
        assert committed.json()["committed"][0]["sequence"] == 0
        assert retry.json() == committed.json()
        assert stale.status_code == 409
        assert (
            len(
                runtime.application.executor.recover_execution(
                    run_id,
                    request=ExecutionRecoveryRequest(
                        run_id=run_id,
                        lease_id=lease.lease_id,
                        generation=lease.generation,
                    ),
                ).transitions
            )
            == 1
        )
        assert (
            len(
                [
                    event
                    for event in _events(runtime, run_id=run_id).items
                    if event.kind == "execution_transition_committed"
                ]
            )
            == 1
        )

        outcome = RunOutcome(
            run_id=run_id,
            result="succeeded",
            certainty="known",
            termination_reason="completed",
            finished_at=datetime.now(tz=UTC),
        )
        terminal = accepted.model_copy(
            update={
                "lifecycle": "terminal",
                "outcome": outcome,
            }
        )
        completed = client.post(
            f"/api/v1/runs/{run_id}/terminal",
            json=TerminalRunCommitCommand(
                command_id=f"terminal:{run_id}",
                run_id=run_id,
                lease_id=lease.lease_id,
                generation=lease.generation,
                manifest=terminal,
            ).model_dump(mode="json"),
        )

        assert completed.status_code == 200
        assert completed.json()["manifest"]["lifecycle"] == "terminal"
        control_run = _control_run(runtime, run_id)
        assert control_run.state == "terminal"
        assert control_run.outcome == outcome
        assert _manifest(runtime, run_id) == terminal
        assert _resource_leases(tmp_path) == ()
        terminal_detail = client.get(f"/api/v1/runs/{run_id}").json()
        assert terminal_detail["resources"][0]["status"] == "released"


def test_delegated_runtime_event_is_fenced_and_durable(tmp_path: Path) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        client = TestClient(runtime.app())
        admission_response = client.post(
            "/api/v1/runs",
            json=_submission().model_dump(mode="json"),
        )
        run_id = RunAdmission.model_validate(admission_response.json()).run_id
        accepted = _manifest(runtime, run_id)
        lease_response = client.post(
            f"/api/v1/runs/{run_id}/executor/start",
            json=ExecutorStartRequest(
                run_id=run_id,
                executor_id="notebook-1",
                manifest=accepted.model_copy(update={"lifecycle": "running"}),
            ).model_dump(mode="json"),
        )
        lease = ExecutorLease.model_validate(lease_response.json())
        observed_at = datetime(2026, 7, 23, 9, 0, 2, tzinfo=UTC)
        occurred_at = datetime(2026, 7, 23, 9, 0, 1, tzinfo=UTC)
        command = RuntimeEventPublishCommand(
            run_id=run_id,
            lease_id=lease.lease_id,
            generation=lease.generation,
            event=RuntimeTransitionEventPayload(
                run_id=run_id,
                experiment_id="scratch",
                observed_at=observed_at,
                occurred_at=occurred_at,
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

        published = client.post(
            f"/api/v1/runs/{run_id}/runtime-events",
            json=command.model_dump(mode="json"),
        )
        stale = client.post(
            f"/api/v1/runs/{run_id}/runtime-events",
            json=command.model_copy(
                update={"generation": lease.generation + 1}
            ).model_dump(mode="json"),
        )

        assert published.status_code == 200
        assert published.json()["kind"] == "transition"
        assert stale.status_code == 409
        events = tuple(
            event
            for event in _events(runtime, run_id=run_id).items
            if event.kind == "runtime_transition"
        )
        assert len(events) == 1
        assert events[0].occurred_at == observed_at
        assert events[0].payload == {
            "run_id": run_id,
            "experiment_id": "scratch",
            "observed_at": "2026-07-23T09:00:02Z",
            "occurred_at": "2026-07-23T09:00:01Z",
            "operation_id": "point-1",
            "stage": "point",
            "effect": "acquisition",
            "state": "completed",
            "progress": {
                "completed_points": 1,
                "total_points": 2,
            },
            "sequence": None,
            "point_index": 0,
            "point_indices": [0],
            "instrument_id": "scope-1",
            "metrics": {"measurement_count": 1},
            "kind": "transition",
        }


def test_effect_and_terminal_publication_roll_back_with_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        submission = _submission()
        admission = runtime.application.submit_run(submission)
        accepted = _manifest(runtime, admission.run_id)
        lease = runtime.application.executor.start_executor(
            admission.run_id,
            ExecutorStartRequest(
                run_id=admission.run_id,
                executor_id=submission.executor_id,
                manifest=accepted.model_copy(update={"lifecycle": "running"}),
            ),
        )
        measurement = MeasurementRecord(
            run_id=admission.run_id,
            logical_point_id="point-0",
            point_index=0,
            coordinates={},
            observables={"signal": Quantity(value=1.25, unit="ratio")},
        )
        append = MeasurementDatasetAppend(
            run_id=admission.run_id,
            dataset_id="raw-measurements",
            recording_contract_fingerprint="test.recording.v1",
            start_index=0,
            records=(measurement,),
        )

        with monkeypatch.context() as patch:

            def fail_event(*_args: object, **_kwargs: object) -> Never:
                raise RuntimeError("event publication failed")

            patch.setattr(
                SQLiteControlPlane,
                "append_event_in_transaction",
                fail_event,
            )
            with pytest.raises(RuntimeError, match="event publication failed"):
                runtime.application.executor.append_measurements(
                    admission.run_id,
                    MeasurementAppendCommand(
                        command_id=append.operation_id,
                        run_id=admission.run_id,
                        lease_id=lease.lease_id,
                        generation=lease.generation,
                        append=append,
                    ),
                )

        assert (
            runtime.application.runs.measurements(
                admission.run_id,
                limit=100,
                offset=0,
            ).items
            == ()
        )

        outcome = RunOutcome(
            run_id=admission.run_id,
            result="succeeded",
            certainty="known",
            termination_reason="completed",
        )
        terminal = accepted.model_copy(
            update={"lifecycle": "terminal", "outcome": outcome}
        )
        with monkeypatch.context() as patch:

            def fail_transition(*_args: object, **_kwargs: object) -> Never:
                raise RuntimeError("control transition failed")

            patch.setattr(
                SQLiteControlPlane,
                "transition_run_in_transaction",
                fail_transition,
            )
            with pytest.raises(RuntimeError, match="control transition failed"):
                runtime.application.executor.commit_terminal(
                    admission.run_id,
                    TerminalRunCommitCommand(
                        command_id=f"terminal:{admission.run_id}",
                        run_id=admission.run_id,
                        lease_id=lease.lease_id,
                        generation=lease.generation,
                        manifest=terminal,
                    ),
                )

        assert _manifest(runtime, admission.run_id).lifecycle == "running"
        assert _control_run(runtime, admission.run_id).state == "running"


def test_restart_quarantines_executor_and_operator_can_requeue_or_abort(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        submission = _submission("operator-recovery")
        admission = runtime.application.submit_run(submission)
        accepted = _manifest(runtime, admission.run_id)
        runtime.application.executor.start_executor(
            admission.run_id,
            ExecutorStartRequest(
                run_id=admission.run_id,
                executor_id=submission.executor_id,
                manifest=accepted.model_copy(update={"lifecycle": "running"}),
            ),
        )
        run_id = admission.run_id

    with LocalDaemonRuntime(tmp_path) as reopened:
        attention = _control_run(reopened, run_id)
        assert attention.state == "attention_required"
        assert attention.attention_reason == "daemon_restarted"
        assert _resource_leases(tmp_path)[0].status == "quarantined"

        requeued = reopened.application.resolve_attention(
            run_id,
            AttentionResolutionCommand(run_id=run_id, action="requeue"),
        )
        assert requeued.state == "accepted"
        assert requeued.released_resource_count == 1
        accepted = _manifest(reopened, run_id)
        assert accepted.lifecycle == "accepted"
        reopened.application.executor.start_executor(
            run_id,
            ExecutorStartRequest(
                run_id=run_id,
                executor_id=submission.executor_id,
                manifest=accepted.model_copy(update={"lifecycle": "running"}),
            ),
        )

    with LocalDaemonRuntime(tmp_path) as reopened:
        aborted = reopened.application.resolve_attention(
            run_id,
            AttentionResolutionCommand(run_id=run_id, action="abort"),
        )

        assert aborted.state == "terminal"
        assert aborted.released_resource_count == 1
        control = _control_run(reopened, run_id)
        assert control.outcome is not None
        assert control.outcome.problems[0].code == "daemon.operator_aborted"
        assert _manifest(reopened, run_id).lifecycle == "terminal"
        assert _resource_leases(tmp_path) == ()
