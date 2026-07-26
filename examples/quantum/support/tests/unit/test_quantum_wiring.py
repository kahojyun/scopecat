from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
import scopecat as sc
from scopecat.compiler.frontend.resolution import (
    compile_invocation,
    resolve_compiled_invocation,
)
from scopecat.config.environment import build_config_environment
from scopecat.config.profile_validation import validate_config_profile
from scopecat.execution.interpreter import execute_admitted_run
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.planning.routing import RoutingView
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateCommand,
    InstrumentStateSnapshot,
)
from scopecat_quantum._ids import QubitId
from scopecat_quantum.pulses import AcquireSignal, DriveSignal
from tests.testkit.runtime import (
    admit_test_run,
    sqlite_execution_session,
    sqlite_run_repository,
)

from quantum_lab_demo.configuration import quantum_lab_bootstrap_config
from quantum_lab_demo.scenarios.opaque_collection import (
    GATE_DURATION,
    parallel_gate_set_template,
)
from quantum_lab_demo.targets.fake_list_mode import configured_fake_list_target
from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider
from quantum_lab_demo.virtual_lab.wiring import (
    ChannelWiring,
    compile_quantum_wiring_system,
    quantum_wiring,
    quantum_wiring_config_profile,
)

from .demo_lab_test_paths import EXPERIMENT_VIRTUAL_LAB_PROFILE


def test_quantum_wiring_builder_compiles_lab_vocabulary_to_core_config() -> None:
    base = quantum_lab_bootstrap_config()
    wiring = (
        quantum_wiring()
        .qubit(
            "q0",
            drive=ChannelWiring(
                instrument_id="drive-stack",
                channel_id="drive.awg0.ch1",
            ),
            readout=ChannelWiring(
                instrument_id="readout-stack",
                channel_id="readout.mux0",
            ),
        )
        .build()
    )
    config = base.model_copy(
        update={"system": compile_quantum_wiring_system(base.system, wiring)}
    )

    assert not validate_config_profile(config)
    assert [(entity.id, entity.kind) for entity in config.topology.entities] == [
        ("q0", "logical_qubit")
    ]

    routing = RoutingView.from_config(config)
    drive_manifest = routing.bind_port(
        port_id=logical_resource_port_id("drive"),
        capabilities=("play_pulse_program",),
    )
    readout_manifest = routing.bind_port(
        port_id=logical_resource_port_id("readout"),
        capabilities=("acquire_iq",),
    )
    drive = drive_manifest.select_one(("q0",))
    readout = readout_manifest.select_one(("q0",))

    assert drive.instrument_id == "drive-stack"
    assert [
        (binding.entity_id, binding.channel_id, binding.capability)
        for binding in drive.channel_bindings
    ] == [("q0", "drive.awg0.ch1", "play_pulse_program")]
    assert readout.instrument_id == "readout-stack"
    assert [
        (binding.entity_id, binding.channel_id, binding.capability)
        for binding in readout.channel_bindings
    ] == [("q0", "readout.mux0", "acquire_iq")]


def test_quantum_wiring_builder_rejects_unknown_coupler_qubits() -> None:
    builder = quantum_wiring().coupler(
        "coupler-q0-q1",
        qubits=("q0", "q1"),
        flux=ChannelWiring(
            instrument_id="coupler-stack",
            channel_id="bias0",
        ),
    )

    with pytest.raises(ValueError, match="references unknown qubit 'q0'"):
        builder.build()


def test_default_quantum_wiring_config_describes_channel_routes() -> None:
    config = quantum_wiring_config_profile()

    assert not validate_config_profile(config)
    assert config.domain_target is not None
    assert config.domain_target.kind == "quantum_lab_demo.fake-list-mode"
    assert {
        (binding.instrument_id, binding.entity_id, binding.channel_id)
        for binding in config.routing.bindings
    } >= {
        ("drive-stack", "q0", "drive.awg0.ch1"),
        ("drive-stack", "q1", "drive.awg0.ch2"),
        ("readout-stack", "q0", "readout.mux0"),
        ("coupler-stack", "coupler-q0-q1", "coupler.bias0"),
    }

    routing = RoutingView.from_config(config)
    drive_manifest = routing.bind_port(
        port_id=logical_resource_port_id("drive"),
        capabilities=("play_pulse_program",),
    )
    readout_manifest = routing.bind_port(
        port_id=logical_resource_port_id("readout"),
        capabilities=("acquire_iq",),
    )
    drive_binding = drive_manifest.select_one(("q0", "q1"))
    readout_binding = readout_manifest.select_one(("q0", "q1"))

    assert drive_binding.instrument_id == "drive-stack"
    assert [
        (binding.entity_id, binding.channel_id)
        for binding in drive_binding.channel_bindings
    ] == [
        ("q0", "drive.awg0.ch1"),
        ("q1", "drive.awg0.ch2"),
    ]
    assert readout_binding.instrument_id == "readout-stack"
    assert [
        (binding.entity_id, binding.channel_id)
        for binding in readout_binding.channel_bindings
    ] == [
        ("q0", "readout.mux0"),
        ("q1", "readout.mux0"),
    ]


def test_target_signal_bindings_are_derived_from_accepted_routing() -> None:
    q0 = QubitId("q0")
    list_config = quantum_wiring_config_profile()
    list_target = configured_fake_list_target(list_config)
    list_domain_target = list_config.domain_target
    drive_channel = list_target.output_channel(DriveSignal(q0))
    acquisition_channel = list_target.acquisition_channel(AcquireSignal(q0))

    assert list_domain_target is not None
    assert drive_channel is not None
    assert acquisition_channel is not None
    assert list_target.id.value == list_domain_target.id
    assert drive_channel.value == "drive-stack:drive.awg0.ch1:q0"
    assert acquisition_channel.value == "readout-stack:readout.mux0:q0"


def test_virtual_provider_description_declares_full_instrument_schemas() -> None:
    config = quantum_wiring_config_profile()
    provider = QuantumLabVirtualProvider(profile=EXPERIMENT_VIRTUAL_LAB_PROFILE)

    description = provider.describe(InstrumentProviderContext(config=config))

    assert description.problems == ()
    assert [instrument.instrument_id for instrument in description.instruments] == [
        "drive-stack",
        "readout-stack",
        "coupler-stack",
    ]
    assert {
        capability.id
        for instrument in description.instruments
        for capability in instrument.capabilities
    } >= {"play_pulse_program", "acquire_iq", "set_flux_bias"}


def test_default_quantum_wiring_runtime_commands_include_channel_bindings(
    tmp_path: Path,
) -> None:
    config = quantum_wiring_config_profile()
    compiled = compile_invocation(
        parallel_gate_set_template.bind(
            gates=(
                {
                    "control_qubit": "q0",
                    "partner_qubit": "q1",
                    "gate": "cz",
                },
            ),
            qubits=("q0", "q1"),
            couplers=("coupler-q0-q1",),
        ).scan(GATE_DURATION, [28], unit="ns")
    )
    linked = resolve_compiled_invocation(
        compiled,
        environment=build_config_environment(config),
    )
    provider = _RecordingProvider(
        QuantumLabVirtualProvider(profile=EXPERIMENT_VIRTUAL_LAB_PROFILE)
    )
    program = sc.ExperimentSystem(provider=provider).compile(linked)

    repository = sqlite_run_repository(tmp_path)
    accepted = admit_test_run(
        config=config,
        request=compiled.request,
        repository=repository,
        config_source=None,
    )
    manifest = execute_admitted_run(
        program=program,
        session=sqlite_execution_session(
            tmp_path,
            accepted.run_id,
            runs=repository,
        ),
        instrument_provider=provider,
    )

    drive = next(
        driver for driver in provider.drivers if driver.instrument_id == "drive-stack"
    )
    readout = next(
        driver for driver in provider.drivers if driver.instrument_id == "readout-stack"
    )
    drive_program = next(
        field
        for command in drive.applied_commands
        for field in command.fields
        if field.capability_id == "play_pulse_program" and field.field_path == "program"
    )
    readout_request = next(
        request
        for command in readout.collect_commands
        for request in command.requests
        if request.id == "multiplexed_iq"
    )

    assert manifest.status == "completed"
    assert [
        (binding.entity_id, binding.channel_id)
        for binding in drive_program.channel_bindings
    ] == [
        ("q0", "drive.awg0.ch1"),
        ("q1", "drive.awg0.ch2"),
    ]
    assert [
        (binding.entity_id, binding.channel_id)
        for binding in readout_request.channel_bindings
    ] == [
        ("q0", "readout.mux0"),
        ("q1", "readout.mux0"),
    ]


@dataclass
class _RecordingDriver:
    wrapped: InstrumentDriver
    instrument_id: str = field(init=False)
    implementation_id: str = field(init=False)
    implementation_version: str = field(init=False)
    applied_commands: list[InstrumentStateCommand] = field(default_factory=list)
    collect_commands: list[CollectCommand] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.instrument_id = self.wrapped.instrument_id
        self.implementation_id = self.wrapped.implementation_id
        self.implementation_version = self.wrapped.implementation_version

    def describe(self) -> InstrumentDescription:
        return self.wrapped.describe()

    def read_state(self) -> InstrumentStateSnapshot:
        return self.wrapped.read_state()

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        self.applied_commands.append(command)
        return self.wrapped.apply_state(command)

    def collect(self, command: CollectCommand) -> CollectReceipt:
        self.collect_commands.append(command)
        return self.wrapped.collect(command)

    def cleanup(self) -> None:
        return self.wrapped.cleanup()

    def abort(self) -> None:
        return self.wrapped.abort()


@dataclass
class _RecordingProvider:
    wrapped: InstrumentProvider
    drivers: list[_RecordingDriver] = field(default_factory=list)

    @property
    def provider_id(self) -> str:
        return self.wrapped.provider_id

    def describe(
        self, context: InstrumentProviderContext
    ) -> InstrumentProviderDescription:
        return self.wrapped.describe(context)

    def provide(self, context: InstrumentProviderContext) -> InstrumentProviderResult:
        result = self.wrapped.provide(context)
        self.drivers = [_RecordingDriver(driver) for driver in result.drivers]
        return InstrumentProviderResult(
            drivers=tuple(self.drivers),
            problems=result.problems,
            metadata=dict(result.metadata),
        )
