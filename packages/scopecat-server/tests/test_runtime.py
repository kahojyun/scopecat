# pyright: reportUnknownArgumentType=false

from __future__ import annotations

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event, Thread
from typing import Literal, Never, cast

import pyarrow as pa
import pytest
from fastapi.testclient import TestClient
from scopecat.analysis.datasets import DerivedDataset
from scopecat.application import LabApplication
from scopecat.config.changes import parameter_change_proposal_from_updates
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.inventory import InstrumentInventoryRekey
from scopecat.config.parameters import ReplaceParameter, replace_scalar_parameter
from scopecat.config.registry import ActiveConfigRegistrySnapshot
from scopecat.control.models import (
    DurableEvent,
    DurableEventInput,
    EventPage,
    ResourceClaim,
    ResourceKey,
    RunDomainTargetRequirement,
    RunPlanSummary,
    RunResourceRequirement,
)
from scopecat.daemon.views import (
    ActiveConfigView,
    ConfigActivationHistoryView,
    ConfigDraftPreview,
    ConfigRegistryView,
    MeasurementArrowColumn,
    MeasurementArrowQuery,
    ParameterProposalListView,
    RunConfigView,
    RunControlView,
    RunDatasetBytesView,
    RunDetail,
)
from scopecat.daemon.wire import (
    AnalysisArtifactOutputPayload,
    AnalysisDatasetOutputPayload,
    AnalysisFigureOutputPayload,
    AnalysisParameterProposalOutputPayload,
    AnalysisSaveCommand,
    AnalysisSaveReceipt,
    AnalysisTableOutputPayload,
    CandidateConfigRevisionSource,
    ConfigActivationReceipt,
    ConfigDraftCommand,
    ConfigEntryActivationCommand,
    ConfigPublishCommand,
    ConfigPublishReceipt,
    ConfigUndoCommand,
    DirectConfigRevisionSource,
    ExecutionTransitionAppend,
    ExecutionTransitionClaim,
    ExecutorHeartbeat,
    ExecutorLease,
    ExecutorStartRequest,
    InstrumentInventoryMigrationCommand,
    InstrumentInventoryMigrationReceipt,
    ManualConfigDraftRevisionSource,
    MeasurementAppendCommand,
    MeasurementHeaderCommand,
    RunAdmission,
    RunAttachmentCommand,
    RunCancellationReceipt,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.kernel.problems import ProblemPhase, problem
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.project_state import ProjectStateServices
from scopecat.records.analysis import (
    AnalysisDatasetViewSource,
    AnalysisField,
    AnalysisFigureProjection,
    AnalysisFigureViewSpec,
    AnalysisTableViewSpec,
)
from scopecat.records.config import (
    ConfigProfileSnapshot,
    TcpipSocketInstrumentConnection,
    config_content_hash,
)
from scopecat.records.execution_journal import ExecutionTransition
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementPointDomainAxis,
    MeasurementProductGridPointDomain,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementVariable,
)
from scopecat.records.measurement_recording import (
    MeasurementDatasetAppend,
    MeasurementDatasetHeader,
)
from scopecat.records.parameter import ScalarParameterValue
from scopecat.records.parameter_change import (
    ParameterChangeProposal,
)
from scopecat.records.run import ConfigRegistryRunConfigSource, RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.refs import dataset_content_ref, record_content_ref
from scopecat.sdk.domain.invocation import close_domain_invocation
from scopecat.sdk.domain.result_mapping import DomainResultMapping
from scopecat.sdk.domain.runtime import (
    DomainExecutionReceipt,
    plan_domain_execution,
)
from tests.testkit.runtime import list_test_runs

import scopecat_server.services as daemon_services
import scopecat_server.services.leases as lease_supervisor_services
from scopecat_server import BackendConflict, LocalDaemonRuntime
from scopecat_server.instruments.actors import InstrumentActorRetirement
from scopecat_server.storage.sqlite import (
    ControlPlaneConflict,
    SQLiteConfigRegistryStore,
    SQLiteControlPlane,
    SQLiteDatabase,
    SQLiteRunRepository,
)

_FIXTURE = (
    Path(__file__).parents[3]
    / "fixtures"
    / "core"
    / "simple_scan"
    / "config-snapshot.json"
)


def _config() -> ConfigProfileSnapshot:
    return load_config_snapshot_document(_FIXTURE)


def _direct_publish_command(
    *,
    entry_id: str,
    config: ConfigProfileSnapshot,
    actor: str,
    expected_generation: int = 0,
    note: str = "",
) -> ConfigPublishCommand:
    return ConfigPublishCommand(
        source=DirectConfigRevisionSource(config=config),
        entry_id=entry_id,
        actor=actor,
        expected_generation=expected_generation,
        note=note,
    )


def _run_detail(runtime: LocalDaemonRuntime, run_id: str) -> RunDetail:
    return runtime.application.runs.get_run(run_id)


def _control_run(runtime: LocalDaemonRuntime, run_id: str) -> RunControlView:
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


def _resource_claims(project_root: Path) -> tuple[ResourceClaim, ...]:
    control = SQLiteControlPlane(
        SQLiteDatabase(project_root / ".scopecat" / "control.sqlite3")
    )
    with control.read_transaction() as connection:
        return control.list_resource_claims_in_transaction(connection)


def _run_repository(project_root: Path) -> SQLiteRunRepository:
    state = project_root / ".scopecat"
    return SQLiteRunRepository(
        SQLiteDatabase(state / "control.sqlite3"), state / "objects"
    )


def _submission(
    submission_id: str = "submission-1",
) -> RunSubmission:
    return RunSubmission(
        submission_id=submission_id,
        config=_config(),
        request=RunRequest(experiment_id="scratch"),
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
            run_resource_requirements=(
                RunResourceRequirement(id="source-0", kind="instrument"),
            ),
        ),
    )


def _domain_only_config() -> ConfigProfileSnapshot:
    config = _config()
    [instrument] = config.instrument_registry.instruments
    configured = instrument.model_copy(update={"exclusivity_key": "rack-a/source"})
    registry = config.instrument_registry.model_copy(
        update={"instruments": [configured]}
    )
    target = config.domain_target
    assert target is not None
    return config.model_copy(
        update={
            "system": config.system.model_copy(
                update={
                    "instrument_registry": registry,
                    "domain_target": target.model_copy(
                        update={"instrument_ids": ["source-0"]}
                    ),
                }
            )
        }
    )


def _rekeyed_config(
    config: ConfigProfileSnapshot,
    *,
    exclusivity_key: str = "rack-a/source",
) -> ConfigProfileSnapshot:
    [instrument] = config.instrument_registry.instruments
    registry = config.instrument_registry.model_copy(
        update={
            "instruments": [
                instrument.model_copy(update={"exclusivity_key": exclusivity_key})
            ]
        }
    )
    return config.model_copy(
        update={
            "id": "inventory-v2",
            "system": config.system.model_copy(
                update={"instrument_registry": registry}
            ),
        }
    )


def _inventory_migration_command(
    config: ConfigProfileSnapshot,
    *,
    expected_generation: int = 1,
) -> InstrumentInventoryMigrationCommand:
    [target] = config.instrument_registry.instruments
    return InstrumentInventoryMigrationCommand(
        config=config,
        entry_id="inventory-v2",
        changes=(
            InstrumentInventoryRekey(
                instrument_id=target.id,
                from_exclusivity_key="source-0",
                to_exclusivity_key=target.exclusivity_key,
            ),
        ),
        actor="operator",
        expected_generation=expected_generation,
        note="moved to rack-a",
    )


def _domain_only_submission(
    config: ConfigProfileSnapshot,
    *,
    submission_id: str,
    requirements: tuple[RunResourceRequirement, ...],
) -> RunSubmission:
    target = config.domain_target
    assert target is not None
    return RunSubmission(
        submission_id=submission_id,
        config=config,
        request=RunRequest(experiment_id="domain-only"),
        plan=RunPlanSummary(
            experiment_id="domain-only",
            experiment_kind="domain-only",
            point_count=1,
            domain_target_requirement=RunDomainTargetRequirement(
                id=target.id,
                kind=target.kind,
                instrument_ids=tuple(target.instrument_ids),
            ),
            run_resource_requirements=requirements,
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


def _analysis_command(proposal: ParameterChangeProposal) -> AnalysisSaveCommand:
    return AnalysisSaveCommand(
        title="fit",
        analysis_key="fit",
        outputs=(
            AnalysisTableOutputPayload(
                kind="table",
                id="fit-parameters",
                title="fit parameters",
                content=AnalysisTableViewSpec(
                    source=AnalysisDatasetViewSource(output_id="fits"),
                    columns=("bias",),
                ),
            ),
            AnalysisDatasetOutputPayload(
                kind="dataset",
                id="fits",
                title="fit data",
                content=DerivedDataset.from_arrow(
                    pa.table({"bias": [1.0, 2.0], "signal": [3.0, 4.0]}),
                    fields={"bias": AnalysisField(role="coordinate")},
                ).to_payload(),
            ),
            AnalysisFigureOutputPayload(
                kind="figure",
                id="fit-curve",
                title="fit curve",
                content=AnalysisFigureViewSpec(
                    source=AnalysisDatasetViewSource(output_id="fits"),
                    projection=AnalysisFigureProjection(
                        kind="line",
                        x="bias",
                        y="signal",
                    ),
                ),
            ),
            AnalysisParameterProposalOutputPayload(
                kind="parameter_change_proposal",
                id=proposal.id,
                title=proposal.id,
                content=proposal,
            ),
            AnalysisArtifactOutputPayload(
                kind="artifact",
                id="fit-report",
                title="Fit report",
                content_base64="IyBGaXQgcmVwb3J0Cg==",
                filename="fit-report.md",
                media_type="text/markdown",
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
    if failure_point == "reconciliation":

        def fail_reconciliation(_supervisor: object) -> Never:
            raise RuntimeError("startup reconciliation failed")

        monkeypatch.setattr(
            daemon_services.OwnershipLeaseSupervisor,
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

        monkeypatch.setattr(lease_supervisor_services, "Thread", build_thread)

    with pytest.raises(RuntimeError, match=r"(reconciliation|thread) failed"):
        LocalDaemonRuntime(tmp_path)

    monkeypatch.undo()
    with LocalDaemonRuntime(tmp_path):
        pass


def test_lease_supervisor_health_recovers_after_one_failed_iteration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalDaemonRuntime(tmp_path) as runtime:
        instruments = runtime.application.instruments
        failed = Event()
        permit_success = Event()

        def fail_once_then_succeed() -> None:
            if not failed.is_set():
                failed.set()
                raise RuntimeError("temporary lease scan failure")
            assert permit_success.wait(timeout=1)

        monkeypatch.setattr(instruments, "expire_leases", fail_once_then_succeed)
        assert failed.wait(timeout=2)
        assert runtime.application.health().status == "degraded"

        permit_success.set()
        deadline = time.monotonic() + 2
        while (
            runtime.application.health().status != "ok" and time.monotonic() < deadline
        ):
            time.sleep(0.01)
        assert runtime.application.health().status == "ok"


def test_runtime_shutdown_unblocks_an_active_lease_supervisor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LocalDaemonRuntime(tmp_path)
    instruments = runtime.application.instruments
    supervision_started = Event()
    instrument_shutdown_started = Event()
    original_shutdown = instruments.shutdown

    def wait_for_instrument_shutdown() -> None:
        supervision_started.set()
        instrument_shutdown_started.wait()

    def shutdown_instruments() -> None:
        instrument_shutdown_started.set()
        original_shutdown()

    monkeypatch.setattr(instruments, "expire_leases", wait_for_instrument_shutdown)
    monkeypatch.setattr(instruments, "shutdown", shutdown_instruments)
    assert supervision_started.wait(timeout=2)

    close_error: BaseException | None = None

    def close_runtime() -> None:
        nonlocal close_error
        try:
            runtime.close()
        except BaseException as error:
            close_error = error

    closer = Thread(target=close_runtime)
    closer.start()
    closer.join(timeout=1)
    try:
        assert not closer.is_alive()
        assert close_error is None
    finally:
        instrument_shutdown_started.set()
        closer.join(timeout=2)


def test_runtime_shutdown_bounds_a_stuck_lease_supervisor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = LocalDaemonRuntime(
        tmp_path,
        instrument_shutdown_grace=timedelta(seconds=0.05),
    )
    instruments = runtime.application.instruments
    supervision_started = Event()
    release_supervision = Event()

    def block_supervision() -> None:
        supervision_started.set()
        release_supervision.wait()

    monkeypatch.setattr(instruments, "expire_leases", block_supervision)
    assert supervision_started.wait(timeout=2)

    close_error: BaseException | None = None

    def close_runtime() -> None:
        nonlocal close_error
        try:
            runtime.close()
        except BaseException as error:
            close_error = error

    closer = Thread(target=close_runtime)
    closer.start()
    closer.join(timeout=0.5)
    try:
        assert not closer.is_alive()
        assert isinstance(close_error, RuntimeError)
        assert str(close_error) == "ownership lease supervisor did not stop"
        with pytest.raises(RuntimeError, match="already has a running daemon"):
            LocalDaemonRuntime(tmp_path)
    finally:
        release_supervision.set()
        closer.join(timeout=2)
        runtime.close()

    with LocalDaemonRuntime(tmp_path):
        pass


def test_runtime_exclusively_owns_one_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory_calls = 0

    def load_factory(_spec: str, _project_root: Path) -> Never:
        nonlocal factory_calls
        factory_calls += 1
        raise AssertionError("factory must not run before project ownership")

    monkeypatch.setattr(
        "scopecat_server.runtime.load_application_factory",
        load_factory,
    )
    with (
        LocalDaemonRuntime(tmp_path),
        pytest.raises(RuntimeError, match="already has a running daemon"),
    ):
        LocalDaemonRuntime(tmp_path, application_spec="tests.application:create")

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

    with LocalDaemonRuntime(tmp_path, bootstrap_config=bootstrap_config) as runtime:
        first = runtime.application.config.get_active_config().activation
        first_events = _events(runtime).items

    with LocalDaemonRuntime(tmp_path, bootstrap_config=bootstrap_config) as reopened:
        second = reopened.application.config.get_active_config().activation
        second_events = _events(reopened).items

    assert first.entry_id.startswith("daemon-")
    assert second == first
    assert [event.kind for event in first_events] == [
        "config_saved",
        "config_activated",
    ]
    assert second_events == first_events
    assert bootstrap_calls == 1


def test_bootstrap_config_does_not_replace_later_activation(
    tmp_path: Path,
) -> None:
    bootstrap = _config()
    selected = bootstrap.model_copy(update={"id": "operator-selected"})

    with LocalDaemonRuntime(tmp_path, bootstrap_config=lambda: bootstrap) as runtime:
        activation = runtime.application.config.publish_config(
            _direct_publish_command(
                config=selected,
                entry_id="operator-selected",
                actor="operator",
                expected_generation=1,
            )
        )

    with LocalDaemonRuntime(tmp_path, bootstrap_config=lambda: bootstrap) as reopened:
        state = reopened.application.config.get_active_config().activation

    assert state.entry_id == "operator-selected"
    assert state == activation.activation


def test_explicit_runtime_bootstrap_overrides_application_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable_bootstrap() -> ConfigProfileSnapshot:
        raise AssertionError("explicit test config must take precedence")

    def application_factory(_root: Path) -> LabApplication:
        return LabApplication(bootstrap_config=unavailable_bootstrap)

    def load_factory(
        _spec: str,
        _project_root: Path,
    ) -> object:
        return application_factory

    monkeypatch.setattr(
        "scopecat_server.runtime.load_application_factory",
        load_factory,
    )
    explicit = _config().model_copy(update={"id": "explicit-test-bootstrap"})
    with LocalDaemonRuntime(
        tmp_path,
        application_spec="tests.application:create",
        bootstrap_config=explicit,
    ) as runtime:
        state = runtime.application.config.get_active_config().activation

    assert state.entry_content_hash == config_content_hash(explicit)


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
        baseline_publish = client.post(
            "/api/v1/config-registry/default",
            json=_direct_publish_command(
                entry_id="baseline",
                config=baseline,
                actor="notebook",
            ).model_dump(mode="json"),
        )
        updated_publish = client.post(
            "/api/v1/config-registry/default",
            json=_direct_publish_command(
                entry_id="updated",
                config=updated,
                actor="notebook",
                expected_generation=1,
            ).model_dump(mode="json"),
        )
        current_activation = client.post(
            "/api/v1/config-registry/active",
            json=ConfigEntryActivationCommand(
                entry_id="updated",
                actor="operator",
                expected_generation=2,
            ).model_dump(mode="json"),
        )
        stale_activation = client.post(
            "/api/v1/config-registry/active",
            json=ConfigEntryActivationCommand(
                entry_id="baseline",
                actor="stale-notebook",
                expected_generation=1,
            ).model_dump(mode="json"),
        )
        undo_response = client.post(
            "/api/v1/config-registry/undo",
            json=ConfigUndoCommand(
                actor="operator",
                expected_generation=2,
            ).model_dump(mode="json"),
        )

        registry = ConfigRegistryView.model_validate(
            client.get("/api/v1/config-registry").json()
        )
        activation_history = ConfigActivationHistoryView.model_validate(
            client.get("/api/v1/config-registry/activations").json()
        )
        active = ActiveConfigView.model_validate(
            client.get("/api/v1/config-registry/active").json()
        )
        events = _events(runtime).items

        assert empty == ConfigRegistryView()
        assert missing.status_code == 404
        assert baseline_publish.status_code == 200
        assert updated_publish.status_code == 200
        first_receipt = ConfigPublishReceipt.model_validate(baseline_publish.json())
        second_receipt = ConfigPublishReceipt.model_validate(updated_publish.json())
        assert first_receipt.entry.id == "baseline"
        assert first_receipt.activation.generation == 1
        assert second_receipt.activation.generation == 2
        assert (
            ConfigActivationReceipt.model_validate(current_activation.json()).activation
            == second_receipt.activation
        )
        assert stale_activation.status_code == 409
        undo = ConfigActivationReceipt.model_validate(undo_response.json())
        assert undo.activation.action == "undo"
        assert undo.activation.generation == 3
        assert undo.activation.entry_id == "baseline"
        assert [entry.id for entry in registry.entries] == ["baseline", "updated"]
        assert registry.activation is not None
        assert [record.action for record in activation_history.items] == [
            "activation",
            "activation",
            "undo",
        ]
        assert active.entry.id == "baseline"
        assert active.config == baseline
        assert [(event.kind, event.payload, event.run_id) for event in events] == [
            ("config_saved", {"entry_id": "baseline"}, None),
            (
                "config_activated",
                {"entry_id": "baseline", "generation": 1},
                None,
            ),
            ("config_saved", {"entry_id": "updated"}, None),
            (
                "config_activated",
                {"entry_id": "updated", "generation": 2},
                None,
            ),
            (
                "config_undone",
                {"entry_id": "baseline", "generation": 3},
                None,
            ),
        ]

    with LocalDaemonRuntime(tmp_path) as reopened:
        active = reopened.application.config.get_active_config()
        events = _events(reopened).items

        assert active.entry.id == "baseline"
        assert active.config == baseline
        assert events[-1].kind == "config_undone"


def test_inventory_migration_http_workflow_activates_only_when_drained(
    tmp_path: Path,
) -> None:
    baseline = _config()
    target = _rekeyed_config(baseline)
    command = _inventory_migration_command(target)
    with LocalDaemonRuntime(tmp_path, bootstrap_config=baseline) as runtime:
        client = TestClient(runtime.app())

        response = client.post(
            "/api/v1/config-registry/instrument-inventory-migrations",
            json=command.model_dump(mode="json"),
        )

        assert response.status_code == 200
        receipt = InstrumentInventoryMigrationReceipt.model_validate(response.json())
        assert receipt.entry.id == command.entry_id
        assert receipt.activation.action == "inventory_migration"
        assert receipt.activation.generation == 2
        assert receipt.changes == command.changes
        assert runtime.application.config.get_active_config().config == target
        assert [
            (event.kind, event.payload) for event in _events(runtime).items[-2:]
        ] == [
            ("config_saved", {"entry_id": command.entry_id}),
            (
                "instrument_inventory_migrated",
                {
                    "entry_id": command.entry_id,
                    "generation": 2,
                    "change_count": 1,
                },
            ),
        ]

        undo = client.post(
            "/api/v1/config-registry/undo",
            json=ConfigUndoCommand(
                actor="operator",
                expected_generation=2,
            ).model_dump(mode="json"),
        )
        assert undo.status_code == 409
        assert runtime.application.config.get_active_config().config == target


def test_inventory_migration_reports_queued_run_as_a_blocker(
    tmp_path: Path,
) -> None:
    baseline = _config()
    target = _rekeyed_config(baseline)
    with LocalDaemonRuntime(tmp_path, bootstrap_config=baseline) as runtime:
        queued = runtime.application.submit_run(_submission("queued-blocker"))
        client = TestClient(runtime.app())

        response = client.post(
            "/api/v1/config-registry/instrument-inventory-migrations",
            json=_inventory_migration_command(target).model_dump(mode="json"),
        )

        assert response.status_code == 409
        assert queued.run_id in response.json()["detail"]
        assert "queued" in response.json()["detail"]
        assert runtime.application.config.get_active_config().config == baseline
        assert "inventory-v2" not in [
            entry.id
            for entry in runtime.application.config.get_config_registry().entries
        ]
        assert "instrument_inventory_migrated" not in {
            event.kind for event in _events(runtime).items
        }


def test_inventory_migration_final_check_catches_post_preflight_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _config()
    target = _rekeyed_config(baseline)
    with LocalDaemonRuntime(tmp_path, bootstrap_config=baseline) as runtime:
        service = runtime.application.config
        require_drained = service._require_inventory_migration_drained
        queued_run_ids: list[str] = []

        def admit_after_preflight(exclusivity_keys: tuple[str, ...]) -> None:
            require_drained(exclusivity_keys)
            queued = runtime.application.submit_run(
                _submission("post-preflight-blocker")
            )
            queued_run_ids.append(queued.run_id)

        monkeypatch.setattr(
            service,
            "_require_inventory_migration_drained",
            admit_after_preflight,
        )

        with pytest.raises(BackendConflict) as caught:
            service.migrate_instrument_inventory(_inventory_migration_command(target))

        assert len(queued_run_ids) == 1
        assert queued_run_ids[0] in str(caught.value)
        assert (
            runtime.application.executor._control.get_run(queued_run_ids[0]).state
            == "queued"
        )
        assert service.get_active_config().config == baseline
        assert "inventory-v2" not in {
            entry.id for entry in service.get_config_registry().entries
        }
        assert "instrument_inventory_migrated" not in {
            event.kind for event in _events(runtime).items
        }


def test_inventory_migration_stale_generation_does_not_begin_retirement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _config()
    current = baseline.model_copy(update={"id": "generation-2"})
    target = _rekeyed_config(current)
    with LocalDaemonRuntime(tmp_path, bootstrap_config=baseline) as runtime:
        service = runtime.application.config
        service.publish_config(
            _direct_publish_command(
                entry_id=current.id,
                config=current,
                actor="operator",
                expected_generation=1,
            )
        )
        begin_calls = 0

        def unexpected_retirement(_keys: tuple[str, ...]) -> Never:
            nonlocal begin_calls
            begin_calls += 1
            pytest.fail("stale migration must not begin actor retirement")

        monkeypatch.setattr(
            service._actors,
            "begin_retirement",
            unexpected_retirement,
        )

        with pytest.raises(BackendConflict, match="active state changed"):
            service.migrate_instrument_inventory(
                _inventory_migration_command(target, expected_generation=1)
            )

        assert begin_calls == 0
        assert service.get_active_config().config == current
        assert "inventory-v2" not in {
            entry.id for entry in service.get_config_registry().entries
        }


def test_inventory_migration_serializes_competing_config_publish(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _config()
    target = _rekeyed_config(baseline)
    ordinary = baseline.model_copy(update={"id": "ordinary-v2"})
    with LocalDaemonRuntime(tmp_path, bootstrap_config=baseline) as runtime:
        service = runtime.application.config
        require_drained = service._require_inventory_migration_drained
        migration_paused = Event()
        release_migration = Event()
        publish_started = Event()
        publish_finished = Event()

        def pause_after_preflight(exclusivity_keys: tuple[str, ...]) -> None:
            require_drained(exclusivity_keys)
            migration_paused.set()
            assert release_migration.wait(timeout=2)

        def publish_competing_revision() -> ConfigPublishReceipt:
            publish_started.set()
            try:
                return service.publish_config(
                    _direct_publish_command(
                        entry_id=ordinary.id,
                        config=ordinary,
                        actor="operator",
                        expected_generation=1,
                    )
                )
            finally:
                publish_finished.set()

        monkeypatch.setattr(
            service,
            "_require_inventory_migration_drained",
            pause_after_preflight,
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            migration = pool.submit(
                service.migrate_instrument_inventory,
                _inventory_migration_command(target),
            )
            assert migration_paused.wait(timeout=2)
            publish = pool.submit(publish_competing_revision)
            assert publish_started.wait(timeout=2)
            try:
                assert not publish_finished.wait(timeout=0.1)
            finally:
                release_migration.set()

            migration_receipt = migration.result(timeout=2)
            with pytest.raises(BackendConflict, match="active state changed"):
                publish.result(timeout=2)

        assert migration_receipt.activation.action == "inventory_migration"
        assert service.get_active_config().config == target
        assert "ordinary-v2" not in {
            entry.id for entry in service.get_config_registry().entries
        }


def test_inventory_migration_release_before_commit_fences_old_session_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _config()
    target = _rekeyed_config(baseline)
    release_seen = Event()
    claim_started = Event()
    release_gate = InstrumentActorRetirement.release_gate

    def release_then_allow_claim(self: InstrumentActorRetirement) -> None:
        release_gate(self)
        if release_seen.is_set():
            return
        release_seen.set()
        assert claim_started.wait(timeout=2)

    with LocalDaemonRuntime(tmp_path, bootstrap_config=baseline) as runtime:
        control = runtime.application.executor._control
        active = runtime.application.config.get_active_config()

        def claim_from_old_snapshot() -> None:
            assert release_seen.wait(timeout=2)
            claim_started.set()
            control.open_instrument_session(
                operation_id="old-snapshot-open",
                actor="operator",
                config_entry_id=active.entry.id,
                config_content_hash=active.entry.content_hash,
                instrument_ids=("source-0",),
                exclusivity_keys=("source-0",),
                expected_config_generation=active.activation.generation,
                ttl=timedelta(seconds=30),
            )

        monkeypatch.setattr(
            InstrumentActorRetirement,
            "release_gate",
            release_then_allow_claim,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            claim = pool.submit(claim_from_old_snapshot)
            receipt = runtime.application.config.migrate_instrument_inventory(
                _inventory_migration_command(target)
            )
            with pytest.raises(
                ControlPlaneConflict,
                match="active configuration changed",
            ):
                claim.result(timeout=2)

        assert receipt.activation.action == "inventory_migration"
        assert control.list_instrument_sessions() == ()
        assert _resource_claims(tmp_path) == ()


def test_inventory_migration_rolls_back_and_releases_its_gate_when_event_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    baseline = _config()
    target = _rekeyed_config(baseline)
    command = _inventory_migration_command(target)
    append_event = SQLiteControlPlane.append_event_in_transaction

    def fail_migration_event(
        control: SQLiteControlPlane,
        connection: sqlite3.Connection,
        event: DurableEventInput,
    ) -> DurableEvent:
        if event.kind == "instrument_inventory_migrated":
            raise RuntimeError("migration event publication failed")
        return append_event(control, connection, event)

    with LocalDaemonRuntime(tmp_path, bootstrap_config=baseline) as runtime:
        with monkeypatch.context() as patch:
            patch.setattr(
                SQLiteControlPlane,
                "append_event_in_transaction",
                fail_migration_event,
            )
            with pytest.raises(
                RuntimeError,
                match="migration event publication failed",
            ):
                runtime.application.config.migrate_instrument_inventory(command)

        assert runtime.application.config.get_active_config().config == baseline
        assert [
            entry.id
            for entry in runtime.application.config.get_config_registry().entries
        ] == [runtime.application.config.get_active_config().entry.id]
        assert "instrument_inventory_migrated" not in {
            event.kind for event in _events(runtime).items
        }

        receipt = runtime.application.config.migrate_instrument_inventory(command)
        assert receipt.activation.action == "inventory_migration"
        assert runtime.application.config.get_active_config().config == target


def test_config_publish_rolls_back_registry_and_event_when_event_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = _direct_publish_command(
        entry_id="baseline",
        config=_config(),
        actor="notebook",
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
                runtime.application.config.publish_config(command)

        assert runtime.application.config.get_config_registry() == ConfigRegistryView()
        assert _events(runtime).items == ()

        receipt = runtime.application.config.publish_config(command)

        assert receipt.activation.generation == 1
        assert [
            entry.id
            for entry in runtime.application.config.get_config_registry().entries
        ] == ["baseline"]
        assert [event.kind for event in _events(runtime).items] == [
            "config_saved",
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
            base_generation=active.activation.generation,
            candidate_id="manual-tuning",
            updates=(
                ReplaceParameter(
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
            "/api/v1/config-registry/default",
            json=ConfigPublishCommand(
                source=ManualConfigDraftRevisionSource(
                    draft=draft,
                    expected_result_content_hash=preview.result_content_hash,
                ),
                entry_id="manual-tuning",
                actor="operator",
                expected_generation=active.activation.generation,
            ).model_dump(mode="json"),
        )
        default = ConfigPublishReceipt.model_validate(default_response.json())

        assert preview_response.status_code == 200
        assert preview.valid
        assert default_response.status_code == 200
        assert default.entry.content_hash == preview.result_content_hash
        assert default.activation.entry_id == "manual-tuning"
        assert default.activation.generation == active.activation.generation + 1

    with LocalDaemonRuntime(tmp_path) as reopened:
        active = reopened.application.config.get_active_config()
        parameter = active.config.parameter_snapshot.get("drive_frequency")

        assert active.entry.id == "manual-tuning"
        assert isinstance(parameter, ScalarParameterValue)
        assert parameter.value == Quantity(value=5.1, unit="GHz")


def test_admission_is_durably_idempotent(tmp_path: Path) -> None:
    submission = _submission()
    state = tmp_path / ".scopecat"
    database = state / "control.sqlite3"
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        client = TestClient(runtime.app())
        admission_services: list[daemon_services.AdmissionService] = []
        for _ in range(2):
            sqlite = SQLiteDatabase(database)
            runs = SQLiteRunRepository(sqlite, state / "objects")
            registry = SQLiteConfigRegistryStore(sqlite, runs=runs)
            admission_services.append(
                daemon_services.AdmissionService(
                    control=SQLiteControlPlane(sqlite),
                    runs=runs,
                    services=ProjectStateServices(
                        runs=runs,
                        config_registry=registry.read_unit_of_work,
                    ),
                )
            )
        services = tuple(admission_services)
        barrier = Barrier(len(services))

        def submit(service: daemon_services.AdmissionService) -> RunAdmission:
            barrier.wait()
            return service.submit_run(submission)

        with ThreadPoolExecutor(max_workers=len(services)) as pool:
            admissions = tuple(pool.map(submit, services))

        retry = client.post(
            "/api/v1/runs",
            json=submission.model_dump(mode="json"),
        )
        changed = client.post(
            "/api/v1/runs",
            json=submission.model_copy(
                update={"request": RunRequest(metadata={"changed": True})}
            ).model_dump(mode="json"),
        )

        assert admissions[0] == admissions[1]
        assert retry.status_code == 201
        assert RunAdmission.model_validate(retry.json()) == admissions[0]
        assert changed.status_code == 409
        run_id = admissions[0].run_id
        published_run_ids = [
            manifest.run_id for manifest in list_test_runs(_run_repository(tmp_path))
        ]
        assert published_run_ids == [run_id]
        assert _manifest(runtime, run_id).outcome is None
        listed = client.get("/api/v1/runs").json()
        assert len(listed["items"]) == 1
        assert listed["items"][0]["control"]["state"] == "queued"
        assert [
            event.kind
            for event in _events(runtime, run_id=run_id).items
            if event.kind == "run_admitted"
        ] == ["run_admitted"]

    with LocalDaemonRuntime(tmp_path) as reopened:
        persisted = reopened.application.submit_run(submission)
        assert persisted.run_id == run_id


@pytest.mark.parametrize(
    "instrument_update",
    [
        {"exclusivity_key": "alternate-source"},
        {"driver_id": "alternate.driver"},
        {
            "connection": TcpipSocketInstrumentConnection(
                host="127.0.0.1",
                port=5025,
            )
        },
    ],
)
def test_client_planned_admission_rejects_instrument_inventory_changes(
    tmp_path: Path,
    instrument_update: dict[str, object],
) -> None:
    authoritative = _config()
    [instrument] = authoritative.instrument_registry.instruments
    registry = authoritative.instrument_registry.model_copy(
        update={"instruments": [instrument.model_copy(update=instrument_update)]}
    )
    submitted = authoritative.model_copy(
        update={
            "system": authoritative.system.model_copy(
                update={"instrument_registry": registry}
            )
        }
    )
    submission = _submission("changed-inventory").model_copy(
        update={"config": submitted}
    )

    with LocalDaemonRuntime(
        tmp_path,
        bootstrap_config=authoritative,
    ) as runtime:
        with pytest.raises(BackendConflict, match="instrument inventory differs"):
            runtime.application.submit_run(submission)

        assert (
            runtime.application.runs.list_runs(
                limit=10,
                before=None,
                state=None,
            ).items
            == ()
        )


def test_config_publish_rejects_rekey_with_a_queued_run(tmp_path: Path) -> None:
    config = _config()
    with LocalDaemonRuntime(tmp_path, bootstrap_config=config) as runtime:
        queued = runtime.application.submit_run(_submission("queued-before-rekey"))
        active = runtime.application.config.get_active_config()
        [instrument] = config.instrument_registry.instruments
        rekeyed_registry = config.instrument_registry.model_copy(
            update={
                "instruments": [
                    instrument.model_copy(
                        update={"exclusivity_key": "alternate-source"}
                    )
                ]
            }
        )
        rekeyed = config.model_copy(
            update={
                "id": "rekeyed",
                "system": config.system.model_copy(
                    update={"instrument_registry": rekeyed_registry}
                ),
            }
        )

        with pytest.raises(
            BackendConflict,
            match="cannot change its exclusivity key",
        ):
            runtime.application.config.publish_config(
                ConfigPublishCommand(
                    source=DirectConfigRevisionSource(config=rekeyed),
                    entry_id="rekeyed",
                    actor="operator",
                    expected_generation=active.activation.generation,
                )
            )

        current = runtime.application.config.get_active_config()
        assert current.activation == active.activation
        assert (
            runtime.application.executor._control.get_run(queued.run_id).state
            == "queued"
        )


def test_admission_fences_an_activation_after_active_resolution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    with LocalDaemonRuntime(tmp_path, bootstrap_config=config) as runtime:
        admission = runtime.application._admission
        resolve_active = admission._resolve_active_config

        def resolve_then_activate() -> ActiveConfigRegistrySnapshot:
            resolved = resolve_active()
            runtime.application.config.publish_config(
                ConfigPublishCommand(
                    source=DirectConfigRevisionSource(
                        config=config.model_copy(
                            update={"id": "activated-during-submit"}
                        )
                    ),
                    entry_id="activated-during-submit",
                    actor="operator",
                    expected_generation=resolved.activation.generation,
                )
            )
            return resolved

        monkeypatch.setattr(
            admission,
            "_resolve_active_config",
            resolve_then_activate,
        )

        with pytest.raises(BackendConflict, match="active configuration changed"):
            runtime.application.submit_run(_submission("activation-race"))

        assert (
            runtime.application.runs.list_runs(
                limit=10,
                before=None,
                state=None,
            ).items
            == ()
        )
        assert list_test_runs(_run_repository(tmp_path)) == []


def test_registry_admission_replays_but_uses_current_inventory_for_new_runs(
    tmp_path: Path,
) -> None:
    config = _config()
    with LocalDaemonRuntime(tmp_path, bootstrap_config=config) as runtime:
        active = runtime.application.config.get_active_config()
        source = ConfigRegistryRunConfigSource(
            selector="active",
            entry_id=active.entry.id,
            config_ref=active.entry.config_ref,
            content_hash=active.entry.content_hash,
            registry_generation=active.activation.generation,
        )
        submission = _submission("registry-source").model_copy(
            update={"config_source": source}
        )
        admitted = runtime.application.submit_run(submission)

        [instrument] = config.instrument_registry.instruments
        changed_registry = config.instrument_registry.model_copy(
            update={
                "instruments": [
                    instrument.model_copy(update={"driver_id": "alternate.driver"})
                ]
            }
        )
        changed = config.model_copy(
            update={
                "id": "changed-inventory",
                "system": config.system.model_copy(
                    update={"instrument_registry": changed_registry}
                ),
            }
        )
        runtime.application.config.publish_config(
            ConfigPublishCommand(
                source=DirectConfigRevisionSource(config=changed),
                entry_id="changed-inventory",
                actor="operator",
                expected_generation=active.activation.generation,
            )
        )

        assert runtime.application.submit_run(submission) == admitted
        with pytest.raises(BackendConflict, match="instrument inventory differs"):
            runtime.application.submit_run(
                submission.model_copy(
                    update={"submission_id": "historical-registry-source"}
                )
            )
        current = runtime.application.submit_run(
            _submission("current-active-inventory").model_copy(
                update={"config": changed}
            )
        )
        control = runtime.application.executor._control.get_run(current.run_id)
        assert control.admission.resource_claims == (
            ResourceKey(kind="instrument", id="source-0"),
        )

        with pytest.raises(BackendConflict, match="does not match its registry entry"):
            runtime.application.submit_run(
                submission.model_copy(
                    update={
                        "submission_id": "forged-registry-source",
                        "config_source": source.model_copy(
                            update={"config_ref": "forged-config-ref"}
                        ),
                    }
                )
            )


def test_authority_failure_replays_a_concurrently_admitted_submission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config()
    submission = _submission("concurrent-authority-change")
    state = tmp_path / ".scopecat"
    database = state / "control.sqlite3"
    with LocalDaemonRuntime(tmp_path, bootstrap_config=config) as runtime:
        sqlite = SQLiteDatabase(database)
        runs = SQLiteRunRepository(sqlite, state / "objects")
        registry = SQLiteConfigRegistryStore(sqlite, runs=runs)
        racing = daemon_services.AdmissionService(
            control=SQLiteControlPlane(sqlite),
            runs=runs,
            services=ProjectStateServices(
                runs=runs,
                config_registry=registry.read_unit_of_work,
            ),
        )
        resolve_active = racing._resolve_active_config
        admitted: RunAdmission | None = None

        def resolve_after_competing_admission() -> ActiveConfigRegistrySnapshot:
            nonlocal admitted
            admitted = runtime.application.submit_run(submission)
            active = runtime.application.config.get_active_config()
            [instrument] = config.instrument_registry.instruments
            changed_registry = config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        instrument.model_copy(update={"driver_id": "alternate.driver"})
                    ]
                }
            )
            runtime.application.config.publish_config(
                ConfigPublishCommand(
                    source=DirectConfigRevisionSource(
                        config=config.model_copy(
                            update={
                                "id": "concurrent-inventory-change",
                                "system": config.system.model_copy(
                                    update={"instrument_registry": changed_registry}
                                ),
                            }
                        )
                    ),
                    entry_id="concurrent-inventory-change",
                    actor="operator",
                    expected_generation=active.activation.generation,
                )
            )
            return resolve_active()

        monkeypatch.setattr(
            racing,
            "_resolve_active_config",
            resolve_after_competing_admission,
        )

        replayed = racing.submit_run(submission)

        assert admitted is not None
        assert replayed == admitted


def test_admission_canonicalizes_domain_only_instrument_claims(
    tmp_path: Path,
) -> None:
    config = _domain_only_config()
    target = config.domain_target
    assert target is not None
    logical_requirements = (RunResourceRequirement(id="source-0", kind="instrument"),)
    with LocalDaemonRuntime(tmp_path, bootstrap_config=config) as runtime:
        admitted = runtime.application.submit_run(
            _domain_only_submission(
                config,
                submission_id="domain-canonical",
                requirements=logical_requirements,
            )
        )
        control = runtime.application.executor._control.get_run(admitted.run_id)
        public = runtime.application.runs.get_run(admitted.run_id)

    assert control.admission.plan.run_resource_requirements == logical_requirements
    assert control.admission.resource_claims == (
        ResourceKey(id="rack-a/source", kind="instrument"),
    )
    assert tuple(item.resource.id for item in public.resources) == ("source-0",)
    public_control = public.control.model_dump(mode="json")
    assert set(public_control["admission"]) == {
        "run_id",
        "plan",
        "display_name",
        "tags",
        "description",
        "admitted_at",
    }
    assert set(public_control["admission"]["plan"]) == {
        "experiment_id",
        "experiment_kind",
        "point_count",
        "coordinate_ids",
        "record_ids",
        "run_resource_requirements",
    }
    assert "rack-a/source" not in str(public_control)


def test_admission_rejects_invalid_domain_only_requirements(
    tmp_path: Path,
) -> None:
    config = _domain_only_config()
    target = config.domain_target
    assert target is not None
    requirements = (
        RunResourceRequirement(id="source-0", kind="instrument"),
        RunResourceRequirement(id="rack-a/source", kind="instrument"),
    )
    with LocalDaemonRuntime(tmp_path, bootstrap_config=config) as runtime:
        with pytest.raises(BackendConflict, match="unknown instruments"):
            runtime.application.submit_run(
                _domain_only_submission(
                    config,
                    submission_id="domain-invalid-instrument",
                    requirements=requirements,
                )
            )

        assert (
            runtime.application.runs.list_runs(
                limit=10,
                before=None,
                state=None,
            ).items
            == ()
        )


@pytest.mark.parametrize(
    "target_update",
    [
        {"id": "tests.forged-target"},
        {"kind": "tests.forged-domain"},
        {"instrument_ids": []},
    ],
)
def test_admission_rejects_domain_requirement_outside_active_authority(
    tmp_path: Path,
    target_update: dict[str, object],
) -> None:
    config = _domain_only_config()
    target = config.domain_target
    assert target is not None
    submitted = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={"domain_target": target.model_copy(update=target_update)}
            )
        }
    )
    submitted_target = submitted.domain_target
    assert submitted_target is not None
    requirements = (RunResourceRequirement(id="source-0", kind="instrument"),)
    with (
        LocalDaemonRuntime(tmp_path, bootstrap_config=config) as runtime,
        pytest.raises(
            BackendConflict,
            match="differs from the active configuration",
        ),
    ):
        runtime.application.submit_run(
            _domain_only_submission(
                submitted,
                submission_id="domain-invalid-authority",
                requirements=requirements,
            )
        )


def test_post_run_analysis_policy_acceptance_and_candidate_activation_closed_loop(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        client = TestClient(runtime.app())
        admission = runtime.application.submit_run(_submission("post-run-loop"))
        proposal = _analysis_proposal(admission.run_id)
        analysis_command = _analysis_command(proposal)
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
        dataset_bytes = RunDatasetBytesView.model_validate(
            client.get(
                f"/api/v1/runs/{admission.run_id}/datasets/analysis-fit-fits/bytes",
                params={"expected_kind": "analysis_dataset"},
            ).json()
        )
        analysis_artifact = client.get(
            f"/api/v1/runs/{admission.run_id}/artifacts/analysis-fit-fit-report/text",
            params={"expected_kind": "analysis_artifact"},
        )
        attachment_command = RunAttachmentCommand(
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
        activated = client.post(
            "/api/v1/config-registry/default",
            json=ConfigPublishCommand(
                source=CandidateConfigRevisionSource(
                    run_id=admission.run_id,
                    proposal_id=proposal.id,
                ),
                entry_id="candidate-fit",
                actor="nightly-calibration",
                expected_generation=1,
                note="fit evidence reviewed",
            ).model_dump(mode="json"),
        )
        approved_proposals = ParameterProposalListView.model_validate(
            client.get(f"/api/v1/runs/{admission.run_id}/parameter-proposals").json()
        )

        saved = AnalysisSaveReceipt.model_validate(first_save.json())
        retry = AnalysisSaveReceipt.model_validate(retry_save.json())
        activation = ConfigPublishReceipt.model_validate(activated.json())
        approval = approved_proposals.items[0].approval
        assert approval is not None
        events = _events(runtime, run_id=admission.run_id).items

        assert first_save.status_code == 201
        assert retry == saved
        assert analyses.json()["items"][0]["analysis"]["key"] == "fit"
        assert analysis_detail.json()["entry"]["id"] == "analysis-fit"
        assert analysis_record.json()["content"]["title"] == "fit"
        persisted_outputs = analysis_record.json()["content"]["outputs"]
        assert persisted_outputs[0]["content"]["preview"] == {
            "columns": [{"id": "bias", "label": None, "unit": None}],
            "rows": [{"cells": [1.0]}, {"cells": [2.0]}],
        }
        assert persisted_outputs[0]["content"]["total_rows"] == 2
        assert not persisted_outputs[0]["content"]["truncated"]
        assert persisted_outputs[1]["content"]["dataset_id"] == "analysis-fit-fits"
        restored_dataset = DerivedDataset.from_arrow_ipc(
            dataset_bytes.content_bytes(),
            schema=DerivedDataset.from_payload(
                cast(
                    "AnalysisDatasetOutputPayload", analysis_command.outputs[1]
                ).content
            ).schema,
        )
        assert restored_dataset.table.to_pylist() == [
            {"bias": 1.0, "signal": 3.0},
            {"bias": 2.0, "signal": 4.0},
        ]
        assert persisted_outputs[2]["content"]["preview"]["series"][0] == {
            "id": "signal",
            "label": "signal",
            "x": [1.0, 2.0],
            "y": [3.0, 4.0],
        }
        assert persisted_outputs[2]["content"]["total_points"] == 2
        assert not persisted_outputs[2]["content"]["truncated"]
        assert persisted_outputs[3]["content"]["proposal_id"] == proposal.id
        assert persisted_outputs[4]["content"]["artifact_id"] == (
            "analysis-fit-fit-report"
        )
        assert analysis_artifact.json()["content"] == "# Fit report\n"
        assert attachment.json()["filename"] == "notes.md"
        assert attachment_text.json()["content"] == "operator notes\n"
        assert config.config == _config()
        assert proposals.items[0].proposal == proposal
        assert proposals.items[0].approval is None
        assert approval.actor == "nightly-calibration"
        assert approved_proposals.items[0].approval == approval
        assert activation.entry.id == "candidate-fit"
        assert activation.activation.generation == 2
        assert [
            event.kind
            for event in events
            if event.kind
            in {
                "analysis_saved",
                "parameter_proposal_approved",
                "config_activated",
            }
        ] == [
            "analysis_saved",
            "parameter_proposal_approved",
            "config_activated",
        ]


def test_analysis_publication_rolls_back_refs_manifest_and_event_together(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        admission = runtime.application.submit_run(_submission("analysis-atomic"))
        proposal = _analysis_proposal(admission.run_id)
        command = _analysis_command(proposal)
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
            dataset_content_ref(
                dataset_id="analysis-fit-fits",
                kind="analysis_dataset",
            ),
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


def test_candidate_publish_rolls_back_approval_with_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        admission = runtime.application.submit_run(_submission("decision-atomic"))
        proposal = _analysis_proposal(admission.run_id)
        runtime.application.runs.save_run_analysis(
            admission.run_id,
            _analysis_command(proposal),
        )
        command = ConfigPublishCommand(
            source=CandidateConfigRevisionSource(
                run_id=admission.run_id,
                proposal_id=proposal.id,
            ),
            entry_id="candidate-atomic",
            actor="nightly-calibration",
            expected_generation=1,
        )
        before = _manifest(runtime, admission.run_id)
        append_event = SQLiteControlPlane.append_event_in_transaction

        def fail_decision_event(
            control: SQLiteControlPlane,
            connection: sqlite3.Connection,
            event: DurableEventInput,
        ) -> DurableEvent:
            if event.kind == "parameter_proposal_approved":
                raise RuntimeError("approval event publication failed")
            return append_event(control, connection, event)

        with monkeypatch.context() as patch:
            patch.setattr(
                SQLiteControlPlane,
                "append_event_in_transaction",
                fail_decision_event,
            )
            with pytest.raises(
                RuntimeError,
                match="approval event publication failed",
            ):
                runtime.application.config.publish_config(command)

        proposals = runtime.application.runs.list_parameter_proposals(admission.run_id)
        assert _manifest(runtime, admission.run_id) == before
        assert proposals.items[0].approval is None
        assert [
            entry.id
            for entry in runtime.application.config.get_config_registry().entries
            if entry.id == "candidate-atomic"
        ] == []
        assert [
            event.kind
            for event in _events(runtime, run_id=admission.run_id).items
            if event.kind == "parameter_proposal_approved"
        ] == []

        receipt = runtime.application.config.publish_config(command)
        proposals = runtime.application.runs.list_parameter_proposals(admission.run_id)

        assert proposals.items[0].approval is not None
        assert receipt.entry.id == "candidate-atomic"
        assert [
            event.kind
            for event in _events(runtime, run_id=admission.run_id).items
            if event.kind == "parameter_proposal_approved"
        ] == ["parameter_proposal_approved"]


def test_executor_start_is_atomic_idempotent_and_quiet_when_resources_busy(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        first = runtime.application.submit_run(_submission("executor-first"))
        request = ExecutorStartRequest(
            executor_id="notebook-1",
        )

        started = runtime.application.executor.start_executor(first.run_id, request)
        retry = runtime.application.executor.start_executor(first.run_id, request)
        events_before_heartbeat = _events(runtime, run_id=first.run_id).items
        renewed = runtime.application.executor.heartbeat_executor(
            first.run_id,
            ExecutorHeartbeat(
                lease_id=started.lease_id,
            ),
        )

        assert retry == started
        assert renewed.expires_at > started.expires_at
        assert _events(runtime, run_id=first.run_id).items == events_before_heartbeat
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
        with pytest.raises(BackendConflict, match="resources are busy"):
            runtime.application.executor.start_executor(
                waiting.run_id,
                ExecutorStartRequest(
                    executor_id="notebook-2",
                ),
            )

        assert _control_run(runtime, waiting.run_id).state == "queued"
        assert _manifest(runtime, waiting.run_id).outcome is None
        assert [
            event.kind for event in _events(runtime, run_id=waiting.run_id).items
        ] == ["run_admitted"]


def test_queued_run_cancellation_is_immediate_durable_and_idempotent(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        client = TestClient(runtime.app())
        admission = runtime.application.submit_run(_submission("cancel-queued"))

        response = client.post(f"/api/v1/runs/{admission.run_id}/cancel")
        retry = client.post(f"/api/v1/runs/{admission.run_id}/cancel")
        missing = client.post("/api/v1/runs/missing-run/cancel")

        assert response.status_code == 200
        receipt = RunCancellationReceipt.model_validate(response.json())
        assert RunCancellationReceipt.model_validate(retry.json()) == receipt
        assert receipt.status == "cancelled"
        assert receipt.outcome is not None
        assert receipt.outcome.result == "cancelled"
        assert receipt.outcome.certainty == "known"
        assert receipt.outcome.problems[0].code == "run_cancelled_before_execution"
        assert missing.status_code == 404
        control = _control_run(runtime, admission.run_id)
        assert control.state == "closed"
        assert control.cancellation_requested_at == receipt.cancellation_requested_at
        assert _manifest(runtime, admission.run_id).outcome == receipt.outcome
        assert _resource_claims(tmp_path) == ()
        assert [
            event.kind
            for event in _events(runtime, run_id=admission.run_id).items
            if event.kind == "run_cancellation_requested"
        ] == ["run_cancellation_requested"]
        with pytest.raises(BackendConflict, match="not ready to start"):
            runtime.application.executor.start_executor(
                admission.run_id,
                ExecutorStartRequest(executor_id="late-executor"),
            )


def test_leased_run_cancellation_reaches_heartbeat_and_preserves_terminal_history(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        admission = runtime.application.submit_run(_submission("cancel-leased"))
        lease = runtime.application.executor.start_executor(
            admission.run_id,
            ExecutorStartRequest(executor_id="notebook-1"),
        )

        requested = runtime.application.cancel_run(admission.run_id)
        retry = runtime.application.cancel_run(admission.run_id)
        heartbeat = runtime.application.executor.heartbeat_executor(
            admission.run_id,
            ExecutorHeartbeat(lease_id=lease.lease_id),
        )

        assert requested == retry
        assert requested.status == "cancel_requested"
        assert heartbeat.cancellation_requested_at == (
            requested.cancellation_requested_at
        )
        assert (
            _control_run(runtime, admission.run_id).cancellation_requested_at
            == requested.cancellation_requested_at
        )
        assert _manifest(runtime, admission.run_id).outcome is None

        outcome = RunOutcome(
            run_id=admission.run_id,
            result="cancelled",
            certainty="known",
            problems=(
                problem(
                    "run_cancellation_requested",
                    "run stopped at a safe checkpoint after cancellation was requested",
                    phase=ProblemPhase.EXECUTION,
                ),
            ),
        )
        terminal = runtime.application.executor.commit_terminal(
            admission.run_id,
            TerminalRunCommitCommand(
                lease_id=lease.lease_id,
                outcome=outcome,
            ),
        )
        completed = runtime.application.cancel_run(admission.run_id)

        assert terminal.outcome == outcome
        assert completed.status == "cancelled"
        assert completed.outcome == outcome
        assert completed.cancellation_requested_at == (
            requested.cancellation_requested_at
        )
        assert _control_run(runtime, admission.run_id).state == "closed"
        assert _resource_claims(tmp_path) == ()

        racing = runtime.application.submit_run(_submission("cancel-terminal-race"))
        racing_lease = runtime.application.executor.start_executor(
            racing.run_id,
            ExecutorStartRequest(executor_id="notebook-race"),
        )
        racing_request = runtime.application.cancel_run(racing.run_id)
        success_intent = TerminalRunCommitCommand(
            lease_id=racing_lease.lease_id,
            outcome=RunOutcome(
                run_id=racing.run_id,
                result="succeeded",
                certainty="known",
            ),
        )

        raced_terminal = runtime.application.executor.commit_terminal(
            racing.run_id,
            success_intent,
        )
        raced_retry = runtime.application.executor.commit_terminal(
            racing.run_id,
            success_intent,
        )

        assert racing_request.status == "cancel_requested"
        assert raced_retry == raced_terminal
        assert raced_terminal.outcome is not None
        assert raced_terminal.outcome.result == "cancelled"
        assert raced_terminal.outcome.certainty == "known"
        assert raced_terminal.outcome.problems[0].code == ("run_cancellation_requested")

        failing = runtime.application.submit_run(_submission("cancel-after-failure"))
        failing_lease = runtime.application.executor.start_executor(
            failing.run_id,
            ExecutorStartRequest(executor_id="notebook-failure"),
        )
        runtime.application.cancel_run(failing.run_id)
        failed_outcome = RunOutcome(
            run_id=failing.run_id,
            result="failed",
            certainty="known",
            problems=(
                problem(
                    "run_failed_before_cancellation_checkpoint",
                    "run failed before it could honor cancellation",
                    phase=ProblemPhase.EXECUTION,
                ),
            ),
        )

        failed_terminal = runtime.application.executor.commit_terminal(
            failing.run_id,
            TerminalRunCommitCommand(
                lease_id=failing_lease.lease_id,
                outcome=failed_outcome,
            ),
        )

        assert failed_terminal.outcome == failed_outcome

        succeeded = runtime.application.submit_run(_submission("already-succeeded"))
        succeeded_lease = runtime.application.executor.start_executor(
            succeeded.run_id,
            ExecutorStartRequest(executor_id="notebook-2"),
        )
        succeeded_outcome = RunOutcome(
            run_id=succeeded.run_id,
            result="succeeded",
            certainty="known",
        )
        runtime.application.executor.commit_terminal(
            succeeded.run_id,
            TerminalRunCommitCommand(
                lease_id=succeeded_lease.lease_id,
                outcome=succeeded_outcome,
            ),
        )

        not_accepted = runtime.application.cancel_run(succeeded.run_id)

        assert not_accepted.status == "not_accepted"
        assert not_accepted.cancellation_requested_at is None
        assert not_accepted.outcome == succeeded_outcome


def test_run_detail_projects_compact_domain_execution_evidence(tmp_path: Path) -> None:
    class _ResultContract:
        contract_fingerprint = "result-contract"

    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        admission = runtime.application.submit_run(_submission("domain-summary"))
        lease = runtime.application.executor.start_executor(
            admission.run_id,
            ExecutorStartRequest(executor_id="notebook-1"),
        )
        mapping = cast(
            "DomainResultMapping[str]",
            cast("object", _ResultContract()),
        )
        invocation = close_domain_invocation(
            mapping,
            invocation_id="invocation-0",
            target_id="target-0",
            compiler_id="compiler-0",
            capability_fingerprint="capability-fingerprint",
            artifact_id="artifact-0",
            artifact_fingerprint="artifact-fingerprint",
            execution_summary={"local_oscillators": {"drive": {"frequency_hz": 5e9}}},
            target_intent={"dialect": "test"},
            payload={"program": "opaque"},
        )
        execution_id = plan_domain_execution(
            invocation,
            run_id=admission.run_id,
            logical_compute_node_id="domain.batch.0",
        )
        receipt = DomainExecutionReceipt(
            execution_key=execution_id.execution_key,
            status="completed",
            result_fingerprint="result-fingerprint",
            result_count=2,
        )
        transitions = (
            ExecutionTransition(
                run_id=admission.run_id,
                operation_id=execution_id.operation_id,
                stage="domain_execute",
                effect="acquisition",
                state="started",
                evidence={
                    "invocation_intent": invocation.intent.model_dump(mode="json"),
                    "logical_compute_node_id": execution_id.logical_compute_node_id,
                    "execution_key": execution_id.execution_key,
                },
            ),
            ExecutionTransition(
                run_id=admission.run_id,
                operation_id=execution_id.operation_id,
                stage="domain_execute",
                effect="acquisition",
                state="completed",
                evidence={
                    "execution_key": execution_id.execution_key,
                    "intent_fingerprint": execution_id.intent_fingerprint,
                    "receipt": receipt.model_dump(mode="json"),
                },
            ),
        )
        runtime.application.executor.claim_transition(
            admission.run_id,
            ExecutionTransitionClaim(
                lease_id=lease.lease_id,
                transition=transitions[0],
            ),
        )
        with pytest.raises(BackendConflict, match="conflicts with durable run state"):
            runtime.application.executor.claim_transition(
                admission.run_id,
                ExecutionTransitionClaim(
                    lease_id=lease.lease_id,
                    transition=transitions[0],
                ),
            )
        runtime.application.executor.append_transition(
            admission.run_id,
            ExecutionTransitionAppend(
                lease_id=lease.lease_id,
                transition=transitions[1],
            ),
        )

        [execution] = runtime.application.runs.get_run(
            admission.run_id
        ).domain_executions

        assert execution.state == "completed"
        assert execution.receipt_status == "completed"
        assert execution.result_count == 2
        assert execution.execution_summary == {
            "local_oscillators": {"drive": {"frequency_hz": 5e9}}
        }


def test_effect_is_fenced_and_terminal_updates_control(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
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
                executor_id="notebook-1",
            ).model_dump(mode="json"),
        )
        lease = ExecutorLease.model_validate(lease_response.json())
        measurement_records = tuple(
            MeasurementRecord(
                run_id=run_id,
                logical_point_id=f"point-{point_index}",
                point_index=point_index,
                coordinates={
                    "frequency": MeasurementArray.create(
                        dtype="float64",
                        unit="Hz",
                        values=tuple(float(index) for index in range(5)),
                    )
                },
                observables={
                    "signal": MeasurementScalar.create(
                        dtype="float64",
                        value=point_index + 1.25,
                        unit="ratio",
                    ),
                    "trace": (
                        MeasurementUnavailable.create(
                            reason="overload",
                            dtype="complex128",
                            unit="ratio",
                            shape=(5,),
                            metadata={},
                        )
                        if point_index == 0
                        else MeasurementArray.create(
                            dtype="complex128",
                            unit="ratio",
                            values=tuple(
                                complex(point_index + 1.0, index) for index in range(5)
                            ),
                        )
                    ),
                },
            )
            for point_index in range(4)
        )
        measurement_header = MeasurementDatasetHeader(
            run_id=run_id,
            recording_contract_fingerprint="test.recording.v1",
            dataset_schema=MeasurementDatasetSchema(
                dataset_id="raw-measurements",
                point_domain=MeasurementProductGridPointDomain(
                    axes=[
                        MeasurementPointDomainAxis(
                            id="x",
                            size=2,
                            values=[
                                MeasurementScalar.create(dtype="int64", value=value)
                                for value in (10, 20)
                            ],
                        ),
                        MeasurementPointDomainAxis(
                            id="bias",
                            size=2,
                            values=[
                                MeasurementScalar.create(dtype="int64", value=value)
                                for value in (0, 1)
                            ],
                        ),
                    ]
                ),
                dimensions=[
                    MeasurementDimension(id="point", kind="point", size=4),
                    MeasurementDimension(id="sample", kind="frequency", size=5),
                ],
                variables=[
                    MeasurementVariable(
                        id="frequency",
                        role="coordinate",
                        dtype="float64",
                        unit="Hz",
                        dims=["point", "sample"],
                        recording_group_id="readout",
                    ),
                    MeasurementVariable(
                        id="signal",
                        role="observable",
                        dtype="float64",
                        unit="ratio",
                        dims=["point"],
                    ),
                    MeasurementVariable(
                        id="trace",
                        role="observable",
                        dtype="complex128",
                        unit="ratio",
                        dims=["point", "sample"],
                        recording_group_id="readout",
                    ),
                ],
                primary_coordinates=["frequency"],
                primary_observables=["signal", "trace"],
            ),
            expected_record_count=4,
        )
        measurement_append = MeasurementDatasetAppend(
            run_id=run_id,
            header_content_hash=measurement_header.content_hash,
            start_index=0,
            records=measurement_records,
        )
        missing_schema_slice = client.post(
            f"/api/v1/runs/{run_id}/measurements/query",
            json={"fixed_axis_indices": {"bias": 1}},
        )
        missing_schema_trace = client.post(
            f"/api/v1/runs/{run_id}/measurements/traces/query",
            json={"observable_id": "trace"},
        )
        header_response = client.post(
            f"/api/v1/runs/{run_id}/measurements/header",
            json=MeasurementHeaderCommand(
                lease_id=lease.lease_id,
                header=measurement_header,
            ).model_dump(mode="json"),
        )
        measurement_response = client.post(
            f"/api/v1/runs/{run_id}/measurements/append",
            json=MeasurementAppendCommand(
                lease_id=lease.lease_id,
                append=measurement_append,
            ).model_dump(mode="json"),
        )
        detail = client.get(f"/api/v1/runs/{run_id}")
        measurement_preview = client.get(f"/api/v1/runs/{run_id}/measurements/preview")
        measurement_arrow = client.post(
            f"/api/v1/runs/{run_id}/measurements/arrow",
            json={
                "columns": [
                    {"name": "sample_hz", "variable_id": "frequency"},
                    {"name": "response", "variable_id": "trace"},
                ],
                "limit": 2,
                "diagnostics": "reason",
                "layout": "observations",
            },
        )
        measurement_slice = client.post(
            f"/api/v1/runs/{run_id}/measurements/query",
            json={
                "fixed_axis_indices": {"bias": 1},
                "limit": 1,
                "include_schema": True,
            },
        )
        invalid_measurement_slice = client.post(
            f"/api/v1/runs/{run_id}/measurements/query",
            json={"fixed_axis_indices": {"missing": 0}},
        )
        trace_preview = client.post(
            f"/api/v1/runs/{run_id}/measurements/traces/query",
            json={
                "observable_id": "trace",
                "coordinate_id": "frequency",
                "fixed_axis_indices": {"bias": 1},
                "max_series": 2,
                "max_samples": 4,
                "value_mode": "imag",
            },
        )
        truncated_trace_preview = client.post(
            f"/api/v1/runs/{run_id}/measurements/traces/query",
            json={
                "observable_id": "trace",
                "coordinate_id": "frequency",
                "max_series": 1,
                "max_samples": 2,
            },
        )
        exhausted_trace_preview = client.post(
            f"/api/v1/runs/{run_id}/measurements/traces/query",
            json={
                "observable_id": "trace",
                "coordinate_id": "frequency",
                "fixed_axis_indices": {"x": 0},
                "max_series": 2,
                "max_samples": 4,
            },
        )
        invalid_trace_preview = client.post(
            f"/api/v1/runs/{run_id}/measurements/traces/query",
            json={"recording_group_id": "missing"},
        )
        transition = ExecutionTransition(
            run_id=run_id,
            operation_id="fetch-1",
            stage="domain_execute",
            effect="read",
            state="completed",
            timestamp=datetime(2026, 7, 23, 9, 0, 1, tzinfo=UTC),
            point_index=0,
            instrument_id="scope-1",
            evidence={"measurement_count": 1},
        )
        command = ExecutionTransitionAppend(
            lease_id=lease.lease_id,
            transition=transition,
        )

        committed = client.post(
            f"/api/v1/runs/{run_id}/transitions",
            json=command.model_dump(mode="json"),
        )
        retry = client.post(
            f"/api/v1/runs/{run_id}/transitions",
            json=command.model_copy(
                update={
                    "transition": transition.model_copy(
                        update={
                            "timestamp": transition.timestamp + timedelta(seconds=1)
                        }
                    )
                }
            ).model_dump(mode="json"),
        )
        changed = client.post(
            f"/api/v1/runs/{run_id}/transitions",
            json=command.model_copy(
                update={"transition": transition.model_copy(update={"state": "failed"})}
            ).model_dump(mode="json"),
        )
        stale = client.post(
            f"/api/v1/runs/{run_id}/transitions",
            json=command.model_copy(
                update={
                    "lease_id": "stale-lease",
                }
            ).model_dump(mode="json"),
        )

        assert header_response.status_code == 200
        assert measurement_response.status_code == 200
        assert detail.json()["control"]["state"] == "leased"
        assert detail.json()["manifest"]["outcome"] is None
        assert detail.json()["resources"][0]["status"] == "active"
        assert measurement_preview.json()["items"][0]["point_index"] == 0
        assert (
            measurement_preview.json()["dataset_schema"]["dataset_id"]
            == "raw-measurements"
        )
        assert measurement_preview.json()["truncated"] is False
        assert measurement_arrow.status_code == 200
        assert measurement_arrow.headers["x-scopecat-next-offset"] == "2"
        assert measurement_arrow.headers["x-scopecat-snapshot-size"] == "4"
        arrow_table = pa.ipc.open_stream(measurement_arrow.content).read_all()
        assert arrow_table.schema.names == [
            "point_index",
            "logical_point_id",
            "sample_index",
            "sample_hz",
            "sample_hz__unavailable_reason",
            "response",
            "response__unavailable_reason",
        ]
        assert arrow_table.num_rows == 10
        assert arrow_table["sample_index"].to_pylist() == [0, 1, 2, 3, 4] * 2
        assert arrow_table["sample_hz"].to_pylist() == [0.0, 1.0, 2.0, 3.0, 4.0] * 2
        assert (
            arrow_table["response__unavailable_reason"].to_pylist()
            == [
                "overload",
            ]
            * 5
            + [None] * 5
        )
        assert measurement_slice.status_code == 200
        assert missing_schema_slice.status_code == 409
        assert missing_schema_trace.status_code == 409
        assert measurement_slice.json()["items"][0]["point_index"] == 1
        assert measurement_slice.json()["selected_point_count"] == 2
        assert measurement_slice.json()["truncated"]
        assert measurement_slice.json()["dataset_schema"]["dataset_id"] == (
            "raw-measurements"
        )
        assert invalid_measurement_slice.status_code == 409
        assert trace_preview.status_code == 200
        assert trace_preview.json()["coordinate_id"] == "frequency"
        assert trace_preview.json()["selected_series_count"] == 2
        assert trace_preview.json()["returned_series_count"] == 2
        assert not trace_preview.json()["truncated_series"]
        assert trace_preview.json()["source_sample_count"] == 10
        assert trace_preview.json()["returned_sample_count"] == 4
        assert trace_preview.json()["samples_reduced"]
        assert trace_preview.json()["series"][0] == {
            "point_index": 1,
            "logical_point_id": "point-1",
            "label": "point-1",
            "x": [0.0, 4.0],
            "y": [0.0, 4.0],
            "source_sample_count": 5,
        }
        assert invalid_trace_preview.status_code == 409
        assert truncated_trace_preview.status_code == 200
        assert truncated_trace_preview.json()["selected_series_count"] == 4
        assert truncated_trace_preview.json()["returned_series_count"] == 1
        assert truncated_trace_preview.json()["truncated_series"]
        assert truncated_trace_preview.json()["series"][0]["point_index"] == 1
        assert exhausted_trace_preview.status_code == 200
        assert exhausted_trace_preview.json()["selected_series_count"] == 2
        assert exhausted_trace_preview.json()["returned_series_count"] == 1
        assert not exhausted_trace_preview.json()["truncated_series"]
        assert exhausted_trace_preview.json()["series"][0]["point_index"] == 1
        assert committed.status_code == 200
        assert committed.json()["sequence"] == 0
        committed_transition = ExecutionTransition.model_validate(committed.json())
        assert retry.json() == committed.json()
        assert changed.status_code == 200
        assert changed.json()["sequence"] == 1
        assert stale.status_code == 409
        transition_events = [
            event
            for event in _events(runtime, run_id=run_id).items
            if event.kind == "execution_transition_committed"
        ]
        transition_event = transition_events[0]
        assert len(transition_events) == 2
        assert transition_event.occurred_at == committed_transition.timestamp
        assert transition_event.payload == {
            "sequence": 0,
            "operation_id": "fetch-1",
            "stage": "domain_execute",
            "effect": "read",
            "state": "completed",
            "point_index": 0,
            "instrument_id": "scope-1",
            "problems": [],
            "evidence": {"measurement_count": 1},
        }

        outcome = RunOutcome(
            run_id=run_id,
            result="succeeded",
            certainty="known",
            finished_at=datetime.now(tz=UTC),
        )
        terminal = accepted.model_copy(
            update={
                "outcome": outcome,
            }
        )
        terminal_command = TerminalRunCommitCommand(
            lease_id=lease.lease_id,
            outcome=outcome,
        )
        terminal_run_mismatch = client.post(
            f"/api/v1/runs/{run_id}/terminal",
            json=terminal_command.model_copy(
                update={"outcome": outcome.model_copy(update={"run_id": "another-run"})}
            ).model_dump(mode="json"),
        )
        completed = client.post(
            f"/api/v1/runs/{run_id}/terminal",
            json=terminal_command.model_dump(mode="json"),
        )
        terminal_retry = client.post(
            f"/api/v1/runs/{run_id}/terminal",
            json=terminal_command.model_dump(mode="json"),
        )
        terminal_conflict = client.post(
            f"/api/v1/runs/{run_id}/terminal",
            json=terminal_command.model_copy(
                update={
                    "outcome": outcome.model_copy(
                        update={"finished_at": datetime(2026, 7, 23, 10, tzinfo=UTC)}
                    )
                }
            ).model_dump(mode="json"),
        )

        assert terminal_run_mismatch.status_code == 422
        assert terminal_run_mismatch.json() == {
            "detail": "path run_id must match request body"
        }
        assert completed.status_code == 200
        assert completed.json()["outcome"]["result"] == "succeeded"
        assert terminal_retry.json() == completed.json()
        assert terminal_conflict.status_code == 409
        control_run = _control_run(runtime, run_id)
        assert control_run.state == "closed"
        assert _manifest(runtime, run_id) == terminal
        assert _resource_claims(tmp_path) == ()
        terminal_detail = client.get(f"/api/v1/runs/{run_id}").json()
        assert terminal_detail["resources"][0]["status"] == "released"


def test_effect_and_terminal_publication_roll_back_with_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        submission = _submission()
        admission = runtime.application.submit_run(submission)
        lease = runtime.application.executor.start_executor(
            admission.run_id,
            ExecutorStartRequest(
                executor_id="notebook-1",
            ),
        )
        measurement = MeasurementRecord(
            run_id=admission.run_id,
            logical_point_id="point-0",
            point_index=0,
            coordinates={},
            observables={
                "signal": MeasurementScalar.create(
                    dtype="float64",
                    value=1.25,
                    unit="ratio",
                )
            },
        )
        header = MeasurementDatasetHeader(
            run_id=admission.run_id,
            recording_contract_fingerprint="test.recording.v1",
            dataset_schema=MeasurementDatasetSchema(
                dataset_id="raw-measurements",
                point_domain=MeasurementProductGridPointDomain(axes=[]),
                dimensions=[MeasurementDimension(id="point", kind="point", size=1)],
                variables=[
                    MeasurementVariable(
                        id="signal",
                        role="observable",
                        dtype="float64",
                        unit="ratio",
                        dims=["point"],
                    )
                ],
            ),
            expected_record_count=1,
        )
        append = MeasurementDatasetAppend(
            run_id=admission.run_id,
            header_content_hash=header.content_hash,
            start_index=0,
            records=(measurement,),
        )
        runtime.application.executor.initialize_measurements(
            admission.run_id,
            MeasurementHeaderCommand(
                lease_id=lease.lease_id,
                header=header,
            ),
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
                        lease_id=lease.lease_id,
                        append=append,
                    ),
                )

        rolled_back, _, _ = runtime.application.runs.measurement_arrow(
            admission.run_id,
            MeasurementArrowQuery(
                columns=(MeasurementArrowColumn(name="signal", variable_id="signal"),)
            ),
        )
        assert rolled_back.num_rows == 0

        outcome = RunOutcome(
            run_id=admission.run_id,
            result="succeeded",
            certainty="known",
        )
        with monkeypatch.context() as patch:

            def fail_close(*_args: object, **_kwargs: object) -> Never:
                raise RuntimeError("control close failed")

            patch.setattr(
                SQLiteControlPlane,
                "close_run_in_transaction",
                fail_close,
            )
            with pytest.raises(RuntimeError, match="control close failed"):
                runtime.application.executor.commit_terminal(
                    admission.run_id,
                    TerminalRunCommitCommand(
                        lease_id=lease.lease_id,
                        outcome=outcome,
                    ),
                )

        assert _manifest(runtime, admission.run_id).outcome is None
        assert _control_run(runtime, admission.run_id).state == "leased"


def test_restart_quarantines_executor_until_operator_reconciles(
    tmp_path: Path,
) -> None:
    with LocalDaemonRuntime(tmp_path, bootstrap_config=_config()) as runtime:
        submission = _submission("operator-recovery")
        admission = runtime.application.submit_run(submission)
        runtime.application.executor.start_executor(
            admission.run_id,
            ExecutorStartRequest(
                executor_id="notebook-1",
            ),
        )
        run_id = admission.run_id

    with LocalDaemonRuntime(tmp_path) as reopened:
        attention = _control_run(reopened, run_id)
        assert attention.state == "attention_required"
        assert attention.attention_reason == "daemon_restarted"
        assert _resource_claims(tmp_path)[0].status == "quarantined"

        resolved = reopened.application.resolve_attention(run_id)
        assert resolved.state == "closed"
        assert resolved.released_resource_count == 1
        control = _control_run(reopened, run_id)
        assert control.state == "closed"
        manifest = _manifest(reopened, run_id)
        assert manifest.outcome is not None
        assert manifest.outcome.certainty == "indeterminate"
        assert manifest.outcome.problems[0].code == "daemon.executor_loss_reconciled"
        assert _resource_claims(tmp_path) == ()
