from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from threading import Event, Thread
from typing import Never, override

import httpx2
import pytest
from fastapi.testclient import TestClient
from scopecat.api.lab import LabClient
from scopecat.control.models import ResourceKey, RunPlanSummary
from scopecat.daemon.client import DaemonClient, DaemonConflictError
from scopecat.daemon.wire import (
    ConfigPublishCommand,
    DirectConfigRevisionSource,
    ExecutorStartRequest,
    InstrumentSessionOpenCommand,
    RunSubmission,
)
from scopecat.kernel.problems import ProblemPhase, model_location, problem
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.records.artifact import command_payload_from_bytes
from scopecat.records.config import (
    ConfigProfileSnapshot,
    InstrumentBindingSpec,
    TcpipSocketInstrumentConnection,
    VirtualInstrumentConnection,
    config_content_hash,
    instrument_bindings,
)
from scopecat.records.measurement import MeasurementValue
from scopecat.records.run_request import RunRequest
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    CollectResultRequest,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverFault,
    DriverInvokeRequest,
    InstrumentBackend,
    InstrumentConnectionContext,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentPropertyState,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentReadback,
    InstrumentStateAssignment,
    InstrumentStateCommand,
    InstrumentStateSnapshot,
    InterfaceRef,
    InvokeReceipt,
    acquisition_case,
    acquisition_result,
    bool_property,
    discriminated_state,
    enum_property,
    float_property,
    interface,
    state_case,
    state_discriminated_acquisition,
    state_discriminator_ref,
)
from tests.testkit.instrument_drivers import SignalInstrumentDriver, load_config
from tests.testkit.payload_codecs import json_payload_codecs

from scopecat_server import LocalDaemonRuntime
from scopecat_server.errors import BackendConflict
from scopecat_server.instrument_backend import LocalInstrumentBackendEndpoint

_SET_FREQUENCY = InterfaceRef("test.set_frequency/v1").property("frequency")
_PLAY_PROGRAM = InterfaceRef("test.play_program/v1").operation("play")
_PLAY_PROGRAM_ARGUMENT = _PLAY_PROGRAM.argument("program")
_SAMPLE_SIGNAL = InterfaceRef("test.scalar_signal/v1").acquisition("sample")
_DC = InterfaceRef("test.dc/v1")
_DC_MODE = _DC.property("mode")
_DC_VOLTAGE_LEVEL = _DC.property("voltage_level")
_DC_CURRENT_LEVEL = _DC.property("current_level")


class _TrackingDriver(SignalInstrumentDriver):
    def __init__(self, instrument_id: str) -> None:
        super().__init__(instrument_id=instrument_id)
        self.disconnected = False
        self.aborted = False
        self.disconnect_count = 0
        self.abort_count = 0

    @override
    def disconnect(self) -> None:
        self.disconnected = True
        self.disconnect_count += 1

    @override
    def abort(self) -> None:
        self.aborted = True
        self.abort_count += 1


class _TrackingProvider:
    provider_id = "tests.interactive_provider"

    def __init__(
        self,
        driver_type: type[_TrackingDriver] = _TrackingDriver,
    ) -> None:
        self._driver_type = driver_type
        self.drivers: list[_TrackingDriver] = []
        self.described_bindings: list[tuple[InstrumentBindingSpec, ...]] = []

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        self.described_bindings.append(context.bindings)
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(
                self._driver_type(instrument_id).describe()
                for instrument_id in _selected_ids(context)
            ),
        )

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> InstrumentDriver:
        driver = self._driver_type(context.binding.id)
        self.drivers.append(driver)
        return driver


class _ToggleDescriptionProvider(_TrackingProvider):
    def __init__(
        self,
        driver_type: type[_TrackingDriver] = _TrackingDriver,
    ) -> None:
        super().__init__(driver_type)
        self.description_available = True

    @override
    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        if not self.description_available:
            raise AssertionError("open retry resolved the replacement config")
        return super().describe(context)


class _UpdatedContractDriver(_TrackingDriver):
    def __init__(self, instrument_id: str) -> None:
        super().__init__(instrument_id)
        self.implementation_version = "v1"


class _RejectedProvider(_TrackingProvider):
    @override
    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> InstrumentDriver:
        del context
        raise DriverFault(
            problem(
                "slow_rejection",
                "the provider rejected the connection",
                phase=ProblemPhase.PROVIDER_PREFLIGHT,
                location=model_location("instrument_provider"),
            )
        )


class _ReadFailDriver(_TrackingDriver):
    @override
    def read_state(self) -> Never:
        raise RuntimeError("read transport failed")


class _AbortFailDriver(_TrackingDriver):
    @override
    def abort(self) -> Never:
        self.aborted = True
        self.abort_count += 1
        raise RuntimeError("abort transport failed")


class _ResyncDriver(_TrackingDriver):
    def __init__(self, instrument_id: str) -> None:
        super().__init__(instrument_id)
        self.read_count = 0
        self.fail_next_read = False
        self.return_invalid_next_read = False

    def change_from_front_panel(self, value: float) -> None:
        self._state[("test.set_frequency/v1", "frequency")] = StateValue(
            Quantity(value=value, unit="GHz")
        )

    @override
    def read_state(self) -> InstrumentStateSnapshot:
        self.read_count += 1
        if self.fail_next_read:
            self.fail_next_read = False
            raise RuntimeError("stale connection")
        if self.return_invalid_next_read:
            self.return_invalid_next_read = False
            return InstrumentStateSnapshot(instrument_id=f"{self.instrument_id}-wrong")
        return super().read_state()


class _InvalidCollectDriver(_TrackingDriver):
    @override
    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        self.collect_requests.append(request)
        return CollectReceipt(
            readback=InstrumentReadback(
                values={"signal": Quantity(value=1.0, unit="K")}
            )
        )


class _InvokeReadbackDriver(_TrackingDriver):
    def __init__(self, instrument_id: str) -> None:
        super().__init__(instrument_id)
        self.read_count = 0

    @override
    def read_state(self) -> InstrumentStateSnapshot:
        self.read_count += 1
        return super().read_state()

    @override
    def invoke(self, request: DriverInvokeRequest) -> InvokeReceipt:
        self.invoked.append(request)
        return InvokeReceipt(status="invoked")


class _NonConvergingApplyDriver(_ResyncDriver):
    @override
    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        self.applied.append(request)
        return ApplyReceipt(status="applied")


class _StatefulDriver(_TrackingDriver):
    def __init__(
        self,
        instrument_id: str,
        state: dict[tuple[str, str], StateValue],
    ) -> None:
        super().__init__(instrument_id)
        for target, value in self._state.items():
            state.setdefault(target, value)
        self._state = state


class _VariantDriver(_TrackingDriver):
    def __init__(self, instrument_id: str) -> None:
        super().__init__(instrument_id)
        self.mode = "voltage"
        self.voltage_level = 0.1
        self.current_level = 0.01

    @override
    def describe(self) -> InstrumentDescription:
        base = super().describe()
        return base.model_copy(
            update={
                "interfaces": [
                    *base.interfaces,
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
                        acquisitions=[
                            state_discriminated_acquisition(
                                "measure",
                                discriminator=state_discriminator_ref(
                                    "test.dc/v1",
                                    "mode",
                                ),
                                cases=(
                                    acquisition_case(
                                        "voltage",
                                        results=(
                                            acquisition_result(
                                                "monitored_voltage",
                                                unit="V",
                                            ),
                                        ),
                                    ),
                                    acquisition_case(
                                        "current",
                                        results=(
                                            acquisition_result(
                                                "monitored_current",
                                                unit="A",
                                            ),
                                        ),
                                    ),
                                ),
                            )
                        ],
                    ),
                ]
            }
        )

    @override
    def read_state(self) -> InstrumentStateSnapshot:
        level_property = "voltage_level" if self.mode == "voltage" else "current_level"
        level = self.voltage_level if self.mode == "voltage" else self.current_level
        return InstrumentStateSnapshot(
            instrument_id=self.instrument_id,
            properties=[
                *super().read_state().properties,
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
    def collect(self, request: DriverCollectRequest) -> CollectReceipt:
        self.collect_requests.append(request)
        values: dict[str, MeasurementValue] = {
            result.request_id: (
                Quantity(value=self.voltage_level, unit="V")
                if result.result_id == "monitored_voltage"
                else Quantity(value=self.current_level, unit="A")
            )
            for result in request.results
        }
        return CollectReceipt(readback=InstrumentReadback(values=values))

    @override
    def apply_state(self, request: DriverApplyRequest) -> ApplyReceipt:
        self.applied.append(request)
        for assignment in request.assignments:
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


class _StatefulProvider:
    provider_id = "tests.stateful_interactive_provider"

    def __init__(self) -> None:
        self.state: dict[tuple[str, str], StateValue] = {}

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(
                _StatefulDriver(instrument_id, self.state).describe()
                for instrument_id in _selected_ids(context)
            ),
        )

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> InstrumentDriver:
        return _StatefulDriver(context.binding.id, self.state)


class _ShutdownRaceDriver(_TrackingDriver):
    def __init__(
        self,
        instrument_id: str,
        *,
        read_entered: Event,
        release_read: Event,
        abort_entered: Event,
        release_abort: Event,
    ) -> None:
        super().__init__(instrument_id)
        self._read_entered = read_entered
        self._release_read = release_read
        self._abort_entered = abort_entered
        self._release_abort = release_abort

    @override
    def read_state(self) -> InstrumentStateSnapshot:
        if self.instrument_id == "source-1":
            self._read_entered.set()
            assert self._release_read.wait(timeout=3)
        return super().read_state()

    @override
    def abort(self) -> None:
        self.aborted = True
        self.abort_count += 1
        if self.instrument_id == "source-0":
            self._abort_entered.set()
            assert self._release_abort.wait(timeout=3)


class _ShutdownRaceProvider:
    provider_id = "tests.shutdown_race_provider"

    def __init__(self) -> None:
        self.read_entered = Event()
        self.release_read = Event()
        self.abort_entered = Event()
        self.release_abort = Event()
        self.drivers: list[_ShutdownRaceDriver] = []

    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        return InstrumentProviderDescription(
            provider_id=self.provider_id,
            instruments=tuple(
                _TrackingDriver(instrument_id).describe()
                for instrument_id in _selected_ids(context)
            ),
        )

    def connect(
        self,
        context: InstrumentConnectionContext,
    ) -> InstrumentDriver:
        driver = _ShutdownRaceDriver(
            context.binding.id,
            read_entered=self.read_entered,
            release_read=self.release_read,
            abort_entered=self.abort_entered,
            release_abort=self.release_abort,
        )
        self.drivers.append(driver)
        return driver


class _ProblemProvider(_TrackingProvider):
    @override
    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        description = super().describe(context)
        return InstrumentProviderDescription(
            provider_id=description.provider_id,
            instruments=description.instruments,
            problems=(
                problem(
                    "source_zero_problem",
                    "source zero is misconfigured",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location("instrument_provider"),
                    details={"instrument_id": "source-0"},
                ),
                problem(
                    "source_one_problem",
                    "source one is misconfigured",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location(
                        "instrument_provider",
                        "config",
                        "system",
                        "instrument_registry",
                        "instruments",
                        1,
                    ),
                ),
                problem(
                    "provider_global_problem",
                    "provider discovery is incomplete",
                    phase=ProblemPhase.PROVIDER_PREFLIGHT,
                    location=model_location("instrument_provider"),
                ),
            ),
        )


class _ScopedProblemProvider(_ProblemProvider):
    @override
    def describe(
        self,
        context: InstrumentProviderContext,
    ) -> InstrumentProviderDescription:
        description = super().describe(context)
        return InstrumentProviderDescription(
            provider_id=description.provider_id,
            instruments=description.instruments,
            problems=tuple(
                item
                for item in description.problems
                if item.code == "source_zero_problem"
            ),
        )


def test_instrument_views_expose_only_safe_configuration_summaries(
    tmp_path: Path,
) -> None:
    config = _config_with_private_instrument_settings()
    with (
        _runtime(tmp_path, _TrackingProvider(), config=config) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        list_response = transport.get("/api/v1/instruments")
        detail_response = transport.get("/api/v1/instruments/source-0")

    assert list_response.status_code == 200
    assert detail_response.status_code == 200
    payload = list_response.json()
    assert set(payload) == {"config_entry_id", "items", "problems"}
    by_id = {item["instrument_id"]: item for item in payload["items"]}
    assert by_id["source-0"]["driver_id"] == "tests.signal_instrument"
    assert by_id["source-0"]["connection"] == {
        "kind": "tcpip_socket",
        "host": "instrument.example",
        "port": 5025,
    }
    assert by_id["source-1"]["connection"] == {"kind": "virtual"}
    assert detail_response.json() == by_id["source-0"]
    for forbidden in (
        "spec",
        "config_content_hash",
        "timeout_seconds",
        "options",
        "default_state",
        "run_start",
        "private-token",
    ):
        assert forbidden not in list_response.text
        assert forbidden not in detail_response.text


def test_notebook_direct_interaction_releases_ownership_but_keeps_connection(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            lab = LabClient(daemon, operator="default-operator")

            [available] = lab.instruments.list().items
            assert available.availability == "available"

            with lab.instruments.open("source-0", actor="alice") as instrument:
                description = instrument.describe()
                state_receipt = instrument.apply(
                    {_SET_FREQUENCY: Quantity(value=5.1, unit="GHz")},
                    command_id="notebook-apply-1",
                )
                payload = command_payload_from_bytes(
                    id="program-1",
                    schema_id="pulse_program",
                    codec_id="tests.canonical-json",
                    codec_version=1,
                    media_type="application/json",
                    content=b'{"samples":[0.0]}',
                )
                invoke_receipt = instrument.invoke(
                    _PLAY_PROGRAM,
                    {_PLAY_PROGRAM_ARGUMENT: payload},
                    command_id="notebook-invoke-1",
                )
                collect_receipt = instrument.collect(
                    _SAMPLE_SIGNAL,
                    _SAMPLE_SIGNAL.result("signal"),
                    command_id="notebook-collect-1",
                )
                [owned] = lab.instruments.list().items

                assert description.instrument_id == "source-0"
                assert state_receipt.status == "applied"
                assert invoke_receipt.status == "invoked"
                assert invoke_receipt.state is not None
                assert collect_receipt.status == "collected"
                assert owned.availability == "active"
                assert owned.owner_kind == "instrument_session"
                assert owned.owner_actor == "alice"

            [released] = lab.instruments.list().items
            [driver] = provider.drivers
            assert released.availability == "available"
            assert not driver.disconnected
            assert driver.applied[0].assignments[0].property_id == "frequency"
            assert driver.invoked[0].operation_id == "play"
            assert driver.invoked[0].payloads[payload.id].content == (
                b'{"samples":[0.0]}'
            )
            [collect_request] = driver.collect_requests
            assert collect_request.acquisition_id == "sample"
            assert [result.result_id for result in collect_request.results] == [
                "signal"
            ]


def test_invoke_without_reported_state_reads_back_before_returning(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_InvokeReadbackDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            handle = LabClient(_daemon_client(transport)).instruments.open(
                "source-0",
                actor="alice",
            )
            _ = handle.session_id
            [driver] = provider.drivers
            assert isinstance(driver, _InvokeReadbackDriver)
            reads_before_invoke = driver.read_count
            payload = command_payload_from_bytes(
                id="program-1",
                schema_id="pulse_program",
                codec_id="tests.canonical-json",
                codec_version=1,
                media_type="application/json",
                content=b'{"samples":[0.0]}',
            )

            receipt = handle.invoke(
                _PLAY_PROGRAM,
                {_PLAY_PROGRAM_ARGUMENT: payload},
            )
            handle.close()

            assert receipt.status == "invoked"
            assert receipt.state is not None
            assert receipt.state.instrument_id == "source-0"
            assert driver.read_count == reads_before_invoke + 1


def test_notebook_invoke_rejects_argument_from_another_operation(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    unrelated = (
        InterfaceRef("test.play_program/v1").operation("preview").argument("program")
    )
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            lab = LabClient(_daemon_client(transport))

            with lab.instruments.open("source-0", actor="alice") as instrument:
                with pytest.raises(
                    ValueError,
                    match="arguments must belong to the selected operation",
                ):
                    instrument.invoke(
                        _PLAY_PROGRAM,
                        {unrelated: False},
                    )

                [driver] = provider.drivers
                assert driver.invoked == []


def test_notebook_collect_rejects_a_result_from_another_acquisition(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            handle = LabClient(_daemon_client(transport)).instruments.open(
                "source-0",
                actor="alice",
            )
            unrelated = (
                InterfaceRef("test.other/v1").acquisition("sample").result("signal")
            )

            with pytest.raises(
                ValueError,
                match="results must belong to the selected acquisition",
            ):
                handle.collect(_SAMPLE_SIGNAL, unrelated)
            handle.close()

            [driver] = provider.drivers
            assert driver.collect_requests == []


def test_apply_without_reported_state_reads_back_before_returning(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_ResyncDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            handle = LabClient(_daemon_client(transport)).instruments.open(
                "source-0",
                actor="alice",
            )
            _ = handle.session_id
            [driver] = provider.drivers
            assert isinstance(driver, _ResyncDriver)
            reads_before_apply = driver.read_count

            receipt = handle.apply(
                {_SET_FREQUENCY: Quantity(value=5.1, unit="GHz")},
            )
            handle.close()

            assert receipt.status == "applied"
            assert receipt.state is not None
            assert driver.read_count == reads_before_apply + 1


def test_apply_readback_must_confirm_the_requested_state(tmp_path: Path) -> None:
    provider = _TrackingProvider(_NonConvergingApplyDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-non-converging",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )

            with pytest.raises(
                DaemonConflictError,
                match="readback did not match requested state",
            ):
                daemon.apply_instrument_state(
                    session.session_id,
                    "source-0",
                    _apply_command(value=5.1),
                )

            [driver] = provider.drivers
            assert isinstance(driver, _NonConvergingApplyDriver)
            [instrument] = daemon.list_instruments().items
            assert len(driver.applied) == 1
            assert driver.read_count == 2
            assert driver.disconnect_count == 1
            assert instrument.availability == "quarantined"


def test_interactive_apply_tracks_observed_discriminated_state(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_VariantDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            handle = LabClient(_daemon_client(transport)).instruments.open(
                "source-0",
                actor="alice",
            )
            _ = handle.session_id

            voltage = handle.apply(
                {_DC_VOLTAGE_LEVEL: 0.2},
                command_id="voltage-before-switch",
            )
            with pytest.raises(DaemonConflictError, match="set mode explicitly"):
                handle.apply(
                    {_DC_CURRENT_LEVEL: 0.02},
                    command_id="invalid-current-patch",
                )

            switched = handle.apply(
                {
                    _DC_MODE: "current",
                    _DC_CURRENT_LEVEL: 0.02,
                },
                command_id="switch-current",
            )
            replay = handle.apply(
                {_DC_VOLTAGE_LEVEL: 0.2},
                command_id="voltage-before-switch",
            )
            partial = handle.apply(
                {_DC_CURRENT_LEVEL: 0.03},
                command_id="adjust-current",
            )
            handle.close()

            assert switched.state is not None
            switched_properties = {
                item.property_id: item.value.root
                for item in switched.state.properties
                if item.interface_id == "test.dc/v1"
            }
            assert switched_properties == {
                "current_level": 0.02,
                "mode": "current",
                "output_enabled": False,
            }
            assert replay == voltage
            assert partial.status == "applied"
            [driver] = provider.drivers
            assert len(driver.applied) == 3


def test_direct_collect_requires_the_active_acquisition_state(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_VariantDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-stateful-collect",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            [driver] = provider.drivers

            receipt = daemon.collect_instrument(
                session.session_id,
                "source-0",
                _variant_collect_command(
                    command_id="collect-active-voltage",
                    result_id="monitored_voltage",
                ),
            )

            assert receipt.status == "collected"
            assert len(driver.collect_requests) == 1
            with pytest.raises(
                DaemonConflictError,
                match="is inactive in state case 'voltage'",
            ):
                daemon.collect_instrument(
                    session.session_id,
                    "source-0",
                    _variant_collect_command(
                        command_id="collect-inactive-current",
                        result_id="monitored_current",
                    ),
                )
            assert len(driver.collect_requests) == 1

            runtime.application.instruments._sessions[session.session_id].instruments[
                "source-0"
            ].invalidate_state()
            with pytest.raises(
                DaemonConflictError,
                match="requires a complete observed discriminator state",
            ):
                daemon.collect_instrument(
                    session.session_id,
                    "source-0",
                    _variant_collect_command(
                        command_id="collect-unknown-voltage",
                        result_id="monitored_voltage",
                    ),
                )
            assert len(driver.collect_requests) == 1
            daemon.close_instrument_session(session.session_id)


def test_operation_retry_is_deduplicated_and_conflicting_content_is_rejected(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-1",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            command = _apply_command(value=5.0)

            first = daemon.apply_instrument_state(
                session.session_id,
                "source-0",
                command,
            )
            second = daemon.apply_instrument_state(
                session.session_id,
                "source-0",
                command,
            )

            assert second == first
            [driver] = provider.drivers
            assert len(driver.applied) == 1
            with pytest.raises(DaemonConflictError, match="different apply content"):
                daemon.apply_instrument_state(
                    session.session_id,
                    "source-0",
                    _apply_command(value=5.2),
                )
            daemon.close_instrument_session(session.session_id)


def test_apply_rejects_logical_assignments_for_one_physical_property(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-duplicate-physical-property",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            payload = _apply_command(value=5.1).model_dump(mode="json")
            duplicate = dict(payload["assignments"][0])
            duplicate["entity_ids"] = ["sample"]
            payload["assignments"].append(duplicate)

            response = transport.post(
                "/api/v1/instrument-sessions/"
                f"{session.session_id}/instruments/source-0/state/apply",
                json=payload,
            )

            assert response.status_code == 422
            assert "property targets must be unique" in response.text
            [driver] = provider.drivers
            assert driver.applied == []
            daemon.close_instrument_session(session.session_id)


def test_open_retry_reuses_session_without_reprovisioning(tmp_path: Path) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            command = InstrumentSessionOpenCommand(
                operation_id="open-retry",
                actor="alice",
                instrument_ids=("source-0",),
            )

            first = daemon.open_instrument_session(command)
            second = daemon.open_instrument_session(command)

            assert second == first
            assert len(provider.drivers) == 1
            daemon.close_instrument_session(first.session_id)


def test_open_retry_recovers_before_resolving_replacement_config(
    tmp_path: Path,
) -> None:
    provider = _ToggleDescriptionProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            original = runtime.application.config.get_active_config()
            command = InstrumentSessionOpenCommand(
                operation_id="open-retry-after-config-activation",
                actor="alice",
                instrument_ids=("source-0",),
            )

            def replace_active_config() -> None:
                updated = load_config().model_copy(update={"id": "updated-config"})
                runtime.application.config.publish_config(
                    ConfigPublishCommand(
                        source=DirectConfigRevisionSource(config=updated),
                        entry_id="updated-config",
                        actor="operator",
                        expected_generation=1,
                    )
                )
                provider.description_available = False

            daemon = _daemon_client(
                transport,
                drop_response_suffix="/instrument-sessions",
                on_response_drop=replace_active_config,
            )
            session = daemon.open_instrument_session(command)

            [durable] = runtime.application.executor._control.list_instrument_sessions()
            assert session.session_id == durable.session_id
            assert session.config_entry_id == original.entry.id
            assert session.config_content_hash == original.entry.content_hash
            assert len(provider.drivers) == 1
            daemon.close_instrument_session(session.session_id)


def test_sequential_sessions_reuse_connection_but_not_state_or_replay_scope(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_ResyncDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            first = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-owner-1",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            daemon.apply_instrument_state(
                first.session_id,
                "source-0",
                _apply_command(value=5.0),
            )
            daemon.close_instrument_session(first.session_id)

            [driver] = provider.drivers
            assert isinstance(driver, _ResyncDriver)
            assert driver.read_count == 2
            driver.change_from_front_panel(5.1)

            second = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-owner-2",
                    actor="bob",
                    instrument_ids=("source-0",),
                )
            )
            assert provider.drivers == [driver]
            assert driver.read_count == 3
            second_apply = daemon.apply_instrument_state(
                second.session_id,
                "source-0",
                _apply_command(value=5.2),
            )
            daemon.close_instrument_session(second.session_id)

            assert second_apply.status == "applied"
            assert driver.read_count == 4
            assert len(driver.applied) == 2
            assert [
                request.assignments[0].value.root for request in driver.applied
            ] == [
                Quantity(value=5.0, unit="GHz"),
                Quantity(value=5.2, unit="GHz"),
            ]
            assert driver.disconnect_count == 0


def test_config_activation_reuses_matching_connection_with_fresh_state(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_ResyncDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-before-config-activation",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            [driver] = provider.drivers
            assert isinstance(driver, _ResyncDriver)
            assert driver.read_count == 1
            updated = _config_with_default_state(
                InstrumentPropertyState(
                    interface_id="test.set_frequency/v1",
                    property_id="frequency",
                    value=StateValue(Quantity(value=5.0, unit="GHz")),
                )
            ).model_copy(update={"id": "updated-config"})

            receipt = runtime.application.config.publish_config(
                ConfigPublishCommand(
                    source=DirectConfigRevisionSource(config=updated),
                    entry_id="updated-config",
                    actor="operator",
                    expected_generation=1,
                )
            )

            assert receipt.activation.generation == 2
            assert driver.disconnect_count == 0
            daemon.close_instrument_session(session.session_id)
            driver.change_from_front_panel(5.1)
            reopened = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-after-config-activation",
                    actor="bob",
                    instrument_ids=("source-0",),
                )
            )
            assert provider.drivers == [driver]
            assert driver.read_count == 2
            assert driver.disconnect_count == 0
            daemon.close_instrument_session(reopened.session_id)


@pytest.mark.parametrize(
    "instrument_update",
    [
        {"connection": VirtualInstrumentConnection(options={"resource": "alternate"})},
        {"driver_id": "tests.alternate_signal_instrument"},
    ],
    ids=("connection-options", "driver"),
)
def test_binding_identity_change_reconnects_idle_instrument(
    tmp_path: Path,
    instrument_update: dict[str, object],
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            first = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-before-binding-change",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            daemon.close_instrument_session(first.session_id)
            [original] = provider.drivers

            config = load_config()
            [instrument] = config.instrument_registry.instruments
            updated_instrument = instrument.model_copy(update=instrument_update)
            registry = config.instrument_registry.model_copy(
                update={"instruments": [updated_instrument]}
            )
            updated = config.model_copy(
                update={
                    "id": "updated-binding",
                    "system": config.system.model_copy(
                        update={"instrument_registry": registry}
                    ),
                }
            )
            runtime.application.config.publish_config(
                ConfigPublishCommand(
                    source=DirectConfigRevisionSource(config=updated),
                    entry_id="updated-binding",
                    actor="operator",
                    expected_generation=1,
                )
            )

            second = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-after-binding-change",
                    actor="bob",
                    instrument_ids=("source-0",),
                )
            )
            assert len(provider.drivers) == 2
            assert original.disconnect_count == 1
            daemon.close_instrument_session(second.session_id)


def test_contract_identity_change_reconnects_idle_instrument(tmp_path: Path) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            first = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-before-contract-change",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            daemon.close_instrument_session(first.session_id)
            [original] = provider.drivers

            provider._driver_type = _UpdatedContractDriver
            second = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-after-contract-change",
                    actor="bob",
                    instrument_ids=("source-0",),
                )
            )

            assert len(provider.drivers) == 2
            assert original.disconnect_count == 1
            assert second.descriptions[0].implementation_version == "v1"
            daemon.close_instrument_session(second.session_id)


def test_stale_idle_connection_is_replaced_after_resynchronization_failure(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_ResyncDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            first = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-before-stale",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            daemon.close_instrument_session(first.session_id)

            [stale] = provider.drivers
            assert isinstance(stale, _ResyncDriver)
            stale.fail_next_read = True

            second = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-after-stale",
                    actor="bob",
                    instrument_ids=("source-0",),
                )
            )
            assert len(provider.drivers) == 2
            replacement = provider.drivers[1]
            assert isinstance(replacement, _ResyncDriver)
            assert stale.disconnect_count == 1
            assert replacement.read_count == 1
            assert daemon.list_instruments().items[0].availability == "active"
            daemon.close_instrument_session(second.session_id)


def test_shutdown_fences_an_owner_that_finishes_opening_after_the_drain_starts(
    tmp_path: Path,
) -> None:
    provider = _ShutdownRaceProvider()
    with _runtime(tmp_path, provider, config=_two_instrument_config()) as runtime:
        instruments = runtime.application.instruments
        first = instruments.open_session(
            InstrumentSessionOpenCommand(
                operation_id="open-before-shutdown",
                actor="alice",
                instrument_ids=("source-0",),
            )
        )
        control = runtime.application.executor._control
        control.start_instrument_operation(
            first.session_id,
            instrument_id="source-0",
            operation_id="pending-apply",
            kind="apply",
        )

        open_errors: list[BaseException] = []
        shutdown_errors: list[BaseException] = []

        def open_during_shutdown() -> None:
            try:
                instruments.open_session(
                    InstrumentSessionOpenCommand(
                        operation_id="open-racing-shutdown",
                        actor="bob",
                        instrument_ids=("source-1",),
                    )
                )
            except BaseException as error:
                open_errors.append(error)

        def shut_down() -> None:
            try:
                instruments.shutdown()
            except BaseException as error:
                shutdown_errors.append(error)

        opening = Thread(target=open_during_shutdown)
        opening.start()
        assert provider.read_entered.wait(timeout=3)

        shutting_down = Thread(target=shut_down)
        shutting_down.start()
        assert provider.abort_entered.wait(timeout=3)

        provider.release_read.set()
        opening.join(timeout=3)
        provider.release_abort.set()
        shutting_down.join(timeout=3)

        assert not opening.is_alive()
        assert not shutting_down.is_alive()
        assert not shutdown_errors
        assert len(open_errors) == 1
        assert isinstance(open_errors[0], BackendConflict)
        assert str(open_errors[0]) == "instrument service is shutting down"
        assert len(provider.drivers) == 2
        by_id = {driver.instrument_id: driver for driver in provider.drivers}
        assert by_id["source-0"].disconnect_count == 1
        assert by_id["source-1"].disconnect_count == 1
        sessions = control.list_instrument_sessions()
        assert not [session for session in sessions if session.state == "active"]
        assert {session.state for session in sessions} == {
            "attention_required",
            "closed",
        }


def test_provider_rejection_closes_the_daemon_session(tmp_path: Path) -> None:
    provider = _RejectedProvider()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)

        with pytest.raises(DaemonConflictError, match="provider rejected"):
            daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-rejected",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )

        [session] = runtime.application.executor._control.list_instrument_sessions()
        assert session.state == "closed"
        assert session.end_status == "aborted"
        [instrument] = daemon.list_instruments().items
        assert instrument.availability == "available"
        assert provider.drivers == []


def test_notebook_open_retry_reuses_operation_after_response_loss(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(
                transport,
                drop_response_suffix="/instrument-sessions",
            )
            handle = LabClient(daemon).instruments.open(
                "source-0",
                actor="alice",
                command_id="open-after-loss",
            )

            state = handle.read_state()
            handle.close()

            assert state.instrument_id == "source-0"
            assert len(provider.drivers) == 1


def test_notebook_can_abort_a_daemon_owned_session_by_id(tmp_path: Path) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            lab = LabClient(_daemon_client(transport))
            handle = lab.instruments.open("source-0", actor="alice")
            handle.read_state()

            receipt = lab.instruments.abort_session(handle.session_id)
            replay = handle.abort()

            assert receipt.status == "aborted"
            assert replay == receipt
            [driver] = provider.drivers
            assert driver.abort_count == 1


def test_abort_retry_replays_receipt_without_repeating_driver_calls(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-abort-retry",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            first = daemon.abort_instrument_session(session.session_id)
            second = daemon.abort_instrument_session(session.session_id)

            assert second == first
            [driver] = provider.drivers
            assert driver.abort_count == 1
            assert driver.disconnect_count == 0
            assert daemon.close_instrument_session(session.session_id) == first


def test_abort_failure_faults_connection_without_repeating_abort(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_AbortFailDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            first = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-abort-failure",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )

            with pytest.raises(
                DaemonConflictError,
                match="abort was not confirmed",
            ):
                daemon.abort_instrument_session(first.session_id)

            [faulted] = provider.drivers
            assert faulted.abort_count == 1
            assert faulted.disconnect_count == 1
            daemon.resolve_instrument_session_attention(first.session_id)

            second = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-after-abort-failure",
                    actor="bob",
                    instrument_ids=("source-0",),
                )
            )
            assert len(provider.drivers) == 2
            daemon.close_instrument_session(second.session_id)


def test_notebook_close_remains_retryable_after_both_transport_attempts_fail(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(
                transport,
                drop_response_suffix="/close",
                drop_response_count=2,
            )
            handle = LabClient(daemon).instruments.open(
                "source-0",
                actor="alice",
            )
            handle.read_state()

            with pytest.raises(httpx2.ReadError, match="response was lost"):
                handle.close()
            receipt = handle.close()

            assert receipt is not None
            assert receipt.status == "closed"
            [driver] = provider.drivers
            assert driver.disconnect_count == 0


def test_notebook_default_apply_retries_with_same_operation_after_response_loss(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(
                transport,
                drop_response_suffix="/state/apply",
            )
            handle = LabClient(daemon).instruments.open(
                "source-0",
                actor="alice",
            )

            receipt = handle.apply(
                {_SET_FREQUENCY: Quantity(value=5.1, unit="GHz")},
            )
            handle.close()

            assert receipt.status == "applied"
            [driver] = provider.drivers
            assert len(driver.applied) == 1


def test_notebook_default_collect_retries_with_same_operation_after_response_loss(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(
                transport,
                drop_response_suffix="/collect",
            )
            handle = LabClient(daemon).instruments.open(
                "source-0",
                actor="alice",
            )

            receipt = handle.collect(
                _SAMPLE_SIGNAL,
                _SAMPLE_SIGNAL.result("signal"),
            )
            handle.close()

            assert receipt.status == "collected"
            [driver] = provider.drivers
            assert len(driver.collect_requests) == 1


def test_observation_failure_aborts_session_without_quarantining(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_ReadFailDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            with pytest.raises(
                DaemonConflictError,
                match="state could not be observed",
            ):
                daemon.open_instrument_session(
                    InstrumentSessionOpenCommand(
                        operation_id="open-read-failure",
                        actor="alice",
                        instrument_ids=("source-0",),
                    )
                )

            [instrument] = daemon.list_instruments().items
            [driver] = provider.drivers
            assert instrument.availability == "available"
            assert driver.disconnected


@pytest.mark.parametrize("invalid_snapshot", [False, True])
def test_explicit_observation_failure_ends_the_entire_session(
    tmp_path: Path,
    *,
    invalid_snapshot: bool,
) -> None:
    provider = _TrackingProvider(_ResyncDriver)
    config = _two_instrument_config()
    with _runtime(tmp_path, provider, config=config) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            first = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id=f"open-explicit-read-failure-{invalid_snapshot}",
                    actor="alice",
                    instrument_ids=("source-0", "source-1"),
                )
            )
            drivers = {driver.instrument_id: driver for driver in provider.drivers}
            failed_driver = drivers["source-0"]
            assert isinstance(failed_driver, _ResyncDriver)
            if invalid_snapshot:
                failed_driver.return_invalid_next_read = True
            else:
                failed_driver.fail_next_read = True

            with pytest.raises(DaemonConflictError):
                daemon.read_instrument_state(first.session_id, "source-0")

            durable = runtime.application.executor._control.get_instrument_session(
                first.session_id
            )
            assert durable.state == "closed"
            assert durable.end_status == "aborted"
            assert {item.availability for item in daemon.list_instruments().items} == {
                "available"
            }
            assert all(driver.abort_count == 0 for driver in drivers.values())
            assert all(driver.disconnect_count == 1 for driver in drivers.values())
            assert daemon.close_instrument_session(first.session_id).status == "aborted"

            second = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id=f"reopen-after-read-failure-{invalid_snapshot}",
                    actor="bob",
                    instrument_ids=("source-0", "source-1"),
                )
            )
            assert len(provider.drivers) == 4
            daemon.close_instrument_session(second.session_id)


def test_explicit_observation_cleanup_failure_requires_attention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _TrackingProvider(_ResyncDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            opened = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-explicit-read-cleanup-failure",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            control = runtime.application.executor._control

            def fail_close(*_args: object, **_kwargs: object) -> Never:
                raise RuntimeError("control close failed")

            monkeypatch.setattr(control, "close_instrument_session", fail_close)
            [driver] = provider.drivers
            assert isinstance(driver, _ResyncDriver)
            driver.fail_next_read = True

            with pytest.raises(
                DaemonConflictError,
                match="observation failure could not be released",
            ):
                daemon.read_instrument_state(opened.session_id, "source-0")

            durable = control.get_instrument_session(opened.session_id)
            assert durable.state == "attention_required"
            assert (
                durable.attention_reason
                == "instrument_session_observation_cleanup_failed"
            )
            assert driver.abort_count == 0
            assert driver.disconnect_count == 1
            [instrument] = daemon.list_instruments().items
            assert instrument.availability == "quarantined"


def test_acquisition_cleanup_failure_quarantines_the_durable_owner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _TrackingProvider(_ReadFailDriver)
    with _runtime(tmp_path, provider) as runtime:
        control = runtime.application.executor._control

        def fail_close(*_args: object, **_kwargs: object) -> Never:
            raise RuntimeError("control close failed")

        monkeypatch.setattr(control, "close_instrument_session", fail_close)
        with pytest.raises(
            BackendConflict,
            match="acquisition could not be released",
        ):
            runtime.application.instruments.open_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-cleanup-failure",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )

        [session] = control.list_instrument_sessions()
        assert session.state == "attention_required"
        assert session.attention_reason == "instrument_session_open_cleanup_failed"
        [instrument] = runtime.application.instruments.list_instruments().items
        assert instrument.availability == "quarantined"


def test_direct_session_observes_without_applying_default_state(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    config = _config_with_default_state(
        InstrumentPropertyState(
            interface_id="test.set_frequency/v1",
            property_id="frequency",
            value=StateValue(Quantity(value=5.0, unit="GHz")),
        )
    )
    with _runtime(tmp_path, provider, config=config) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            handle = LabClient(_daemon_client(transport)).instruments.open(
                "source-0",
                actor="alice",
            )
            _ = handle.session_id

            [driver] = provider.drivers
            assert driver.applied == []
            handle.close()


def test_invalid_collect_receipt_is_deduplicated_without_quarantining(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider(_InvalidCollectDriver)
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-invalid-collect",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            request = CollectCommand(
                command_id="collect-invalid",
                instrument_id="source-0",
                point_index=0,
                point_count=1,
                requests=[
                    CollectResultRequest(
                        id="signal",
                        interface_id="test.scalar_signal/v1",
                        acquisition_id="sample",
                        result_id="signal",
                        dtype="float64",
                        unit="ratio",
                    )
                ],
            )

            for _attempt in range(2):
                with pytest.raises(
                    DaemonConflictError,
                    match="unit_mismatch",
                ):
                    daemon.collect_instrument(
                        session.session_id,
                        "source-0",
                        request,
                    )

            [driver] = provider.drivers
            [instrument] = daemon.list_instruments().items
            assert len(driver.collect_requests) == 1
            assert instrument.availability == "active"
            daemon.close_instrument_session(session.session_id)


def test_provider_instance_and_virtual_state_survive_across_sessions(
    tmp_path: Path,
) -> None:
    with (
        LocalDaemonRuntime(
            tmp_path,
            bootstrap_config=load_config(),
            instrument_endpoint=LocalInstrumentBackendEndpoint(
                InstrumentBackend(provider=_StatefulProvider())
            ),
        ) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        first = daemon.open_instrument_session(
            InstrumentSessionOpenCommand(
                operation_id="open-stateful-1",
                actor="alice",
                instrument_ids=("source-0",),
            )
        )
        daemon.apply_instrument_state(
            first.session_id,
            "source-0",
            _apply_command(value=5.1),
        )
        daemon.close_instrument_session(first.session_id)

        second = daemon.open_instrument_session(
            InstrumentSessionOpenCommand(
                operation_id="open-stateful-2",
                actor="alice",
                instrument_ids=("source-0",),
            )
        )
        state = daemon.read_instrument_state(
            second.session_id,
            "source-0",
        )
        daemon.close_instrument_session(second.session_id)

    property_state = next(
        item
        for item in state.properties
        if item.interface_id == "test.set_frequency/v1"
    )
    assert property_state.value == StateValue(Quantity(value=5.1, unit="GHz"))


def test_contract_catalog_resolves_the_requested_non_active_config(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    requested = _two_instrument_config()
    with (
        _runtime(tmp_path, provider) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        catalog = _daemon_client(transport).resolve_instrument_contracts(requested)

    assert catalog.config_content_hash == config_content_hash(requested)
    assert tuple(item.instrument_id for item in catalog.instruments) == (
        "source-0",
        "source-1",
    )
    assert provider.described_bindings[-1] == instrument_bindings(requested)


def test_contract_catalog_is_empty_without_an_instrument_backend(
    tmp_path: Path,
) -> None:
    config = load_config()
    with (
        LocalDaemonRuntime(tmp_path, bootstrap_config=config) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        catalog = _daemon_client(transport).resolve_instrument_contracts(config)

    assert catalog.config_content_hash == config_content_hash(config)
    assert catalog.provider_id is None
    assert catalog.instruments == ()
    assert catalog.problems == ()


def test_provider_problems_are_scoped_without_polluting_healthy_views(
    tmp_path: Path,
) -> None:
    config = _two_instrument_config()
    provider = _ProblemProvider()
    with _runtime(tmp_path, provider, config=config) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            instruments = _daemon_client(transport).list_instruments()

    by_id = {item.instrument_id: item for item in instruments.items}
    assert [item.code for item in by_id["source-0"].problems] == ["source_zero_problem"]
    assert [item.code for item in by_id["source-1"].problems] == ["source_one_problem"]
    assert [item.code for item in instruments.problems] == ["provider_global_problem"]


def test_direct_session_ignores_unrelated_instrument_description_problem(
    tmp_path: Path,
) -> None:
    provider = _ScopedProblemProvider()
    with (
        _runtime(tmp_path, provider, config=_two_instrument_config()) as runtime,
        TestClient(runtime.app()) as transport,
    ):
        daemon = _daemon_client(transport)
        session = daemon.open_instrument_session(
            InstrumentSessionOpenCommand(
                operation_id="open-healthy-source",
                actor="alice",
                instrument_ids=("source-1",),
            )
        )

        assert session.instrument_ids == ("source-1",)
        daemon.close_instrument_session(session.session_id)


def test_run_and_interactive_session_compete_for_the_same_resource(
    tmp_path: Path,
) -> None:
    provider = _TrackingProvider()
    config = load_config()
    with _runtime(tmp_path, provider) as runtime:  # noqa: SIM117
        with TestClient(runtime.app()) as transport:
            daemon = _daemon_client(transport)
            session = daemon.open_instrument_session(
                InstrumentSessionOpenCommand(
                    operation_id="open-exclusive",
                    actor="alice",
                    instrument_ids=("source-0",),
                )
            )
            admission = daemon.submit_run(_submission(config))

            with pytest.raises(DaemonConflictError, match="resources are busy"):
                daemon.start_executor(
                    admission.run_id,
                    ExecutorStartRequest(executor_id="notebook"),
                )

            daemon.close_instrument_session(session.session_id)
            executor = daemon.start_executor(
                admission.run_id,
                ExecutorStartRequest(executor_id="notebook"),
            )
            assert executor.run_id == admission.run_id

            with pytest.raises(DaemonConflictError, match="resources are busy"):
                daemon.open_instrument_session(
                    InstrumentSessionOpenCommand(
                        operation_id="open-while-run",
                        actor="bob",
                        instrument_ids=("source-0",),
                    )
                )


def _runtime(
    root: Path,
    provider: InstrumentProvider,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> LocalDaemonRuntime:
    return LocalDaemonRuntime(
        root,
        bootstrap_config=config if config is not None else load_config(),
        instrument_endpoint=LocalInstrumentBackendEndpoint(
            InstrumentBackend(
                provider=provider,
                payload_codecs=json_payload_codecs("pulse_program"),
            )
        ),
    )


def _daemon_client(
    transport: TestClient,
    *,
    drop_response_suffix: str | None = None,
    drop_response_count: int = 1,
    on_response_drop: Callable[[], None] | None = None,
) -> DaemonClient:
    responses_dropped = 0

    def send(request: httpx2.Request) -> httpx2.Response:
        nonlocal responses_dropped
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
        if (
            drop_response_suffix is not None
            and request.url.path.endswith(drop_response_suffix)
            and responses_dropped < drop_response_count
        ):
            responses_dropped += 1
            if on_response_drop is not None:
                on_response_drop()
            raise httpx2.ReadError(
                "response was lost",
                request=request,
            )
        return translated

    return DaemonClient(
        "http://testserver",
        transport=httpx2.MockTransport(send),
    )


def _selected_ids(context: InstrumentProviderContext) -> Sequence[str]:
    return tuple(item.id for item in context.bindings)


def _apply_command(*, value: float) -> InstrumentStateCommand:
    return InstrumentStateCommand(
        command_id="apply-1",
        instrument_id="source-0",
        assignments=[
            InstrumentStateAssignment(
                resource_id="source-0",
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=StateValue(Quantity(value=value, unit="GHz")),
            )
        ],
    )


def _variant_collect_command(
    *,
    command_id: str,
    result_id: str,
) -> CollectCommand:
    unit = "V" if result_id == "monitored_voltage" else "A"
    return CollectCommand(
        command_id=command_id,
        instrument_id="source-0",
        point_index=0,
        point_count=1,
        requests=[
            CollectResultRequest(
                id="reading",
                interface_id="test.dc/v1",
                acquisition_id="measure",
                result_id=result_id,
                unit=unit,
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


def _config_with_default_state(
    *properties: InstrumentPropertyState,
) -> ConfigProfileSnapshot:
    config = load_config()
    [instrument] = config.instrument_registry.instruments
    configured = instrument.model_copy(
        update={
            "run_start": "apply_default_state",
            "default_state": list(properties),
        }
    )
    registry = config.instrument_registry.model_copy(
        update={"instruments": [configured]}
    )
    return config.model_copy(
        update={
            "system": config.system.model_copy(update={"instrument_registry": registry})
        }
    )


def _config_with_private_instrument_settings() -> ConfigProfileSnapshot:
    config = _two_instrument_config()
    source, virtual = config.instrument_registry.instruments
    configured = source.model_copy(
        update={
            "connection": TcpipSocketInstrumentConnection(
                host="instrument.example",
                port=5025,
                timeout_seconds=17.0,
                options={"api_token": "private-token"},
            ),
            "default_state": [
                InstrumentPropertyState(
                    interface_id="test.set_frequency/v1",
                    property_id="frequency",
                    value=StateValue(Quantity(value=5.0, unit="GHz")),
                )
            ],
            "run_start": "apply_default_state",
        }
    )
    registry = config.instrument_registry.model_copy(
        update={"instruments": [configured, virtual]}
    )
    return config.model_copy(
        update={
            "system": config.system.model_copy(update={"instrument_registry": registry})
        }
    )


def _submission(config: ConfigProfileSnapshot) -> RunSubmission:
    return RunSubmission(
        submission_id="interactive-exclusion",
        config=config,
        request=RunRequest(experiment_id="scratch"),
        plan=RunPlanSummary(
            experiment_id="scratch",
            experiment_kind="scratch",
            point_count=1,
            run_resource_claims=(ResourceKey(kind="instrument", id="source-0"),),
        ),
    )
