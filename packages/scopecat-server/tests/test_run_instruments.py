from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Barrier, Event
from typing import Literal, override

import httpx2
import pytest
from fastapi.testclient import TestClient
from scopecat.application import LabApplication
from scopecat.control.models import ResourceKey, RunPlanSummary
from scopecat.daemon.client import DaemonClient
from scopecat.daemon.wire import (
    ExecutorStartRequest,
    InstrumentSessionEndCommand,
    InstrumentSessionOpenCommand,
    RunInstrumentApplyCommand,
    RunInstrumentCollectCommand,
    RunInstrumentLifecycleCommand,
    RunInstrumentProvisionCommand,
    RunInstrumentReadCommand,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.kernel.problems import ProblemPhase, model_location, problem
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.kernel.state import StateValue
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments import (
    CollectCommand,
    CollectProductRequest,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateCommand,
    InstrumentStateCommandField,
)
from tests.testkit.instrument_drivers import SignalInstrumentDriver, load_config

from scopecat_server import LocalDaemonRuntime
from scopecat_server.errors import BackendConflict, BackendNotFound
from scopecat_server.instrument_service import InstrumentService


class _Driver(SignalInstrumentDriver):
    def __init__(
        self,
        instrument_id: str,
        *,
        fail_action: Literal["cleanup", "abort", "close"] | None = None,
        apply_barrier: Barrier | None = None,
        abort_entered: Event | None = None,
        abort_release: Event | None = None,
    ) -> None:
        super().__init__(instrument_id=instrument_id)
        self.fail_action: Literal["cleanup", "abort", "close"] | None = fail_action
        self.apply_barrier = apply_barrier
        self.abort_entered = abort_entered
        self.abort_release = abort_release
        self.read_count = 0
        self.cleanup_count = 0
        self.abort_count = 0
        self.close_count = 0

    @override
    def read_state(self):  # type: ignore[no-untyped-def]
        self.read_count += 1
        return super().read_state()

    @override
    def apply_state(self, command: InstrumentStateCommand):  # type: ignore[no-untyped-def]
        if self.apply_barrier is not None:
            self.apply_barrier.wait(timeout=2)
        return super().apply_state(command)

    @override
    def cleanup(self) -> None:
        self.cleanup_count += 1
        if self.fail_action == "cleanup":
            raise RuntimeError("cleanup failed")

    @override
    def abort(self) -> None:
        self.abort_count += 1
        if self.abort_entered is not None:
            self.abort_entered.set()
        if self.abort_release is not None:
            assert self.abort_release.wait(timeout=2)
        if self.fail_action == "abort":
            raise RuntimeError("abort failed")

    @override
    def close(self) -> None:
        self.close_count += 1
        if self.fail_action == "close":
            raise RuntimeError("close failed")


class _Provider:
    provider_id = "tests.run_provider"

    def __init__(
        self,
        *,
        fail_action: Literal["cleanup", "abort", "close"] | None = None,
        reject: bool = False,
        fail_describe: bool = False,
        fail_provide: bool = False,
        apply_barrier: Barrier | None = None,
        unclaimed_problem_id: str | None = None,
        provide_entered: Event | None = None,
        provide_release: Event | None = None,
        abort_entered: Event | None = None,
        abort_release: Event | None = None,
    ) -> None:
        self.fail_action: Literal["cleanup", "abort", "close"] | None = fail_action
        self.reject = reject
        self.fail_describe = fail_describe
        self.fail_provide = fail_provide
        self.apply_barrier = apply_barrier
        self.unclaimed_problem_id = unclaimed_problem_id
        self.provide_entered = provide_entered
        self.provide_release = provide_release
        self.abort_entered = abort_entered
        self.abort_release = abort_release
        self.provide_count = 0
        self.describe_contexts: list[tuple[str, ...]] = []
        self.provided_config_ids: list[str] = []
        self.drivers: list[_Driver] = []

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        if self.fail_describe:
            raise RuntimeError("describe failed")
        self.describe_contexts.append(context.instrument_ids)
        selected = set(context.instrument_ids) or {
            item.id for item in context.config.instrument_registry.instruments
        }
        descriptions = tuple(
            _Driver(item.id).describe()
            for item in context.config.instrument_registry.instruments
            if item.id in selected
        )
        problems = (
            (
                problem(
                    "unclaimed_instrument_problem",
                    "another instrument is unavailable",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location("instrument_provider"),
                    details={"instrument_id": self.unclaimed_problem_id},
                ),
            )
            if self.unclaimed_problem_id is not None
            else ()
        )
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=descriptions,
            problems=problems,
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        self.provide_count += 1
        self.provided_config_ids.append(context.config.id)
        if self.fail_provide:
            raise RuntimeError("provide failed")
        drivers = tuple(
            _Driver(
                instrument_id,
                fail_action=self.fail_action,
                apply_barrier=self.apply_barrier,
                abort_entered=self.abort_entered,
                abort_release=self.abort_release,
            )
            for instrument_id in context.instrument_ids
        )
        self.drivers.extend(drivers)
        if self.provide_entered is not None:
            self.provide_entered.set()
        if self.provide_release is not None:
            assert self.provide_release.wait(timeout=2)
        problems = (
            (
                problem(
                    "provider_rejected",
                    "provider rejected the connection",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location("instrument_provider"),
                ),
            )
            if self.reject
            else ()
        )
        return InstrumentProviderResult(
            drivers=drivers,
            problems=problems,
        )


def test_run_operations_replay_without_repeating_driver_calls(
    tmp_path: Path,
) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        provision = RunInstrumentProvisionCommand(
            lease_id=lease_id,
            operation_id="provide",
        )

        first_provision = instruments.provision_run(run_id, provision)
        assert instruments.provision_run(run_id, provision) == first_provision
        assert first_provision.provider_id == provider.provider_id
        [driver] = provider.drivers

        read = RunInstrumentReadCommand(
            lease_id=lease_id,
            operation_id="read",
        )
        first_read = instruments.read_run_state(run_id, "source-0", read)
        assert instruments.read_run_state(run_id, "source-0", read) == first_read

        apply = RunInstrumentApplyCommand(
            lease_id=lease_id,
            operation_id="apply",
            command=_apply_command("source-0", operation_id="apply"),
        )
        first_apply = instruments.apply_run_state(run_id, "source-0", apply)
        assert instruments.apply_run_state(run_id, "source-0", apply) == first_apply

        collect = RunInstrumentCollectCommand(
            lease_id=lease_id,
            operation_id="collect",
            command=_collect_command("source-0", operation_id="collect"),
        )
        first_collect = instruments.collect_run(run_id, "source-0", collect)
        assert instruments.collect_run(run_id, "source-0", collect) == first_collect

        cleanup = RunInstrumentLifecycleCommand(
            lease_id=lease_id,
            operation_id="cleanup",
            action="cleanup",
        )
        first_cleanup = instruments.run_lifecycle(
            run_id,
            "source-0",
            cleanup,
        )
        assert instruments.run_lifecycle(run_id, "source-0", cleanup) == first_cleanup
        close = RunInstrumentLifecycleCommand(
            lease_id=lease_id,
            operation_id="close",
            action="close",
        )
        first_close = instruments.run_lifecycle(run_id, "source-0", close)
        assert instruments.run_lifecycle(run_id, "source-0", close) == first_close

        assert provider.provide_count == 1
        assert driver.read_count == 1
        assert len(driver.applied) == 1
        assert len(driver.collect_commands) == 1
        assert driver.cleanup_count == 1
        assert driver.close_count == 1


def test_lost_http_responses_do_not_repeat_run_driver_calls(tmp_path: Path) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client_with_lost_responses(
                transport,
                suffixes=(
                    "/instruments/provision",
                    "/state/read",
                    "/state/apply",
                    "/collect",
                    "/lifecycle",
                ),
            )
            daemon.provision_run_instruments(
                run_id,
                RunInstrumentProvisionCommand(
                    lease_id=lease_id,
                    operation_id="provide",
                ),
            )
            daemon.read_run_instrument_state(
                run_id,
                "source-0",
                RunInstrumentReadCommand(
                    lease_id=lease_id,
                    operation_id="read",
                ),
            )
            daemon.apply_run_instrument_state(
                run_id,
                "source-0",
                RunInstrumentApplyCommand(
                    lease_id=lease_id,
                    operation_id="apply",
                    command=_apply_command("source-0", operation_id="apply"),
                ),
            )
            daemon.collect_run_instrument(
                run_id,
                "source-0",
                RunInstrumentCollectCommand(
                    lease_id=lease_id,
                    operation_id="collect",
                    command=_collect_command("source-0", operation_id="collect"),
                ),
            )
            daemon.run_instrument_lifecycle(
                run_id,
                "source-0",
                RunInstrumentLifecycleCommand(
                    lease_id=lease_id,
                    operation_id="close",
                    action="close",
                ),
            )

        [driver] = provider.drivers
        assert provider.provide_count == 1
        assert driver.read_count == 1
        assert len(driver.applied) == 1
        assert len(driver.collect_commands) == 1
        assert driver.close_count == 1


def test_run_operation_id_is_unique_across_effect_kinds(tmp_path: Path) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )
        instruments.read_run_state(
            run_id,
            "source-0",
            RunInstrumentReadCommand(
                lease_id=lease_id,
                operation_id="shared",
            ),
        )

        with pytest.raises(BackendConflict, match="different instrument operation"):
            instruments.apply_run_state(
                run_id,
                "source-0",
                RunInstrumentApplyCommand(
                    lease_id=lease_id,
                    operation_id="shared",
                    command=_apply_command("source-0", operation_id="shared"),
                ),
            )
        assert not provider.drivers[0].applied


def test_missing_instrument_does_not_reserve_the_run_operation_id(
    tmp_path: Path,
) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )
        operation_id = "reusable-after-route-error"

        with pytest.raises(BackendNotFound, match="not live"):
            instruments.read_run_state(
                run_id,
                "missing",
                RunInstrumentReadCommand(
                    lease_id=lease_id,
                    operation_id=operation_id,
                ),
            )

        receipt = instruments.apply_run_state(
            run_id,
            "source-0",
            RunInstrumentApplyCommand(
                lease_id=lease_id,
                operation_id=operation_id,
                command=_apply_command("source-0", operation_id=operation_id),
            ),
        )
        assert receipt.status == "applied"


def test_selected_claim_order_and_problem_scope_are_run_local(
    tmp_path: Path,
) -> None:
    config = _two_instrument_config()
    provider = _Provider(unclaimed_problem_id="source-0")
    with _runtime(tmp_path, provider, config=config) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            config,
            host_instrument_order=("source-1",),
        )

        receipt = runtime.application.instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )

        assert receipt.status == "ready"
        assert receipt.instrument_ids == ("source-1",)
        assert provider.describe_contexts[-1] == ("source-1",)
        assert [driver.instrument_id for driver in provider.drivers] == ["source-1"]


def test_provision_uses_the_run_accepted_snapshot(tmp_path: Path) -> None:
    active = load_config()
    accepted = active.model_copy(update={"id": "accepted-run-config"})
    provider = _Provider()
    with _runtime(tmp_path, provider, config=active) as runtime:
        run_id, lease_id = _start_run(runtime, accepted)

        runtime.application.instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )

        assert provider.provided_config_ids == ["accepted-run-config"]


def test_known_provider_rejection_closes_drivers_without_quarantine(
    tmp_path: Path,
) -> None:
    provider = _Provider(reject=True)
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())

        receipt = runtime.application.instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )

        assert receipt.status == "rejected"
        assert runtime.application.executor._control.get_run(run_id).state == "leased"
        [driver] = provider.drivers
        assert driver.abort_count == 0
        assert driver.close_count == 1


def test_provider_description_exception_is_a_structured_rejection(
    tmp_path: Path,
) -> None:
    provider = _Provider(fail_describe=True)
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())

        receipt = runtime.application.instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )

        assert receipt.status == "rejected"
        assert [item.code for item in receipt.problems] == [
            "instrument_provider_description_failed"
        ]
        assert runtime.application.executor._control.get_run(run_id).state == "leased"
        assert not provider.drivers


def test_provider_construction_exception_is_a_structured_rejection(
    tmp_path: Path,
) -> None:
    def factory(_root: Path) -> LabApplication:
        def build(_config: ConfigProfileSnapshot) -> ExperimentSystem:
            raise RuntimeError("build failed")

        return LabApplication(build_system=build)

    with LocalDaemonRuntime(
        tmp_path,
        bootstrap_config=load_config(),
        application_factory=factory,
    ) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())

        receipt = runtime.application.instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )

        assert receipt.status == "rejected"
        assert [item.code for item in receipt.problems] == [
            "instrument_provider_construction_failed"
        ]
        assert runtime.application.executor._control.get_run(run_id).state == "leased"


def test_provider_exception_quarantines_run(tmp_path: Path) -> None:
    provider = _Provider(fail_provide=True)
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())

        with pytest.raises(BackendConflict, match="failed while connecting"):
            runtime.application.instruments.provision_run(
                run_id,
                RunInstrumentProvisionCommand(
                    lease_id=lease_id,
                    operation_id="provide",
                ),
            )

        assert (
            runtime.application.executor._control.get_run(run_id).state
            == "attention_required"
        )
        _assert_run_state_discarded(runtime.application.instruments, run_id)


def test_slow_provision_rechecks_the_executor_fence(tmp_path: Path) -> None:
    entered = Event()
    release = Event()
    provider = _Provider(
        provide_entered=entered,
        provide_release=release,
    )
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                runtime.application.instruments.provision_run,
                run_id,
                RunInstrumentProvisionCommand(
                    lease_id=lease_id,
                    operation_id="provide",
                ),
            )
            assert entered.wait(timeout=2)
            runtime.application.executor._control.mark_executor_unknown(
                run_id,
                token=lease_id,
                reason="test_fence_lost",
            )
            release.set()
            with pytest.raises(BackendConflict, match="lease is absent"):
                future.result(timeout=3)

        [driver] = provider.drivers
        assert driver.abort_count == 1
        assert driver.close_count == 1
        _assert_run_state_discarded(runtime.application.instruments, run_id)


@pytest.mark.parametrize("action", ["cleanup", "abort", "close"])
def test_lifecycle_failure_does_not_repeat_attempted_action(
    tmp_path: Path,
    action: Literal["cleanup", "abort", "close"],
) -> None:
    provider = _Provider(fail_action=action)
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )

        with pytest.raises(BackendConflict, match="unknown state"):
            instruments.run_lifecycle(
                run_id,
                "source-0",
                RunInstrumentLifecycleCommand(
                    lease_id=lease_id,
                    operation_id=action,
                    action=action,
                ),
            )

        [driver] = provider.drivers
        assert getattr(driver, f"{action}_count") == 1
        assert runtime.application.executor._control.get_run(run_id).state == (
            "attention_required"
        )
        _assert_run_state_discarded(instruments, run_id)


def test_failed_read_audit_is_observational(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )
        original = InstrumentService._record_run_operation_event

        def fail_finished(
            self: InstrumentService,
            selected_run_id: str,
            *,
            token: str,
            instrument_id: str | None,
            operation_id: str,
            event_kind: str,
            status: str | None,
        ) -> None:
            if event_kind == "run_instrument_read_finished":
                raise BackendConflict("audit unavailable")
            original(
                self,
                selected_run_id,
                token=token,
                instrument_id=instrument_id,
                operation_id=operation_id,
                event_kind=event_kind,
                status=status,
            )

        monkeypatch.setattr(
            InstrumentService,
            "_record_run_operation_event",
            fail_finished,
        )

        with pytest.raises(BackendConflict, match="audit unavailable"):
            instruments.read_run_state(
                run_id,
                "source-0",
                RunInstrumentReadCommand(
                    lease_id=lease_id,
                    operation_id="read",
                ),
            )

        [driver] = provider.drivers
        assert driver.read_count == 1
        assert driver.abort_count == 0
        assert driver.close_count == 0
        assert runtime.application.executor._control.get_run(run_id).state == "leased"


def test_disjoint_runs_do_not_serialize_driver_io(tmp_path: Path) -> None:
    config = _two_instrument_config()
    provider = _Provider(apply_barrier=Barrier(2))
    with _runtime(tmp_path, provider, config=config) as runtime:
        first = _start_run(
            runtime,
            config,
            host_instrument_order=("source-0",),
            submission_id="first",
        )
        second = _start_run(
            runtime,
            config,
            host_instrument_order=("source-1",),
            submission_id="second",
        )
        for run_id, lease_id in (first, second):
            runtime.application.instruments.provision_run(
                run_id,
                RunInstrumentProvisionCommand(
                    lease_id=lease_id,
                    operation_id="provide",
                ),
            )

        def apply(run: tuple[str, str], instrument_id: str) -> None:
            run_id, lease_id = run
            runtime.application.instruments.apply_run_state(
                run_id,
                instrument_id,
                RunInstrumentApplyCommand(
                    lease_id=lease_id,
                    operation_id="apply",
                    command=_apply_command(instrument_id, operation_id="apply"),
                ),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = (
                pool.submit(apply, first, "source-0"),
                pool.submit(apply, second, "source-1"),
            )
            for future in futures:
                future.result(timeout=3)


def test_terminal_finalizes_once_and_closed_retry_replays(tmp_path: Path) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        runtime.application.instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )
        command = TerminalRunCommitCommand(
            lease_id=lease_id,
            outcome=RunOutcome(
                run_id=run_id,
                result="succeeded",
                certainty="known",
                finished_at=datetime.now(tz=UTC),
            ),
        )

        first = runtime.application.executor.commit_terminal(run_id, command)
        retry = runtime.application.executor.commit_terminal(run_id, command)

        assert retry == first
        [driver] = provider.drivers
        assert driver.abort_count == 1
        assert driver.close_count == 1
        assert runtime.application.executor._control.get_run(run_id).state == "closed"


def test_failed_terminal_finalization_quarantines_and_discards_state(
    tmp_path: Path,
) -> None:
    provider = _Provider(fail_action="close")
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )

        with pytest.raises(BackendConflict, match="could not be released"):
            runtime.application.executor.commit_terminal(
                run_id,
                TerminalRunCommitCommand(
                    lease_id=lease_id,
                    outcome=RunOutcome(
                        run_id=run_id,
                        result="succeeded",
                        certainty="known",
                    ),
                ),
            )

        [driver] = provider.drivers
        assert driver.abort_count == 1
        assert driver.close_count == 1
        assert runtime.application.executor._control.get_run(run_id).state == (
            "attention_required"
        )
        _assert_run_state_discarded(instruments, run_id)


def test_expiry_and_shutdown_release_live_run_drivers(tmp_path: Path) -> None:
    provider = _Provider()
    runtime = _runtime(tmp_path, provider)
    run_id, lease_id = _start_run(runtime, load_config())
    runtime.application.instruments.provision_run(
        run_id,
        RunInstrumentProvisionCommand(
            lease_id=lease_id,
            operation_id="provide",
        ),
    )
    lease = runtime.application.executor._control.validate_executor_lease(
        run_id,
        token=lease_id,
    )
    expired = runtime.application.executor._control.expire_executor_leases(
        at=lease.expires_at,
    )
    runtime.application.instruments.expire_runs(expired)
    [driver] = provider.drivers
    assert driver.abort_count == 1
    assert driver.close_count == 1
    runtime.close()

    shutdown_provider = _Provider()
    shutdown = _runtime(tmp_path / "shutdown", shutdown_provider)
    shutdown_run, shutdown_lease = _start_run(shutdown, load_config())
    shutdown.application.instruments.provision_run(
        shutdown_run,
        RunInstrumentProvisionCommand(
            lease_id=shutdown_lease,
            operation_id="provide",
        ),
    )
    shutdown.close()
    [shutdown_driver] = shutdown_provider.drivers
    assert shutdown_driver.abort_count == 1
    assert shutdown_driver.close_count == 1


def test_direct_slow_provision_rechecks_the_session_fence(tmp_path: Path) -> None:
    entered = Event()
    release = Event()
    provider = _Provider(
        provide_entered=entered,
        provide_release=release,
    )
    with _runtime(tmp_path, provider) as runtime:
        instruments = runtime.application.instruments
        command = InstrumentSessionOpenCommand(
            operation_id="open",
            actor="alice",
            instrument_ids=("source-0",),
        )

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(instruments.open_session, command)
            assert entered.wait(timeout=2)
            [session] = instruments._control.list_instrument_sessions()
            assert instruments._control.expire_instrument_sessions(
                at=session.expires_at
            ) == (session.session_id,)
            release.set()
            with pytest.raises(BackendConflict, match="expired while connecting"):
                future.result(timeout=3)

        [driver] = provider.drivers
        assert driver.abort_count == 1
        assert driver.close_count == 1
        assert instruments._control.get_instrument_session(
            session.session_id
        ).state == ("attention_required")
        instruments.resolve_attention(session.session_id)


def test_attention_resolution_waits_for_run_driver_cleanup(tmp_path: Path) -> None:
    abort_entered = Event()
    abort_release = Event()
    provider = _Provider(
        abort_entered=abort_entered,
        abort_release=abort_release,
    )
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )
        lease = instruments._control.validate_executor_lease(
            run_id,
            token=lease_id,
        )
        expired = instruments._control.expire_executor_leases(at=lease.expires_at)
        resolution_entered = Event()

        def resolve_attention() -> None:
            resolution_entered.set()
            runtime.application.resolve_attention(run_id)

        with ThreadPoolExecutor(max_workers=2) as pool:
            cleanup = pool.submit(instruments.expire_runs, expired)
            assert abort_entered.wait(timeout=2)
            resolution = pool.submit(resolve_attention)
            assert resolution_entered.wait(timeout=2)
            assert not resolution.done()
            abort_release.set()
            cleanup.result(timeout=3)
            resolution.result(timeout=3)

        [driver] = provider.drivers
        assert driver.abort_count == 1
        assert driver.close_count == 1
        assert instruments._control.get_run(run_id).state == "closed"


def test_direct_end_receipt_ledger_is_bounded(tmp_path: Path) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        instruments = runtime.application.instruments
        instruments._ended_session_limit = 2
        ended: list[tuple[str, InstrumentSessionEndCommand]] = []
        for index in range(3):
            lease = instruments.open_session(
                InstrumentSessionOpenCommand(
                    operation_id=f"open-{index}",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            command = InstrumentSessionEndCommand(
                lease_id=lease.lease_id,
                operation_id=f"close-{index}",
            )
            instruments.close_session(lease.session_id, command)
            ended.append((lease.session_id, command))

        assert tuple(instruments._ended_sessions) == tuple(
            session_id for session_id, _command in ended[1:]
        )
        last_session_id, last_command = ended[-1]
        assert (
            instruments.close_session(last_session_id, last_command).operation_id
            == last_command.operation_id
        )
        first_session_id, first_command = ended[0]
        with pytest.raises(BackendConflict, match="lease is absent"):
            instruments.close_session(first_session_id, first_command)


def test_run_without_instrument_claims_does_not_build_provider(
    tmp_path: Path,
) -> None:
    build_count = 0

    def factory(_root: Path) -> LabApplication:
        def build(_config: ConfigProfileSnapshot) -> ExperimentSystem:
            nonlocal build_count
            build_count += 1
            raise AssertionError("provider must not be built")

        return LabApplication(build_system=build)

    with LocalDaemonRuntime(
        tmp_path,
        bootstrap_config=load_config(),
        application_factory=factory,
    ) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            load_config(),
            host_instrument_order=(),
        )
        receipt = runtime.application.instruments.provision_run(
            run_id,
            RunInstrumentProvisionCommand(
                lease_id=lease_id,
                operation_id="provide",
            ),
        )

        assert receipt.status == "ready"
        assert receipt.instrument_ids == ()
        assert build_count == 0


def _runtime(
    root: Path,
    provider: _Provider,
    *,
    config: ConfigProfileSnapshot | None = None,
    lease_ttl: timedelta | None = None,
) -> LocalDaemonRuntime:
    def factory(_root: Path) -> LabApplication:
        return LabApplication(
            build_system=lambda _config: ExperimentSystem(provider=provider)
        )

    return LocalDaemonRuntime(
        root,
        bootstrap_config=config if config is not None else load_config(),
        application_factory=factory,
        lease_ttl=lease_ttl,
    )


def _assert_run_state_discarded(
    instruments: InstrumentService,
    run_id: str,
) -> None:
    assert run_id not in instruments._run_runtimes
    assert run_id not in instruments._run_provisions
    assert run_id not in instruments._run_open_locks
    assert run_id not in instruments._finalizing_runs


def _daemon_client_with_lost_responses(
    transport: TestClient,
    *,
    suffixes: tuple[str, ...],
) -> DaemonClient:
    dropped: set[str] = set()

    def send(request: httpx2.Request) -> httpx2.Response:
        response = transport.request(
            request.method,
            request.url.raw_path.decode(),
            content=request.content,
            headers=dict(request.headers),
        )
        translated = httpx2.Response(
            response.status_code,
            content=response.content,
            headers=dict(response.headers),
        )
        suffix = next(
            (
                candidate
                for candidate in suffixes
                if request.url.path.endswith(candidate)
            ),
            None,
        )
        if suffix is not None and suffix not in dropped:
            dropped.add(suffix)
            raise httpx2.ReadError("response was lost", request=request)
        return translated

    return DaemonClient(
        "http://testserver",
        transport=httpx2.MockTransport(send),
    )


def _start_run(
    runtime: LocalDaemonRuntime,
    config: ConfigProfileSnapshot,
    *,
    host_instrument_order: tuple[str, ...] = ("source-0",),
    submission_id: str = "run-instruments",
) -> tuple[str, str]:
    admission = runtime.application.submit_run(
        RunSubmission(
            submission_id=submission_id,
            config=config,
            request=RunRequest(experiment_id="scratch"),
            plan=RunPlanSummary(
                experiment_id="scratch",
                experiment_kind="scratch",
                point_count=1,
                host_instrument_order=host_instrument_order,
                run_resource_claims=tuple(
                    ResourceKey(kind="instrument", id=instrument_id)
                    for instrument_id in host_instrument_order
                ),
            ),
        )
    )
    lease = runtime.application.executor.start_executor(
        admission.run_id,
        ExecutorStartRequest(executor_id=f"executor-{submission_id}"),
    )
    return admission.run_id, lease.lease_id


def _apply_command(
    instrument_id: str,
    *,
    operation_id: str,
) -> InstrumentStateCommand:
    return InstrumentStateCommand(
        operation_id=operation_id,
        instrument_id=instrument_id,
        fields=[
            InstrumentStateCommandField(
                resource_id=instrument_id,
                capability_id="set_frequency",
                field_path="frequency",
                value=StateValue(Quantity(value=5.0, unit="GHz")),
            )
        ],
    )


def _collect_command(
    instrument_id: str,
    *,
    operation_id: str,
) -> CollectCommand:
    return CollectCommand(
        operation_id=operation_id,
        instrument_id=instrument_id,
        point_index=0,
        point_count=1,
        requests=[
            CollectProductRequest(
                id="signal",
                capability_id="scalar_signal",
            )
        ],
    )


def _two_instrument_config() -> ConfigProfileSnapshot:
    config = load_config()
    [source] = config.instrument_registry.instruments
    registry = config.instrument_registry.model_copy(
        update={
            "instruments": [
                source,
                source.model_copy(update={"id": "source-1"}),
            ]
        }
    )
    return config.model_copy(
        update={
            "system": config.system.model_copy(update={"instrument_registry": registry})
        }
    )
