from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

import pytest
import scopecat as sc
from demo_lab_test_paths import EXPERIMENT_VIRTUAL_LAB_PROFILE
from scopecat._runtime.executor import execute_run
from scopecat.authoring import resolve_experiment
from scopecat.config_profiles import load_config_profile
from scopecat.instruments import (
    CollectCommand,
    InstrumentDescription,
    InstrumentDriver,
    InstrumentProviderContext,
    InstrumentReadback,
    InstrumentResult,
    InstrumentStateCommand,
    InstrumentStateSnapshot,
)
from scopecat.planning.validation import validate_config
from scopecat.routing import RoutingView

from quantum_lab_demo.experiments import SIMULTANEOUS_RABI_TEMPLATE
from quantum_lab_demo.experiments.background_modules import FLUX_BACKGROUND_MODULE
from quantum_lab_demo.experiments.rabi_modules import RABI_MODULE
from quantum_lab_demo.experiments.readout_modules import (
    MULTIPLEXED_READOUT_MODULE,
    READOUT_MODULE,
)
from quantum_lab_demo.experiments.two_qubit_modules import CZ_CHEVRON_MODULE
from quantum_lab_demo.fixtures import EXPERIMENT_FIXTURE_DIR
from quantum_lab_demo.lab import quantum_lab
from quantum_lab_demo.virtual_lab.provider import QuantumLabVirtualProvider
from quantum_lab_demo.virtual_lab.wiring import (
    compile_quantum_wiring_system,
    quantum_wiring,
    quantum_wiring_config_profile,
)


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
    drive = routing.route(
        port_id="drive",
        capabilities=("play_pulse_program",),
        entity_ids=("q0",),
    )
    readout = routing.route(
        port_id="readout",
        capabilities=("acquire_iq",),
        entity_ids=("q0",),
    )

    assert drive.resource_id == "drive-stack"
    assert [
        (binding.entity_id, binding.line_id, binding.channel_id, binding.group_ids)
        for binding in drive.channel_bindings
    ] == [("q0", "q0.xy", "drive.awg0.ch1", ["lo.xy0"])]
    assert readout.resource_id == "readout-stack"
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
    drive_binding = routing.route(
        port_id="drive",
        capabilities=("play_pulse_program",),
        entity_ids=("q0", "q1"),
    )
    readout_binding = routing.route(
        port_id="readout",
        capabilities=("acquire_iq",),
        entity_ids=("q0", "q1"),
    )

    assert drive_binding.resource_id == "drive-stack"
    assert [
        (binding.entity_id, binding.line_id, binding.channel_id, binding.group_ids)
        for binding in drive_binding.channel_bindings
    ] == [
        ("q0", "q0.xy", "drive.awg0.ch1", ["lo.xy0"]),
        ("q1", "q1.xy", "drive.awg0.ch2", ["lo.xy0"]),
    ]
    assert readout_binding.resource_id == "readout-stack"
    assert [
        (binding.entity_id, binding.line_id, binding.channel_id, binding.group_ids)
        for binding in readout_binding.channel_bindings
    ] == [
        ("q0", "ro.mux0", "readout.mux0", ["lo.ro0"]),
        ("q1", "ro.mux0", "readout.mux0", ["lo.ro0"]),
    ]


def test_workspace_system_summary_describes_default_quantum_wiring(tmp_path) -> None:
    lab = sc.open(tmp_path, config_profile=quantum_wiring_config_profile())

    summary = lab.system()
    q0 = next(entity for entity in summary.entities if entity.id == "q0")
    readout_line = next(line for line in summary.lines if line.id == "ro.mux0")
    readout_channel = next(
        channel for channel in summary.channels if channel.id == "readout.mux0"
    )
    drive_lo = next(group for group in summary.groups if group.id == "lo.xy0")
    readout_lo = next(group for group in summary.groups if group.id == "lo.ro0")
    drive_resource = next(
        resource for resource in summary.resources if resource.id == "drive-stack"
    )

    assert summary.entity_count == 6
    assert q0.lines == ("q0.xy", "ro.mux0")
    assert q0.channels == ("drive.awg0.ch1", "readout.mux0")
    assert q0.resources == ("drive-stack", "readout-stack")
    assert readout_line.endpoints == (
        "q0",
        "q1",
        "q2",
        "q3",
        "readout-stack",
    )
    assert readout_line.groups == ("lo.ro0",)
    assert readout_channel.resources == ("readout-stack",)
    assert readout_channel.max_route_ports_per_point == 1
    assert drive_lo.channels == ("drive.awg0.ch1", "drive.awg0.ch2")
    assert drive_lo.max_resources_per_point == 1
    assert drive_lo.resources == ("drive-stack",)
    assert drive_lo.entities == ("q0", "q1")
    assert drive_lo.capabilities == ("play_gate_sequence", "play_pulse_program")
    assert drive_lo.binding_count == 4
    assert readout_lo.channels == ("readout.mux0",)
    assert readout_lo.resources == ("readout-stack",)
    assert readout_lo.entities == ("q0", "q1", "q2", "q3")
    assert readout_lo.capabilities == (
        "acquire_iq",
        "readout_pulse",
        "submit_backend_batch",
    )
    assert readout_lo.binding_count == 12
    assert drive_resource.binding_count == 8


def test_modules_leave_resource_selection_to_routing() -> None:
    modules = [
        RABI_MODULE(qubit="q0", drive_length=20),
        READOUT_MODULE(qubit="q0", readout_frequency=6.6),
        FLUX_BACKGROUND_MODULE(coupler="coupler-q0-q1", flux_bias=0.02),
        CZ_CHEVRON_MODULE(
            control_qubit="q0",
            partner_qubit="q1",
            coupler="coupler-q0-q1",
            coupler_duration=24,
            coupler_amplitude=0.18,
        ),
        MULTIPLEXED_READOUT_MODULE(qubits=["q0", "q1"]),
    ]

    for module in modules:
        assembly = module.assemble()

        assert assembly.resource_ports
        assert all(not hasattr(port, "resource_id") for port in assembly.resource_ports)


def test_default_quantum_wiring_preview_includes_resolved_channel_routes(
    tmp_path,
) -> None:
    preview = quantum_lab(
        workspace=tmp_path,
        config_profile=quantum_wiring_config_profile(),
    ).preview(SIMULTANEOUS_RABI_TEMPLATE.bind(qubits=sc.entity_array(("q0", "q1"))))

    drive = next(route for route in preview.routes if route.port_id == "drive")
    readout = next(route for route in preview.routes if route.port_id == "readout")

    assert [
        (binding.line_id, binding.channel_id)
        for binding in drive.resolved[0].channel_bindings
    ] == [
        ("q0.xy", "drive.awg0.ch1"),
        ("q1.xy", "drive.awg0.ch2"),
    ]
    assert [
        (binding.line_id, binding.channel_id)
        for binding in readout.resolved[0].channel_bindings
    ] == [
        ("ro.mux0", "readout.mux0"),
        ("ro.mux0", "readout.mux0"),
    ]


def test_default_quantum_wiring_runtime_commands_include_channel_bindings(
    tmp_path,
) -> None:
    config = quantum_wiring_config_profile()
    resolved = resolve_experiment(
        SIMULTANEOUS_RABI_TEMPLATE.bind(qubits=sc.entity_array(("q0", "q1"))),
        workspace=tmp_path,
        config_profile=config,
    )
    provider_result = QuantumLabVirtualProvider(
        profile=EXPERIMENT_VIRTUAL_LAB_PROFILE
    ).provide(InstrumentProviderContext(config=config))
    drivers = [_RecordingDriver(driver) for driver in provider_result.drivers]

    manifest, _snapshot = execute_run(
        config=config,
        experiment=resolved.experiment,
        parameter_view=resolved.parameter_view,
        parameter_derivations=resolved.parameter_derivations,
        instruments=cast("list[InstrumentDriver]", drivers),
        workspace=tmp_path,
    )

    drive = next(driver for driver in drivers if driver.instrument_id == "drive-stack")
    readout = next(
        driver for driver in drivers if driver.instrument_id == "readout-stack"
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
    applied_commands: list[InstrumentStateCommand] = field(default_factory=list)
    collect_commands: list[CollectCommand] = field(default_factory=list)

    @property
    def instrument_id(self) -> str:
        return self.wrapped.instrument_id

    @property
    def implementation_id(self) -> str:
        return self.wrapped.implementation_id

    @property
    def implementation_version(self) -> str:
        return self.wrapped.implementation_version

    def describe(self) -> InstrumentDescription:
        return self.wrapped.describe()

    def read_state(self) -> InstrumentStateSnapshot:
        return self.wrapped.read_state()

    def apply_state(self, command: InstrumentStateCommand) -> InstrumentResult:
        self.applied_commands.append(command)
        return self.wrapped.apply_state(command)

    def collect(self, command: CollectCommand) -> InstrumentReadback:
        self.collect_commands.append(command)
        return self.wrapped.collect(command)

    def cleanup(self) -> None:
        return self.wrapped.cleanup()

    def abort(self) -> None:
        return self.wrapped.abort()
