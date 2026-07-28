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
    RunHardwareInvoke,
)
from scopecat.kernel.problems import ProblemPhase, problem
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.planning.provider_validation import instrument_contract_fingerprint
from scopecat.planning.system import ExperimentSystem
from scopecat.records.artifact import CommandPayload, command_payload_from_bytes
from scopecat.records.config import (
    ApplyDefaultsRunPreparation,
    ConfigProfileSnapshot,
    config_content_hash,
)
from scopecat.records.run import (
    AnalysisCandidateRunConfigSource,
    ConfigRegistryRunConfigSource,
    RunConfigSource,
)
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectResultRequest,
    InstrumentDescription,
    InstrumentOperationArgument,
    InstrumentPropertyState,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InstrumentStateSnapshot,
    InvokeCommand,
    InvokeReceipt,
    bool_property,
    discriminated_state,
    enum_property,
    float_property,
    interface,
    operation,
    state_case,
)
from tests.testkit.instrument_drivers import SignalInstrumentDriver, load_config
from tests.testkit.payload_codecs import json_payload_codecs

from scopecat_server import LocalDaemonRuntime
from scopecat_server.errors import BackendConflict
from scopecat_server.instrument_service import InstrumentService

type _FailAction = (
    Literal["apply", "reject_apply", "invoke", "abort", "disconnect"] | None
)


class _Driver(SignalInstrumentDriver):
    def __init__(
        self,
        instrument_id: str,
        *,
        fail_action: _FailAction = None,
        apply_barrier: Barrier | None = None,
    ) -> None:
        super().__init__(instrument_id=instrument_id)
        self.fail_action: _FailAction = fail_action
        self.apply_barrier = apply_barrier
        self.read_count = 0
        self.abort_count = 0
        self.disconnect_count = 0

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
        if self.fail_action == "reject_apply":
            return ApplyReceipt(
                status="not_applied",
                problems=(
                    problem(
                        "test_apply_rejected",
                        "test driver rejected state",
                        phase=ProblemPhase.EXECUTION,
                    ),
                ),
            )
        return super().apply_state(command)

    @override
    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        self.invoked.append(command)
        if self.fail_action == "invoke":
            raise RuntimeError("invoke outcome lost")
        return InvokeReceipt(status="invoked")

    @override
    def abort(self) -> None:
        self.abort_count += 1
        if self.fail_action == "abort":
            raise RuntimeError("abort failed")

    @override
    def disconnect(self) -> None:
        self.disconnect_count += 1
        if self.fail_action == "disconnect":
            raise RuntimeError("disconnect failed")


class _VariantDriver(_Driver):
    def __init__(
        self,
        instrument_id: str,
        *,
        fail_action: _FailAction = None,
        apply_barrier: Barrier | None = None,
    ) -> None:
        super().__init__(
            instrument_id,
            fail_action=fail_action,
            apply_barrier=apply_barrier,
        )
        self.mode = "voltage"
        self.voltage_level = 0.1
        self.current_level = 0.01

    @override
    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            interfaces=[
                interface(
                    "test.dc/v1",
                    properties=[
                        enum_property("mode", choices=("voltage", "current")),
                        float_property("voltage_level"),
                        float_property("current_level"),
                        bool_property("output_enabled"),
                    ],
                    state=discriminated_state(
                        "mode",
                        common_property_ids=("output_enabled",),
                        cases=(
                            state_case(
                                "voltage",
                                property_ids=("voltage_level",),
                            ),
                            state_case(
                                "current",
                                property_ids=("current_level",),
                            ),
                        ),
                    ),
                    operations=[operation("select_current")],
                )
            ],
        )

    @override
    def read_state(self) -> InstrumentStateSnapshot:
        self.read_count += 1
        level_property = "voltage_level" if self.mode == "voltage" else "current_level"
        level = self.voltage_level if self.mode == "voltage" else self.current_level
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=[
                InstrumentPropertyState(
                    interface_id="test.dc/v1",
                    property_id="mode",
                    value=StateValue(self.mode),
                ),
                InstrumentPropertyState(
                    interface_id="test.dc/v1",
                    property_id=level_property,
                    value=StateValue(level),
                ),
                InstrumentPropertyState(
                    interface_id="test.dc/v1",
                    property_id="output_enabled",
                    value=StateValue(False),
                ),
            ],
        )

    @override
    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        self.applied.append(command)
        for assignment in command.assignments:
            if assignment.property_id == "mode":
                assert isinstance(assignment.value.root, str)
                self.mode = assignment.value.root
            elif assignment.property_id == "voltage_level":
                assert isinstance(assignment.value.root, float)
                self.voltage_level = assignment.value.root
            elif assignment.property_id == "current_level":
                assert isinstance(assignment.value.root, float)
                self.current_level = assignment.value.root
        return ApplyReceipt(status="applied")

    @override
    def invoke(self, command: InvokeCommand) -> InvokeReceipt:
        self.invoked.append(command)
        self.mode = "current"
        return InvokeReceipt(status="invoked")


class _NonConvergingDriver(_Driver):
    @override
    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        self.applied.append(command)
        return ApplyReceipt(status="applied")


class _EquivalentQuantityDriver(_Driver):
    def __init__(
        self,
        instrument_id: str,
        *,
        fail_action: _FailAction = None,
        apply_barrier: Barrier | None = None,
    ) -> None:
        super().__init__(
            instrument_id,
            fail_action=fail_action,
            apply_barrier=apply_barrier,
        )
        self._state[("test.set_frequency/v1", "frequency")] = StateValue(
            Quantity(value=1.0, unit="GHz")
        )


class _Provider:
    provider_id = "tests.run_provider"

    def __init__(
        self,
        *,
        fail_action: _FailAction = None,
        apply_barrier: Barrier | None = None,
        driver_type: type[_Driver] = _Driver,
    ) -> None:
        self.fail_action: _FailAction = fail_action
        self.apply_barrier = apply_barrier
        self.driver_type = driver_type
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
                self.driver_type(item.id).describe()
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
            self.driver_type(
                instrument_id,
                fail_action=self.fail_action,
                apply_barrier=self.apply_barrier,
            )
            for instrument_id in context.instrument_ids
        )
        self.drivers.extend(drivers)
        return InstrumentProviderResult(drivers=drivers)


class _SecondRejectingProvider(_Provider):
    @override
    def provide(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderResult:
        self.provide_count += 1
        drivers = tuple(
            _Driver(
                instrument_id,
                fail_action=("reject_apply" if instrument_id == "source-1" else None),
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
        assert provision.observed_state[0].instrument_id == "source-0"
        assert provision.prepared_state[0].instrument_id == "source-0"
        assert provision.prepared_state == provision.observed_state
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


def test_run_preparation_applies_defaults_after_fresh_observation(
    tmp_path: Path,
) -> None:
    provider = _Provider()
    config = _config_with_defaults(
        InstrumentPropertyState(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=StateValue(Quantity(value=5.0, unit="GHz")),
        )
    )
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, config)
        instruments = runtime.application.instruments

        provision = instruments.provision_run(run_id, _provision(lease_id))
        replay = instruments.provision_run(run_id, _provision(lease_id))

        assert replay == provision
        [observed] = provision.observed_state
        [prepared] = provision.prepared_state
        assert observed.properties == []
        assert {item.property_id: item.value.root for item in prepared.properties} == {
            "frequency": Quantity(value=5.0, unit="GHz")
        }
        [driver] = provider.drivers
        assert len(driver.applied) == 1
        assert driver.applied[0].command_id == "hardware.provision.prepare.source-0"


def test_unknown_run_preparation_quarantines_the_run(tmp_path: Path) -> None:
    provider = _Provider(fail_action="apply")
    config = _config_with_defaults(
        InstrumentPropertyState(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=StateValue(Quantity(value=5.0, unit="GHz")),
        )
    )
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, config)

        with pytest.raises(BackendConflict, match="preparation failed with unknown"):
            runtime.application.instruments.provision_run(
                run_id,
                _provision(lease_id),
            )

        [driver] = provider.drivers
        assert driver.abort_count == 1
        assert driver.disconnect_count == 1
        assert runtime.application.executor._control.get_run(run_id).state == (
            "attention_required"
        )
        _assert_run_state_discarded(runtime.application.instruments, run_id)


def test_run_preparation_requires_defaults_to_converge(tmp_path: Path) -> None:
    provider = _Provider(driver_type=_NonConvergingDriver)
    config = _config_with_defaults(
        InstrumentPropertyState(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=StateValue(Quantity(value=5.0, unit="GHz")),
        )
    )
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            config,
            driver_type=_NonConvergingDriver,
        )

        with pytest.raises(BackendConflict, match="preparation failed with unknown"):
            runtime.application.instruments.provision_run(
                run_id,
                _provision(lease_id),
            )

        [driver] = provider.drivers
        assert len(driver.applied) == 1
        assert driver.abort_count == 1
        assert driver.disconnect_count == 1
        assert runtime.application.executor._control.get_run(run_id).state == (
            "attention_required"
        )


def test_rejected_run_preparation_closes_without_quarantine(tmp_path: Path) -> None:
    provider = _Provider(fail_action="reject_apply")
    config = _config_with_defaults(
        InstrumentPropertyState(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=StateValue(Quantity(value=5.0, unit="GHz")),
        )
    )
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, config)
        instruments = runtime.application.instruments

        receipt = instruments.provision_run(run_id, _provision(lease_id))

        assert receipt.status == "rejected"
        assert [item.code for item in receipt.problems] == ["test_apply_rejected"]
        [driver] = provider.drivers
        assert driver.abort_count == 0
        assert driver.disconnect_count == 1
        assert runtime.application.executor._control.get_run(run_id).state != (
            "attention_required"
        )
        assert run_id not in instruments._run_runtimes


def test_partial_run_preparation_is_unknown(tmp_path: Path) -> None:
    provider = _SecondRejectingProvider()
    config = _two_instrument_config_with_defaults(
        InstrumentPropertyState(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=StateValue(Quantity(value=5.0, unit="GHz")),
        )
    )
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            config,
            host_instrument_order=("source-0", "source-1"),
        )

        with pytest.raises(BackendConflict, match="partially changed hardware"):
            runtime.application.instruments.provision_run(
                run_id,
                _provision(lease_id),
            )

        first, second = provider.drivers
        assert len(first.applied) == 1
        assert second.applied == []
        assert [driver.abort_count for driver in provider.drivers] == [1, 1]
        assert [driver.disconnect_count for driver in provider.drivers] == [1, 1]
        assert runtime.application.executor._control.get_run(run_id).state == (
            "attention_required"
        )


def test_run_preparation_skips_defaults_matching_observed_state(
    tmp_path: Path,
) -> None:
    provider = _Provider(driver_type=_VariantDriver)
    config = _config_with_defaults(
        InstrumentPropertyState(
            interface_id="test.dc/v1",
            property_id="mode",
            value=StateValue("voltage"),
        ),
        InstrumentPropertyState(
            interface_id="test.dc/v1",
            property_id="voltage_level",
            value=StateValue(0.1),
        ),
        InstrumentPropertyState(
            interface_id="test.dc/v1",
            property_id="output_enabled",
            value=StateValue(False),
        ),
    )
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            config,
            driver_type=_VariantDriver,
        )

        receipt = runtime.application.instruments.provision_run(
            run_id,
            _provision(lease_id),
        )

        assert receipt.status == "ready"
        assert receipt.prepared_state == receipt.observed_state
        [driver] = provider.drivers
        assert driver.applied == []


def test_run_preparation_skips_unit_equivalent_defaults(tmp_path: Path) -> None:
    provider = _Provider(driver_type=_EquivalentQuantityDriver)
    config = _config_with_defaults(
        InstrumentPropertyState(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=StateValue(Quantity(value=1000.0, unit="MHz")),
        )
    )
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            config,
            driver_type=_EquivalentQuantityDriver,
        )

        receipt = runtime.application.instruments.provision_run(
            run_id,
            _provision(lease_id),
        )

        assert receipt.prepared_state == receipt.observed_state
        [driver] = provider.drivers
        assert driver.applied == []


def test_batch_retry_replays_before_state_dependent_preflight(tmp_path: Path) -> None:
    provider = _Provider(driver_type=_VariantDriver)
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            load_config(),
            driver_type=_VariantDriver,
        )
        instruments = runtime.application.instruments
        instruments.provision_run(run_id, _provision(lease_id))
        [driver] = provider.drivers
        voltage = _batch_command(
            lease_id,
            "voltage-batch",
            _variant_apply_action(
                effect_id="voltage-level",
                voltage_level=0.2,
            ),
        )

        first = instruments.execute_run_hardware(run_id, voltage)
        switched = instruments.execute_run_hardware(
            run_id,
            _batch_command(
                lease_id,
                "current-batch",
                _variant_apply_action(
                    effect_id="switch-current",
                    mode="current",
                    current_level=0.02,
                ),
            ),
        )
        replay = instruments.execute_run_hardware(run_id, voltage)

        assert not first.problems
        assert not switched.problems
        assert replay == first
        assert len(driver.applied) == 2


def test_invoke_makes_later_case_specific_preflight_require_discriminator(
    tmp_path: Path,
) -> None:
    provider = _Provider(driver_type=_VariantDriver)
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            load_config(),
            driver_type=_VariantDriver,
        )
        instruments = runtime.application.instruments
        instruments.provision_run(run_id, _provision(lease_id))
        [driver] = provider.drivers

        rejected = instruments.execute_run_hardware(
            run_id,
            _batch_command(
                lease_id,
                "implicit-after-invoke",
                _variant_invoke_action(effect_id="select-current"),
                _variant_apply_action(
                    effect_id="implicit-current-level",
                    current_level=0.02,
                ),
            ),
        )

        assert [item.code for item in rejected.problems] == [
            "instrument_driver_state_case_unknown"
        ]
        assert driver.invoked == []
        accepted = instruments.execute_run_hardware(
            run_id,
            _batch_command(
                lease_id,
                "explicit-after-invoke",
                _variant_invoke_action(effect_id="select-current-explicit"),
                _variant_apply_action(
                    effect_id="explicit-current-level",
                    mode="current",
                    current_level=0.02,
                ),
            ),
        )
        assert not accepted.problems
        assert len(driver.invoked) == 1
        assert len(driver.applied) == 1


def test_run_invoke_reads_back_state_before_later_actions(
    tmp_path: Path,
) -> None:
    provider = _Provider()
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(run_id, _provision(lease_id))
        [driver] = provider.drivers
        reads_before_invoke = driver.read_count
        payload = command_payload_from_bytes(
            id="program-1",
            schema_id="pulse_program",
            codec_id="tests.canonical-json",
            codec_version=1,
            media_type="application/json",
            content=b'{"samples":[0.0]}',
        )

        receipt = instruments.execute_run_hardware(
            run_id,
            _batch_command(
                lease_id,
                "invoke-batch",
                _invoke_action(
                    "source-0",
                    effect_id="invoke-1",
                    payload=payload,
                ),
            ),
        )

        assert receipt.problems == ()
        assert len(driver.invoked) == 1
        assert driver.read_count == reads_before_invoke + 1
        assert driver.invoked[0].payloads[payload.id].inline_bytes() == (
            b'{"samples":[0.0]}'
        )


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
        assert driver.disconnect_count == 1
        assert runtime.application.executor._control.get_run(run_id).state == (
            "attention_required"
        )
        _assert_run_state_discarded(instruments, run_id)


def test_unknown_invoke_quarantines_and_discards_run_state(
    tmp_path: Path,
) -> None:
    provider = _Provider(fail_action="invoke")
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(run_id, _provision(lease_id))
        payload = command_payload_from_bytes(
            id="program-1",
            schema_id="pulse_program",
            codec_id="tests.canonical-json",
            codec_version=1,
            media_type="application/json",
            content=b'{"samples":[0.0]}',
        )

        with pytest.raises(BackendConflict, match="unknown state"):
            instruments.execute_run_hardware(
                run_id,
                _batch_command(
                    lease_id,
                    "invoke-unknown",
                    _invoke_action(
                        "source-0",
                        effect_id="invoke-unknown-1",
                        payload=payload,
                    ),
                ),
            )

        [driver] = provider.drivers
        assert len(driver.invoked) == 1
        assert driver.abort_count == 1
        assert driver.disconnect_count == 1
        assert runtime.application.executor._control.get_run(run_id).state == (
            "attention_required"
        )
        _assert_run_state_discarded(instruments, run_id)


def test_finish_reads_terminal_state_releases_and_replays(tmp_path: Path) -> None:
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
        assert driver.abort_count == 0
        assert driver.disconnect_count == 0
        assert driver.read_count == 2
        _assert_run_state_discarded(instruments, run_id)


def test_failed_finish_abort_failure_is_unknown(tmp_path: Path) -> None:
    provider = _Provider(fail_action="abort")
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(runtime, load_config())
        instruments = runtime.application.instruments
        instruments.provision_run(run_id, _provision(lease_id))

        with pytest.raises(BackendConflict, match="abort failed with unknown state"):
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
        assert driver.disconnect_count == 1
        _assert_run_state_discarded(instruments, run_id)


def test_analysis_candidate_run_retires_without_leaking_disconnect_failure(
    tmp_path: Path,
) -> None:
    provider = _Provider(fail_action="disconnect")
    config = load_config()
    source = AnalysisCandidateRunConfigSource(
        source_run_id="source-run",
        analysis_record_id="analysis-candidate",
        proposal_id="proposal-candidate",
        base_config_content_hash=config_content_hash(config),
        content_hash=config_content_hash(config),
    )
    with _runtime(tmp_path, provider) as runtime:
        run_id, lease_id = _start_run(
            runtime,
            config,
            config_source=source,
            submission_id="analysis-candidate",
        )
        instruments = runtime.application.instruments
        instruments.provision_run(run_id, _provision(lease_id))

        receipt = instruments.finish_run_hardware(
            run_id,
            RunHardwareFinishCommand(
                lease_id=lease_id,
                operation_id="hardware.finish",
                failed=False,
            ),
        )

        [driver] = provider.drivers
        assert receipt.final_state[0].instrument_id == "source-0"
        assert driver.disconnect_count == 1
        assert runtime.application.executor._control.get_run(run_id).state != (
            "attention_required"
        )


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
        assert driver.read_count == 2
        assert driver.disconnect_count == 0


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
    assert driver.disconnect_count == 1
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
    assert shutdown_driver.disconnect_count == 1


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
        assert receipt.observed_state == ()
        assert receipt.prepared_state == ()
        assert provider.provide_count == 0


def _config_with_defaults(
    *properties: InstrumentPropertyState,
) -> ConfigProfileSnapshot:
    config = load_config()
    [instrument] = config.instrument_registry.instruments
    prepared = instrument.model_copy(
        update={
            "run_preparation": ApplyDefaultsRunPreparation(properties=list(properties))
        }
    )
    registry = config.instrument_registry.model_copy(update={"instruments": [prepared]})
    return config.model_copy(
        update={
            "system": config.system.model_copy(update={"instrument_registry": registry})
        }
    )


def _two_instrument_config_with_defaults(
    *properties: InstrumentPropertyState,
) -> ConfigProfileSnapshot:
    config = _two_instrument_config()
    instruments = [
        instrument.model_copy(
            update={
                "run_preparation": ApplyDefaultsRunPreparation(
                    properties=[item.model_copy(deep=True) for item in properties]
                )
            }
        )
        for instrument in config.instrument_registry.instruments
    ]
    registry = config.instrument_registry.model_copy(
        update={"instruments": instruments}
    )
    return config.model_copy(
        update={
            "system": config.system.model_copy(update={"instrument_registry": registry})
        }
    )


def _runtime(
    root: Path,
    provider: _Provider,
    *,
    lease_ttl: timedelta | None = None,
) -> LocalDaemonRuntime:
    def factory(_root: Path) -> LabApplication:
        return LabApplication(
            build_system=lambda _config: ExperimentSystem(
                provider=provider,
                payload_codecs=json_payload_codecs("pulse_program"),
            )
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
    driver_type: type[_Driver] = _Driver,
    config_source: RunConfigSource | Literal["matching_active"] | None = (
        "matching_active"
    ),
) -> tuple[str, str]:
    if config_source == "matching_active":
        active = runtime.application.config.get_active_config()
        selected_config_source = (
            ConfigRegistryRunConfigSource(
                selector="active",
                entry_id=active.entry.id,
                config_ref=active.entry.config_ref,
                content_hash=active.entry.content_hash,
                registry_generation=active.activation.generation,
            )
            if active.entry.content_hash == config_content_hash(config)
            else None
        )
    else:
        selected_config_source = config_source
    admitted_fingerprint = (
        instrument_contract_fingerprint(
            _Provider.provider_id,
            tuple(
                driver_type(instrument_id).describe()
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
            config_source=selected_config_source,
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
    *actions: RunHardwareApply | RunHardwareInvoke | RunHardwareCollect,
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
        assignments=(
            InstrumentStateAssignment(
                resource_id=instrument_id,
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=StateValue(Quantity(value=5.0, unit="GHz")),
            ),
        ),
    )


def _variant_apply_action(
    *,
    effect_id: str,
    mode: str | None = None,
    voltage_level: float | None = None,
    current_level: float | None = None,
) -> RunHardwareApply:
    values = {
        "mode": mode,
        "voltage_level": voltage_level,
        "current_level": current_level,
    }
    return RunHardwareApply(
        effect_id=effect_id,
        point_index=0,
        instrument_id="source-0",
        assignments=tuple(
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id="test.dc/v1",
                property_id=property_id,
                value=StateValue(value),
            )
            for property_id, value in values.items()
            if value is not None
        ),
    )


def _variant_invoke_action(*, effect_id: str) -> RunHardwareInvoke:
    return RunHardwareInvoke(
        effect_id=effect_id,
        point_index=0,
        instrument_id="source-0",
        resource_id="source-0",
        interface_id="test.dc/v1",
        operation_id="select_current",
    )


def _invoke_action(
    instrument_id: str,
    *,
    effect_id: str,
    payload: CommandPayload,
) -> RunHardwareInvoke:
    return RunHardwareInvoke(
        effect_id=effect_id,
        point_index=0,
        instrument_id=instrument_id,
        resource_id=instrument_id,
        interface_id="test.play_program/v1",
        operation_id="play",
        arguments=(
            InstrumentOperationArgument(
                id="program",
                value=StateValue(PayloadRef(payload_id=payload.id)),
            ),
        ),
        payloads={payload.id: payload},
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
            CollectResultRequest(
                id="signal",
                interface_id="test.scalar_signal/v1",
                acquisition_id="sample",
                result_id="signal",
            ),
        ),
        bindings=(
            RunHardwareCollectBinding(
                request_id="signal",
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
