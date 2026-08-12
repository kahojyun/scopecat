from __future__ import annotations

from scopecat.compiler.bind import bind_program
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.config.environment import build_config_environment
from scopecat.execution.local.program import ApplyStateOperation, InvokeOperation
from scopecat.execution.program import RunCoverageEffect
from scopecat.planning.compilation import compile_run_program
from scopecat_testkit.instrument_host import compose_test_instruments

from reference_lab.bench_interfaces import (
    ANALOG_WAVEFORM_OUTPUT,
    AWG_SEQUENCER,
)
from reference_lab.configuration import bootstrap_config
from reference_lab.interfaces import CLOCK_REFERENCE
from reference_lab.payloads import reference_lab_payload_codecs
from reference_lab.provider import ReferenceLabProvider
from reference_lab.workflows.xy_drive import XY_LO_SWEEP


def test_xy_drive_declares_physical_i_and_q_resources_per_entity() -> None:
    logical = compile_invocation(XY_LO_SWEEP).program.program

    assert [port.id for port in logical.resource_ports] == [
        "xy_drive.lo.q0",
        "xy_drive.lo.q1",
        "xy_drive.i.q0",
        "xy_drive.i.q1",
        "xy_drive.q.q0",
        "xy_drive.q.q1",
    ]
    i_ports = logical.resource_ports[2:4]
    q_ports = logical.resource_ports[4:]
    assert all(
        port.selector.interfaces
        == (
            AWG_SEQUENCER.interface_id,
            ANALOG_WAVEFORM_OUTPUT.interface_id,
            CLOCK_REFERENCE.interface_id,
        )
        for port in (*i_ports, *q_ports)
    )
    assert all(port.selector.role.role_id == "drive-i" for port in i_ports)
    assert all(port.selector.role.role_id == "drive-q" for port in q_ports)
    assert len(logical.compute_nodes) == 4
    assert [record.id for record in logical.value_record_selections] == [
        "requested_carrier_frequency/logical_qubit/q0",
        "requested_carrier_frequency/logical_qubit/q1",
    ]


def test_xy_drive_composes_shared_awg_state_and_real_dac_operations() -> None:
    config = bootstrap_config()
    provider = ReferenceLabProvider()
    composition = compose_test_instruments(
        config=config,
        provider=provider,
        payload_codecs=reference_lab_payload_codecs(),
    )
    bound = bind_program(
        compile_invocation(XY_LO_SWEEP).program,
        build_config_environment(config),
    )
    plan = compile_run_program(composition.system, bound=bound)
    coverage = tuple(plan.coverage)
    operations = {
        effect.operation.instrument_id: effect.operation
        for effect in coverage
        if isinstance(effect, RunCoverageEffect)
        and effect.point_index == 0
        and isinstance(effect.operation, ApplyStateOperation)
    }

    lo = operations["drive-lo-a"]
    assert {target.property_id for target in lo.targets} == {
        "frequency",
        "power",
        "output_enabled",
        "reference_source",
    }
    assert all(target.component_path == () for target in lo.targets)
    assert all(len(target.origins) == 2 for target in lo.targets)
    assert all(target.entity_ids == ("q0", "q1") for target in lo.targets)

    awg = operations["drive-awg"]
    shared = [target for target in awg.targets if not target.component_path]
    outputs = [target for target in awg.targets if target.component_path]
    assert {target.property_id for target in shared} == {
        "sample_rate",
        "run_mode",
        "source",
        "frequency",
    }
    assert all(len(target.origins) == 4 for target in shared)
    assert {target.component_path for target in outputs} == {
        ("outputs", "ch1"),
        ("outputs", "ch2"),
        ("outputs", "ch3"),
        ("outputs", "ch4"),
    }
    assert len(outputs) == 12
    assert all(len(target.origins) == 1 for target in outputs)

    point_operations = [
        effect.operation
        for effect in coverage
        if isinstance(effect, RunCoverageEffect) and effect.point_index == 0
    ]
    invocations = [
        operation
        for operation in point_operations
        if isinstance(operation, InvokeOperation)
    ]
    assert [operation.instrument_id for operation in invocations] == [
        "drive-awg",
        "drive-awg",
        "drive-awg",
        "drive-awg",
    ]
    assert {operation.component_path for operation in invocations} == {
        ("outputs", "ch1"),
        ("outputs", "ch2"),
        ("outputs", "ch3"),
        ("outputs", "ch4"),
    }
    assert {operation.resource.route_role_id for operation in invocations} == {
        "drive-i",
        "drive-q",
    }
    assert all(operation.operation_id == "play" for operation in invocations)
    assert max(
        index
        for index, operation in enumerate(point_operations)
        if isinstance(operation, ApplyStateOperation)
    ) < min(
        index
        for index, operation in enumerate(point_operations)
        if isinstance(operation, InvokeOperation)
    )
