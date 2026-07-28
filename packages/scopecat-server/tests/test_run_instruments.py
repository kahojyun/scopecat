from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier
from typing import Literal, override

import pytest
from scopecat.application import LabApplication
from scopecat.control.models import ResourceKey, RunPlanSummary
from scopecat.daemon.wire import (
    ExecutorStartRequest,
    RunHardwareBatchCommand,
    RunHardwareFinishCommand,
    RunInstrumentProvisionCommand,
    RunSubmission,
    TerminalRunCommitCommand,
)
from scopecat.execution.ports.instruments import (
    RunHardwareApply,
    RunHardwareBatch,
    RunHardwareCollect,
    RunHardwareCollectBinding,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.kernel.state import StateValue
from scopecat.planning.provider_validation import instrument_contract_fingerprint
from scopecat.planning.system import ExperimentSystem
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments import (
    CollectProductRequest,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateCommand,
    InstrumentStateCommandField,
)
from tests.testkit.instrument_drivers import SignalInstrumentDriver, load_config

from scopecat_server import LocalDaemonRuntime
from scopecat_server.errors import BackendConflict
from scopecat_server.instrument_service import InstrumentService


class _Driver(SignalInstrumentDriver):
    def __init__(
        self,
        instrument_id: str,
        *,
        fail_action: Literal["apply", "cleanup", "abort", "close"] | None = None,
        apply_barrier: Barrier | None = None,
    ) -> None:
        super().__init__(instrument_id=instrument_id)
        self.fail_action = fail_action
        self.apply_barrier = apply_barrier
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
        if self.fail_action == "apply":
            raise RuntimeError("apply outcome lost")
        return super().apply_state(command)

    @override
    def cleanup(self) -> None:
        self.cleanup_count += 1
        if self.fail_action == "cleanup":
            raise RuntimeError("cleanup failed")

    @override
    def abort(self) -> None:
        self.abort_count += 1
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
        fail_action: Literal["apply", "cleanup", "abort", "close"] | None = None,
        apply_barrier: Barrier | None = None,
    ) -> None:
        self.fail_action: Literal["apply", "cleanup", "abort", "close"] | None = (
            fail_action
        )
        self.apply_barrier = apply_barrier
        self.provide_count = 0
        self.drivers: list[_Driver] = []

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        selected = set(context.instrument_ids)
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(
                _Driver(item.id).describe()
                for item in context.config.instrument_registry.instruments
                if item.id in selected
            ),
        )

    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        self.provide_count += 1
        drivers = tuple(
            _Driver(
                instrument_id,
                fail_action=self.fail_action,
                apply_barrier=self.apply_barrier,
            )
            for instrument_id in context.instrument_ids
        )
        self.drivers.extend(drivers)
        return InstrumentProviderResult(drivers=drivers)


def test_batch_reconciles_state_collects_values_and_replays_once(
    tmp_path: Path,
) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        provision = instruments.provision_run(run_id, _provision(lease_id))
        assert provision.initial_state[0].instrument_id == "source-0"
        [driver] = provider.drivers

        command = _batch_command(
            lease_id,
            "batch-1",
            _apply_action("source-0", effect_id="apply-1"),
            _collect_action("source-0", effect_id="collect-1"),
        )
        receipt = instruments.execute_run_hardware(run_id, command)
        assert instruments.execute_run_hardware(run_id, command) == receipt
        assert [(value.product_use_id, value.value) for value in receipt.values] == [
            ("signal-use", Quantity(value=1.0, unit="ratio"))
        ]
        assert len(driver.applied) == 1
        assert len(driver.collect_commands) == 1

        unchanged = _batch_command(
            lease_id,
            "batch-2",
            _apply_action("source-0", effect_id="apply-2"),
        )
        assert not instruments.execute_run_hardware(run_id, unchanged).problems
        assert len(driver.applied) == 1
        batch_events = [
            event
            for event in runtime.application.runs.list_events(
                limit=100,
                after=None,
                run_id=run_id,
            ).items
            if event.kind.startswith("run_hardware_batch_")
        ]
        assert [event.kind for event in batch_events] == [
            "run_hardware_batch_started",
            "run_hardware_batch_finished",
            "run_hardware_batch_started",
            "run_hardware_batch_finished",
        ]
        assert batch_events[0].payload["batch"] == command.batch.model_dump(mode="json")
        assert batch_events[1].payload["completed_effect_ids"] == [
            "apply-1",
            "collect-1",
        ]
        assert batch_events[1].payload["effect_receipts"] == [
            {"effect_id": "apply-1", "status": "applied", "metadata": {}},
            {
                "effect_id": "collect-1",
                "status": "collected",
                "metadata": {},
                "readback_metadata": {
                    "implementation": "tests.signal_driver",
                },
            },
        ]


def test_provision_rejects_contract_changed_after_admission(tmp_path: Path) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            load_config(),
            contract_fingerprint="0" * 64,
        )

        receipt = runtime.application.instruments.provision_run(
            run_id,
            _provision(lease_id),
        )

        assert receipt.status == "rejected"
        assert [item.code for item in receipt.problems] == [
            "instrument_contract_changed_after_admission"
        ]
        assert provider.provide_count == 0


def test_batch_id_rejects_different_content(tmp_path: Path) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(run_id, _provision(lease_id))
        first = _batch_command(
            lease_id,
            "batch-1",
            _apply_action("source-0", effect_id="apply-1"),
        )
        instruments.execute_run_hardware(run_id, first)

        changed = _batch_command(
            lease_id,
            "batch-1",
            _collect_action("source-0", effect_id="collect-1"),
        )
        with pytest.raises(BackendConflict, match="different operation content"):
            instruments.execute_run_hardware(run_id, changed)


def test_unknown_driver_action_quarantines_and_discards_run_state(
    tmp_path: Path,
) -> None:
    provider = _Provider(fail_action="apply")
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(run_id, _provision(lease_id))

        with pytest.raises(BackendConflict, match="unknown state"):
            instruments.execute_run_hardware(
                run_id,
                _batch_command(
                    lease_id,
                    "batch-1",
                    _apply_action("source-0", effect_id="apply-1"),
                ),
            )

        [driver] = provider.drivers
        assert driver.abort_count == 1
        assert driver.close_count == 1
        assert runtime.application.executor._control.get_run(run_id).state == (
            "attention_required"
        )
        _assert_run_state_discarded(instruments, run_id)


def test_finish_owns_cleanup_terminal_read_close_and_replay(tmp_path: Path) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(run_id, _provision(lease_id))
        [driver] = provider.drivers
        command = RunHardwareFinishCommand(
            lease_id=lease_id,
            operation_id="hardware.finish",
            failed=False,
        )

        receipt = instruments.finish_run_hardware(run_id, command)
        assert instruments.finish_run_hardware(run_id, command) == receipt
        assert receipt.final_state[0].instrument_id == "source-0"
        assert driver.cleanup_count == 1
        assert driver.abort_count == 0
        assert driver.close_count == 1
        assert driver.read_count == 2
        _assert_run_state_discarded(instruments, run_id)


def test_failed_finish_aborts_and_close_failure_is_unknown(tmp_path: Path) -> None:
    provider = _Provider(fail_action="close")
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(run_id, _provision(lease_id))

        with pytest.raises(BackendConflict, match="close failed with unknown state"):
            instruments.finish_run_hardware(
                run_id,
                RunHardwareFinishCommand(
                    lease_id=lease_id,
                    operation_id="hardware.finish",
                    failed=True,
                ),
            )

        [driver] = provider.drivers
        assert driver.abort_count == 1
        assert driver.close_count == 1
        _assert_run_state_discarded(instruments, run_id)


def test_terminal_commit_uses_the_same_abort_finalizer_as_explicit_finish(
    tmp_path: Path,
) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        runtime.application.instruments.provision_run(run_id, _provision(lease_id))

        manifest = runtime.application.executor.commit_terminal(
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
        assert manifest.outcome is not None
        assert driver.abort_count == 1
        assert driver.cleanup_count == 0
        assert driver.read_count == 2
        assert driver.close_count == 1


def test_disjoint_runs_do_not_serialize_hardware_batches(tmp_path: Path) -> None:
    provider = _Provider(apply_barrier=Barrier(2))
    config = _two_instrument_config()
    with _runtime(tmp_path, provider) as runtime:
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
        instruments = runtime.application.instruments
        for run_id, lease_id in (first, second):
            instruments.provision_run(run_id, _provision(lease_id))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    instruments.execute_run_hardware,
                    run_id,
                    _batch_command(
                        lease_id,
                        f"batch-{index}",
                        _apply_action(
                            f"source-{index}",
                            effect_id=f"apply-{index}",
                        ),
                    ),
                )
                for index, (run_id, lease_id) in enumerate((first, second))
            ]
            assert all(not future.result(timeout=3).problems for future in futures)


def test_expiry_and_shutdown_release_live_run_drivers(tmp_path: Path) -> None:
    provider = _Provider()
    runtime = _runtime(tmp_path, provider)
    run_id, lease_id = _start_run(runtime, load_config())
    runtime.application.instruments.provision_run(run_id, _provision(lease_id))
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
        _provision(shutdown_lease),
    )
    shutdown.close()
    [shutdown_driver] = shutdown_provider.drivers
    assert shutdown_driver.abort_count == 1
    assert shutdown_driver.close_count == 1


def test_run_without_claims_does_not_build_provider(tmp_path: Path) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            load_config(),
            host_instrument_order=(),
        )
        receipt = runtime.application.instruments.provision_run(
            run_id,
            _provision(lease_id),
        )
        assert receipt.status == "ready"
        assert receipt.initial_state == ()
        assert provider.provide_count == 0


def _runtime(
    root: Path,
    provider: _Provider,
    *,
    lease_ttl: timedelta | None = None,
) -> LocalDaemonRuntime:
    def factory(_root: Path) -> LabApplication:
        return LabApplication(
            build_system=lambda _config: ExperimentSystem(provider=provider)
        )

    return LocalDaemonRuntime(
        root,
        bootstrap_config=load_config(),
        application_factory=factory,
        lease_ttl=lease_ttl,
    )


def _start_run(
    runtime: LocalDaemonRuntime,
    config: ConfigProfileSnapshot,
    *,
    host_instrument_order: tuple[str, ...] = ("source-0",),
    submission_id: str = "run-instruments",
    contract_fingerprint: str | None = None,
) -> tuple[str, str]:
    admitted_fingerprint = (
        instrument_contract_fingerprint(
            _Provider.provider_id,
            tuple(
                _Driver(instrument_id).describe()
                for instrument_id in host_instrument_order
            ),
        )
        if host_instrument_order
        else None
    )
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
                host_provider_id=(
                    _Provider.provider_id if host_instrument_order else None
                ),
                host_contract_fingerprint=(
                    contract_fingerprint or admitted_fingerprint
                ),
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


def _provision(lease_id: str) -> RunInstrumentProvisionCommand:
    return RunInstrumentProvisionCommand(
        lease_id=lease_id,
        operation_id="hardware.provision",
    )


def _batch_command(
    lease_id: str,
    operation_id: str,
    *actions: RunHardwareApply | RunHardwareCollect,
) -> RunHardwareBatchCommand:
    return RunHardwareBatchCommand(
        lease_id=lease_id,
        batch=RunHardwareBatch(
            operation_id=operation_id,
            actions=actions,
        ),
    )


def _apply_action(
    instrument_id: str,
    *,
    effect_id: str,
) -> RunHardwareApply:
    return RunHardwareApply(
        effect_id=effect_id,
        point_index=0,
        instrument_id=instrument_id,
        fields=(
            InstrumentStateCommandField(
                resource_id=instrument_id,
                capability_id="set_frequency",
                field_path="frequency",
                value=StateValue(Quantity(value=5.0, unit="GHz")),
            ),
        ),
    )


def _collect_action(
    instrument_id: str,
    *,
    effect_id: str,
) -> RunHardwareCollect:
    return RunHardwareCollect(
        effect_id=effect_id,
        point_index=0,
        instrument_id=instrument_id,
        point_count=1,
        requests=(
            CollectProductRequest(
                id="signal",
                capability_id="scalar_signal",
            ),
        ),
        bindings=(
            RunHardwareCollectBinding(
                provider_key="signal",
                product_use_ids=("signal-use",),
            ),
        ),
    )


def _assert_run_state_discarded(
    instruments: InstrumentService,
    run_id: str,
) -> None:
    assert run_id not in instruments._run_runtimes
    assert run_id not in instruments._run_provisions
    assert run_id not in instruments._run_open_locks
    assert run_id not in instruments._finalizing_runs


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
