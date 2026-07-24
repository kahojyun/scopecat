from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Never

import pytest
from fastapi.testclient import TestClient
from scopecat.authoring import ExperimentBody, experiment, template
from scopecat.config.changes import parameter_change_proposal_from_updates
from scopecat.config.parameters import replace_scalar_parameter
from scopecat.config.profiles import load_config_profile
from scopecat.config.registry import load_active_config_registry_state
from scopecat.config.resolution import register_and_activate_config_profile
from scopecat.daemon.catalog import (
    RegisteredExperiment,
    RegisteredExperimentCatalog,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigRegistryView,
    ParameterProposalListView,
    RunConfigView,
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
    ConfigEntryActivationCommand,
    ConfigImportReceipt,
    ConfigRollbackCommand,
    DelegatedPlanSummary,
    DelegatedRunSubmission,
    DirectConfigImportCommand,
    ExecutionRecoveryRequest,
    ExecutionTransitionBatch,
    ExecutorLease,
    ExecutorStartRequest,
    ManagedRunSubmission,
    MeasurementAppendCommand,
    ParameterProposalReviewCommand,
    ParameterProposalReviewReceipt,
    RegisteredExperimentDescriptor,
    ResourceClaimDescriptor,
    RunAdmission,
    RunAttachmentCommand,
    TerminalRunCommitCommand,
)
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import MeasurementDatasetAppend
from scopecat.records.parameter import Quantity
from scopecat.records.run import RunOutcome
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments import (
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
)

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


def test_runtime_bootstraps_project_control_plane_and_health(tmp_path: Path) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        response = TestClient(runtime.app()).get("/api/v1/health")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert response.json()["project_id"].startswith("local:")
        assert response.json()["project_name"] == tmp_path.name
        assert response.json()["project_root"] == str(tmp_path)
        assert runtime.control.path == runtime.runs.database
        assert runtime.control.path == runtime.config_registry.database
        assert runtime.control.path == tmp_path / ".scopecat" / "control.sqlite3"
        assert runtime.runs.objects.root == tmp_path / ".scopecat" / "objects"


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
        assert reopened.backend.health().status == "ok"


def test_bootstrap_config_is_active_and_idempotent_across_restarts(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        first = load_active_config_registry_state(
            unit_of_work=runtime.config_registry.unit_of_work
        )

    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as reopened:
        second = load_active_config_registry_state(
            unit_of_work=reopened.config_registry.unit_of_work
        )

    assert first.active_entry_id.startswith("daemon-")
    assert second == first


def test_bootstrap_config_does_not_replace_later_activation(
    tmp_path: Path,
) -> None:
    bootstrap = _config()
    selected = bootstrap.model_copy(update={"id": "operator-selected"})
    with LocalDaemonRuntime(tmp_path, bootstrap_config=bootstrap) as runtime:
        activation = register_and_activate_config_profile(
            config=selected,
            services=runtime.backend.services,
            entry_id="operator-selected",
            registered_by="operator",
            operator="operator",
        )

    with LocalDaemonRuntime(tmp_path, bootstrap_config=bootstrap) as reopened:
        state = load_active_config_registry_state(
            unit_of_work=reopened.config_registry.unit_of_work
        )

    assert state.active_entry_id == "operator-selected"
    assert state == activation.active_state


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
        events = runtime.control.list_events().items

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
        active = reopened.backend.get_active_config()
        events = reopened.control.list_events().items

        assert active.entry.id == "baseline"
        assert active.config == baseline
        assert events[-1].kind == "config_rolled_back"


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
        assert runtime.runs.read_manifest(run_id).lifecycle == "accepted"
        assert [
            event.kind
            for event in runtime.control.list_events(run_id=run_id).items
            if event.kind == "run_admitted"
        ] == ["run_admitted"]

    with LocalDaemonRuntime(tmp_path) as reopened:
        persisted = reopened.backend.submit_run(submission)
        assert persisted.run_id == run_id


def test_post_run_analysis_review_and_candidate_activation_closed_loop(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        client = TestClient(runtime.app())
        admission = runtime.backend.submit_run(_submission("post-run-loop"))
        proposal = parameter_change_proposal_from_updates(
            source_run_id=admission.run_id,
            source_config=_config(),
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
        )
        analysis_command = AnalysisSaveCommand(
            run_id=admission.run_id,
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
        review_command = ParameterProposalReviewCommand(
            run_id=admission.run_id,
            proposal_id=proposal.id,
            decision="approved",
            reviewer="operator",
            note="fit evidence accepted",
        )
        reviewed = client.post(
            f"/api/v1/runs/{admission.run_id}/parameter-proposals/{proposal.id}/review",
            json=review_command.model_dump(mode="json"),
        )
        reviewed_proposals = ParameterProposalListView.model_validate(
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
        decision = ParameterProposalReviewReceipt.model_validate(reviewed.json())
        activation = CandidateConfigActivationReceipt.model_validate(activated.json())
        events = runtime.control.list_events(run_id=admission.run_id).items

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
        assert reviewed_proposals.items[0].decisions == (decision.decision,)
        assert activation.entry.id == "candidate-fit"
        assert activation.active_state.generation == 2
        assert [
            event.kind
            for event in events
            if event.kind
            in {
                "analysis_saved",
                "parameter_proposal_reviewed",
                "config_activated",
            }
        ] == [
            "analysis_saved",
            "parameter_proposal_reviewed",
            "config_activated",
        ]


def test_executor_start_is_atomic_idempotent_and_quiet_when_resources_busy(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        first = runtime.backend.submit_run(_submission("executor-first"))
        first_manifest = runtime.runs.read_manifest(first.run_id)
        request = ExecutorStartRequest(
            run_id=first.run_id,
            executor_id="notebook-1",
            manifest=first_manifest.model_copy(update={"lifecycle": "running"}),
        )

        lease = runtime.backend.start_executor(first.run_id, request)
        retry = runtime.backend.start_executor(first.run_id, request)

        assert retry == lease
        assert (
            len(
                [
                    event
                    for event in runtime.control.list_events(run_id=first.run_id).items
                    if event.kind == "executor_lease_granted"
                ]
            )
            == 1
        )

        waiting = runtime.backend.submit_run(_submission("executor-waiting"))
        waiting_manifest = runtime.runs.read_manifest(waiting.run_id)
        with pytest.raises(BackendConflict, match="resources are busy"):
            runtime.backend.start_executor(
                waiting.run_id,
                ExecutorStartRequest(
                    run_id=waiting.run_id,
                    executor_id="notebook-2",
                    manifest=waiting_manifest.model_copy(
                        update={"lifecycle": "running"}
                    ),
                ),
            )

        assert runtime.control.get_run(waiting.run_id).state == "accepted"
        assert runtime.runs.read_manifest(waiting.run_id).lifecycle == "accepted"
        assert [
            event.kind
            for event in runtime.control.list_events(run_id=waiting.run_id).items
        ] == ["run_admitted"]


def test_managed_submission_executes_registered_experiment(tmp_path: Path) -> None:
    catalog = RegisteredExperimentCatalog(
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
    with LocalDaemonRuntime(
        tmp_path,
        catalog=catalog,
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
            runtime.control.get_run(run_id).state != "terminal"
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        run = runtime.control.get_run(run_id)
        assert run.state == "terminal"
        assert run.outcome is not None
        assert run.outcome.result == "succeeded"
        assert (
            client.get(f"/api/v1/runs/{run_id}").json()["manifest"]["lifecycle"]
            == "terminal"
        )
        assert client.get(f"/api/v1/runs/{run_id}/measurements").json() == {
            "schema_version": "scopecat.measurement_page.v1",
            "items": [],
            "next_offset": None,
        }


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

        def skip_schedule(_run_id: str, _managed: object) -> None:
            return

        monkeypatch.setattr(
            runtime.backend,
            "_schedule_managed",
            skip_schedule,
        )
        admission = runtime.backend.submit_run(
            ManagedRunSubmission(
                submission_id="managed-restart",
                registration_id="simple-scan",
                registration_version="1",
                request=RunRequest(id="managed-request"),
            )
        )
        assert runtime.control.get_run(admission.run_id).state == "accepted"

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
        control = reopened.control.get_run(admission.run_id)

        assert control.state == "terminal"
        assert control.outcome is not None
        assert control.outcome.problems[0].code == "daemon.managed_plan_unavailable"
        assert reopened.runs.read_manifest(admission.run_id).lifecycle == "terminal"


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

        def skip_schedule(_run_id: str, _planned: object) -> None:
            return

        monkeypatch.setattr(runtime.backend, "_schedule_managed", skip_schedule)
        admission = runtime.backend.submit_run(
            ManagedRunSubmission(
                submission_id="managed-config-restart",
                registration_id="simple-scan",
                registration_version="1",
                request=RunRequest(id="managed-request"),
            )
        )
        register_and_activate_config_profile(
            config=later_config,
            services=runtime.backend.services,
            entry_id="later-config",
            registered_by="operator",
            operator="operator",
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
            reopened.control.get_run(admission.run_id).state != "terminal"
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

        assert reopened.control.get_run(admission.run_id).state == "terminal"
        assert built_from == [accepted_config]
        assert (
            load_active_config_registry_state(
                unit_of_work=reopened.config_registry.unit_of_work
            ).active_entry_id
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
        accepted = runtime.runs.read_manifest(run_id)
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
                runtime.backend.recover_execution(
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
                    for event in runtime.control.list_events(run_id=run_id).items
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
        control_run = runtime.control.get_run(run_id)
        assert control_run.state == "terminal"
        assert control_run.outcome == outcome
        assert runtime.runs.read_manifest(run_id) == terminal
        assert runtime.control.list_resource_leases() == ()
        terminal_detail = client.get(f"/api/v1/runs/{run_id}").json()
        assert terminal_detail["resources"][0]["status"] == "released"


def test_effect_and_terminal_publication_roll_back_with_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        submission = _submission()
        admission = runtime.backend.submit_run(submission)
        accepted = runtime.runs.read_manifest(admission.run_id)
        lease = runtime.backend.start_executor(
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
                runtime.control,
                "append_event_in_transaction",
                fail_event,
            )
            with pytest.raises(RuntimeError, match="event publication failed"):
                runtime.backend.append_measurements(
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
            runtime.backend.measurements(
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
                runtime.control,
                "transition_run_in_transaction",
                fail_transition,
            )
            with pytest.raises(RuntimeError, match="control transition failed"):
                runtime.backend.commit_terminal(
                    admission.run_id,
                    TerminalRunCommitCommand(
                        command_id=f"terminal:{admission.run_id}",
                        run_id=admission.run_id,
                        lease_id=lease.lease_id,
                        generation=lease.generation,
                        manifest=terminal,
                    ),
                )

        assert runtime.runs.read_manifest(admission.run_id).lifecycle == "running"
        assert runtime.control.get_run(admission.run_id).state == "running"


def test_restart_quarantines_executor_and_operator_can_requeue_or_abort(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        submission = _submission("operator-recovery")
        admission = runtime.backend.submit_run(submission)
        accepted = runtime.runs.read_manifest(admission.run_id)
        runtime.backend.start_executor(
            admission.run_id,
            ExecutorStartRequest(
                run_id=admission.run_id,
                executor_id=submission.executor_id,
                manifest=accepted.model_copy(update={"lifecycle": "running"}),
            ),
        )
        run_id = admission.run_id

    with LocalDaemonRuntime(tmp_path) as reopened:
        attention = reopened.control.get_run(run_id)
        assert attention.state == "attention_required"
        assert attention.attention_reason == "daemon_restarted"
        assert reopened.control.list_resource_leases()[0].status == "quarantined"

        requeued = reopened.backend.resolve_attention(
            run_id,
            AttentionResolutionCommand(run_id=run_id, action="requeue"),
        )
        assert requeued.state == "accepted"
        assert requeued.released_resource_count == 1
        accepted = reopened.runs.read_manifest(run_id)
        assert accepted.lifecycle == "accepted"
        reopened.backend.start_executor(
            run_id,
            ExecutorStartRequest(
                run_id=run_id,
                executor_id=submission.executor_id,
                manifest=accepted.model_copy(update={"lifecycle": "running"}),
            ),
        )

    with LocalDaemonRuntime(tmp_path) as reopened:
        aborted = reopened.backend.resolve_attention(
            run_id,
            AttentionResolutionCommand(run_id=run_id, action="abort"),
        )

        assert aborted.state == "terminal"
        assert aborted.released_resource_count == 1
        control = reopened.control.get_run(run_id)
        assert control.outcome is not None
        assert control.outcome.problems[0].code == "daemon.operator_aborted"
        assert reopened.runs.read_manifest(run_id).lifecycle == "terminal"
        assert reopened.control.list_resource_leases() == ()
