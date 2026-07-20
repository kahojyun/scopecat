from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest
import scopecat as sc
from scopecat.compiler.linking.linked import (
    link_verified_program,
    specialize_linked_program,
)
from scopecat.composition.local import local_execution_services
from scopecat.config.profiles import load_config_profile
from scopecat.execution.interpreter import interpret_run_program
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.planning.authoring import resolve_experiment
from scopecat.planning.routing import RoutingView
from scopecat.planning.validation import validate_config
from scopecat.sdk.instruments import (
    ActionReceipt,
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    InstrumentActionCommand,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProvider,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateCommand,
    InstrumentStateSnapshot,
)

from quantum_lab_demo.experiments import SIMULTANEOUS_RABI_TEMPLATE
from quantum_lab_demo.fixtures import EXPERIMENT_FIXTURE_DIR
from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider
from quantum_lab_demo.virtual_lab.wiring import (
    compile_quantum_wiring_system,
    quantum_wiring,
    quantum_wiring_config_profile,
)

from .demo_lab_test_paths import EXPERIMENT_VIRTUAL_LAB_PROFILE


def test_quantum_wiring_builder_compiles_lab_vocabulary_to_core_config() -> None:
    base = load_config_profile(EXPERIMENT_FIXTURE_DIR / "config-profile.json")
    wiring = (
        quantum_wiring()
        .drive_line(
            "q0.xy",
            instrument="drive-stack",
            channel="drive.awg0.ch1",
            port="awg0.ch1",
            shared_lo="lo.xy0",
        )
        .readout_line(
            "ro.mux0",
            instrument="readout-stack",
            channel="readout.mux0",
            port="ro0",
            shared_lo="lo.ro0",
        )
        .qubit("q0", drive="q0.xy", readout="ro.mux0")
        .build()
    )
    config = base.model_copy(
        update={"system": compile_quantum_wiring_system(base.system, wiring)}
    )

    assert not validate_config(config)
    assert [(entity.id, entity.kind) for entity in config.topology.entities] == [
        ("q0", "logical_qubit")
    ]
    topology_lines = [
        (line.id, line.signal, line.endpoints) for line in config.topology.lines
    ]
    assert topology_lines == [
        ("q0.xy", "drive", ["q0", "drive-stack"]),
        ("ro.mux0", "readout", ["q0", "readout-stack"]),
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
        (binding.entity_id, binding.line_id, binding.channel_id, binding.group_ids)
        for binding in drive.channel_bindings
    ] == [("q0", "q0.xy", "drive.awg0.ch1", ["lo.xy0"])]
    assert readout.instrument_id == "readout-stack"
    assert [
        (binding.entity_id, binding.line_id, binding.channel_id, binding.group_ids)
        for binding in readout.channel_bindings
    ] == [("q0", "ro.mux0", "readout.mux0", ["lo.ro0"])]


def test_quantum_wiring_builder_rejects_unknown_line_references() -> None:
    builder = quantum_wiring().qubit("q0", drive="missing.xy", readout="ro.mux0")

    with pytest.raises(ValueError, match=r"unknown drive line 'missing\.xy'"):
        builder.build()


def test_quantum_wiring_builder_rejects_unknown_coupler_qubits() -> None:
    builder = (
        quantum_wiring()
        .coupler_flux_line("c01.z", instrument="coupler-stack", channel="bias0")
        .coupler("coupler-q0-q1", qubits=("q0", "q1"), flux="c01.z")
    )

    with pytest.raises(ValueError, match="references unknown qubit 'q0'"):
        builder.build()


def test_default_quantum_wiring_config_describes_lines_groups_and_channel_routes() -> (
    None
):
    config = quantum_wiring_config_profile()

    assert not validate_config(config)
    assert {line.id for line in config.topology.lines} >= {
        "q0.xy",
        "q1.xy",
        "ro.mux0",
        "c01.z",
    }
    assert {group.id for group in config.topology.groups} >= {"lo.xy0", "lo.ro0"}

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
        (binding.entity_id, binding.line_id, binding.channel_id, binding.group_ids)
        for binding in drive_binding.channel_bindings
    ] == [
        ("q0", "q0.xy", "drive.awg0.ch1", ["lo.xy0"]),
        ("q1", "q1.xy", "drive.awg0.ch2", ["lo.xy0"]),
    ]
    assert readout_binding.instrument_id == "readout-stack"
    assert [
        (binding.entity_id, binding.line_id, binding.channel_id, binding.group_ids)
        for binding in readout_binding.channel_bindings
    ] == [
        ("q0", "ro.mux0", "readout.mux0", ["lo.ro0"]),
        ("q1", "ro.mux0", "readout.mux0", ["lo.ro0"]),
    ]


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
    resolved = resolve_experiment(
        SIMULTANEOUS_RABI_TEMPLATE.bind(qubits=("q0", "q1")),
        config_profile=config,
    )
    provider = _RecordingProvider(
        QuantumLabVirtualProvider(profile=EXPERIMENT_VIRTUAL_LAB_PROFILE)
    )
    linked = specialize_linked_program(
        link_verified_program(resolved.verified_program, resolved.environment)
    )
    program = sc.ExperimentSystem(provider=provider).compile(linked, config=config)

    manifest = interpret_run_program(
        config=config,
        program=program,
        request=resolved.request,
        services=local_execution_services(tmp_path),
        instrument_provider=provider,
        config_source=resolved.config_source,
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
        (binding.entity_id, binding.line_id, binding.channel_id, binding.group_ids)
        for binding in drive_program.channel_bindings
    ] == [
        ("q0", "q0.xy", "drive.awg0.ch1", ["lo.xy0"]),
        ("q1", "q1.xy", "drive.awg0.ch2", ["lo.xy0"]),
    ]
    assert [
        (binding.entity_id, binding.line_id, binding.channel_id, binding.group_ids)
        for binding in readout_request.channel_bindings
    ] == [
        ("q0", "ro.mux0", "readout.mux0", ["lo.ro0"]),
        ("q1", "ro.mux0", "readout.mux0", ["lo.ro0"]),
    ]


@dataclass
class _RecordingDriver:
    wrapped: InstrumentDriver
    instrument_id: str = field(init=False)
    implementation_id: str = field(init=False)
    implementation_version: str = field(init=False)
    applied_commands: list[InstrumentStateCommand] = field(default_factory=list)
    action_commands: list[InstrumentActionCommand] = field(default_factory=list)
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

    def action(self, command: InstrumentActionCommand) -> ActionReceipt:
        self.action_commands.append(command)
        return self.wrapped.action(command)

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
