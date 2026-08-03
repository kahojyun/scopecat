from __future__ import annotations

# pyright: reportPrivateUsage=false
from typing import assert_type

import pytest
from scopecat.authoring import (
    EntityType,
    ExperimentContext,
    IntType,
    ModuleContext,
    PerEntity,
    ProductRef,
    ScalarType,
    coordinate,
    each,
    module,
    one,
    template,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.program.bindings import EnsureStateIntent, InvocationIntent
from scopecat.program.expressions import LiteralScalarExpr
from scopecat.program.module import ModuleAcquireEffect

from scopecat_instruments import (
    DCMonitorCurrentProducts,
    DCMonitorGroupTarget,
    DCMonitorTarget,
    DCMonitorVoltageProducts,
    DCSourceGroupTarget,
    DCSourceTarget,
    NetworkSweepProducts,
    NetworkSweepTarget,
    RFOutputGroupTarget,
    RFOutputTarget,
    SymbolicDCSourceClient,
    SymbolicDCSourceGroup,
    SymbolicDCSourceMonitorClient,
    SymbolicDCSourceMonitorGroup,
    SymbolicNetworkSweepClient,
    SymbolicNetworkSweepGroup,
    SymbolicRFOutputClient,
    SymbolicRFOutputGroup,
    SymbolicTemperatureReadoutClient,
    SymbolicTemperatureReadoutGroup,
    TemperatureSampleProducts,
    dc_source,
    dc_source_monitor,
    network_sweep,
    rf_output,
    temperature_readout,
)
from scopecat_instruments.members import (
    DC_MONITOR,
    DC_SOURCE,
    NETWORK_SWEEP,
    RF_OUTPUT,
    TEMPERATURE_READOUT,
)


def test_factories_bind_typed_symbolic_clients_and_declare_resources() -> None:
    context = ModuleContext()
    qubit = coordinate("qubit", ScalarType(EntityType(entity_kind="qubit")))

    source = dc_source(context, "flux", for_=one(qubit))
    rf = rf_output(context, "drive")
    vna = network_sweep(context, "readout")
    thermometer = temperature_readout(context, "temperature")

    assert_type(source, SymbolicDCSourceClient)
    assert_type(rf, SymbolicRFOutputClient)
    assert_type(vna, SymbolicNetworkSweepClient)
    assert_type(thermometer, SymbolicTemperatureReadoutClient)
    interface, _, _ = context.close_experiment_parts_internal()
    assert [resource.id for resource in interface.resources] == [
        "flux",
        "drive",
        "readout",
        "temperature",
    ]
    assert [resource.selector.interfaces for resource in interface.resources] == [
        (DC_SOURCE.interface_id,),
        (RF_OUTPUT.interface_id,),
        (NETWORK_SWEEP.interface_id,),
        (TEMPERATURE_READOUT.interface_id,),
    ]
    assert interface.resources[0].selector.entity_inputs == (qubit,)


def test_explicit_dc_source_factories_cover_scalar_and_group() -> None:
    context = ModuleContext()
    q0 = EntityRef(id="q0", kind="logical_device")
    selection = each(q0)

    scalar = dc_source(context, "scalar")
    scalar_monitor = dc_source_monitor(context, "scalar-monitor")
    group = dc_source(context, "group", for_=selection)
    group_monitor = dc_source_monitor(
        context,
        "group-monitor",
        for_=selection,
    )

    assert_type(scalar, SymbolicDCSourceClient)
    assert_type(scalar_monitor, SymbolicDCSourceMonitorClient)
    assert_type(group, SymbolicDCSourceGroup)
    assert_type(group_monitor, SymbolicDCSourceMonitorGroup)

    interface, _, _ = context.close_experiment_parts_internal()
    assert [resource.selector.interfaces for resource in interface.resources] == [
        (DC_SOURCE.interface_id,),
        (DC_SOURCE.interface_id, DC_MONITOR.interface_id),
        (DC_SOURCE.interface_id,),
        (DC_SOURCE.interface_id, DC_MONITOR.interface_id),
    ]


def test_one_concrete_entity_lowers_to_one_literal_entity_input() -> None:
    context = ModuleContext()
    q0 = EntityRef(id="q0", kind="logical_device")

    source = dc_source(context, "flux", for_=one(q0))

    assert_type(source, SymbolicDCSourceClient)
    interface, _, _ = context.close_experiment_parts_internal()
    [entity_input] = interface.resources[0].selector.entity_inputs
    assert isinstance(entity_input.source, LiteralScalarExpr)
    assert entity_input.source.value == q0


def test_each_expands_into_single_entity_resources_and_unique_acquisitions() -> None:
    context = ModuleContext()
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")

    analyzers = network_sweep(context, "readout", for_=each(q0, q1))
    assert_type(analyzers, SymbolicNetworkSweepGroup)
    assert analyzers.entities == (q0, q1)
    assert analyzers[q0] is analyzers.clients[q0]
    analyzers.ensure(points=11)
    traces = analyzers.sweep()

    assert_type(traces, PerEntity[NetworkSweepProducts])
    definition = context.close_definition_internal(id="test.symbolic.each")
    resources = definition.interface.resources
    assert len(resources) == 2
    assert all(
        resource.id.startswith("readout.logical-device-q") for resource in resources
    )
    assert len({resource.id for resource in resources}) == 2
    for resource, entity in zip(resources, (q0, q1), strict=True):
        [entity_input] = resource.selector.entity_inputs
        assert isinstance(entity_input.source, LiteralScalarExpr)
        assert entity_input.source.value == entity

    acquisitions = tuple(
        effect
        for effect in definition.body.effects
        if isinstance(effect, ModuleAcquireEffect)
    )
    assert len(acquisitions) == 2
    assert len({effect.id for effect in acquisitions}) == 2
    assert len(definition.body.products) == 4
    assert len({product.qualified_id for product in definition.body.products}) == 4
    for entity in (q0, q1):
        trace = traces[entity]
        assert trace.frequency.id.startswith(analyzers[entity].id)
        assert trace.s_parameter.id.startswith(analyzers[entity].id)


def test_group_sweep_uses_entity_aligned_output_shape_state() -> None:
    context = ModuleContext()
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    analyzers = network_sweep(context, "readout", for_=each(q0, q1))
    points_by_entity: PerEntity[int] = PerEntity(
        (
            (q1, 17),
            (q0, 5),
        )
    )

    analyzers.ensure(points=points_by_entity)
    traces = analyzers.sweep()

    definition = context.close_definition_internal(id="test.symbolic.each-shape")
    products = {product.qualified_id: product for product in definition.body.products}
    for entity, points in ((q0, 5), (q1, 17)):
        trace = traces[entity]
        assert products[trace.frequency.id].axes[0].size == points
        assert products[trace.s_parameter.id].axes[0].size == points


def test_each_factories_keep_the_typed_interface_specific_group_verbs() -> None:
    context = ModuleContext()
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    selection = each(q0, q1)

    outputs = rf_output(context, "drive", for_=selection)
    thermometers = temperature_readout(context, "temperature", for_=selection)
    assert_type(outputs, SymbolicRFOutputGroup)
    assert_type(thermometers, SymbolicTemperatureReadoutGroup)
    outputs.ensure(RFOutputGroupTarget(output_enabled=False))
    samples = thermometers.sample()

    assert_type(samples, PerEntity[TemperatureSampleProducts])
    assert tuple(samples) == (q0, q1)


def test_dc_group_broadcasts_and_aligns_typed_operation_arguments() -> None:
    context = ModuleContext()
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    biases = dc_source(context, "flux", for_=each(q0, q1))
    assert_type(biases, SymbolicDCSourceGroup)
    biases.source_voltage(
        range=Quantity(1, "V"),
        level=Quantity(0.01, "V"),
    )
    current_ranges = assert_type(
        PerEntity(
            (
                (q1, Quantity(2, "A")),
                (q0, Quantity(1, "A")),
            )
        ),
        PerEntity[Quantity],
    )
    current_levels = assert_type(
        PerEntity(
            (
                (q1, Quantity(0.03, "A")),
                (q0, Quantity(0.02, "A")),
            )
        ),
        PerEntity[Quantity],
    )
    biases.source_current(range=current_ranges, level=current_levels)

    definition = context.close_definition_internal(id="test.symbolic.dc-each")
    invocations = tuple(
        effect
        for effect in definition.body.effects
        if isinstance(effect, InvocationIntent)
    )
    assert [effect.operation_id for effect in invocations] == [
        "source_voltage",
        "source_voltage",
        "source_current",
        "source_current",
    ]
    assert [
        [argument.value for argument in effect.arguments] for effect in invocations
    ] == [
        [Quantity(1, "V"), Quantity(0.01, "V")],
        [Quantity(1, "V"), Quantity(0.01, "V")],
        [Quantity(1, "A"), Quantity(0.02, "A")],
        [Quantity(2, "A"), Quantity(0.03, "A")],
    ]


def test_generated_rf_group_aligns_state_and_finalization() -> None:
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")

    @template(id="test.symbolic.generated-rf-state", kind="symbolic_root")
    def experiment(context: ExperimentContext) -> None:
        outputs = rf_output(context, "drive", for_=each(q0, q1))
        assert_type(outputs, SymbolicRFOutputGroup)
        outputs.ensure(
            PerEntity(
                (
                    (q1, RFOutputTarget(output_enabled=True)),
                    (q0, RFOutputTarget(output_enabled=False)),
                )
            )
        )
        context.finalize(outputs, RFOutputGroupTarget(output_enabled=False))

    definition = experiment.definition
    ensures = tuple(
        effect
        for effect in definition.body.effects
        if isinstance(effect, EnsureStateIntent)
    )
    assert [effect.assignments[0].value for effect in ensures] == [False, True]
    assert definition.final_state is not None
    assert [assignment.value for assignment in definition.final_state.assignments] == [
        False,
        False,
    ]


def test_group_target_lifts_each_field_independently() -> None:
    context = ModuleContext()
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    outputs = rf_output(context, "drive", for_=each(q0, q1))

    outputs.ensure(
        RFOutputGroupTarget(
            power=Quantity(-20, "dBm"),
            output_enabled=PerEntity(((q1, True), (q0, False))),
        )
    )

    definition = context.close_definition_internal(id="test.symbolic.field-lift")
    ensures = tuple(
        effect
        for effect in definition.body.effects
        if isinstance(effect, EnsureStateIntent)
    )
    assert len(ensures) == 2
    assert [assignment.value for assignment in ensures[0].assignments] == [
        Quantity(-20, "dBm"),
        False,
    ]
    assert [assignment.value for assignment in ensures[1].assignments] == [
        Quantity(-20, "dBm"),
        True,
    ]


def test_group_per_entity_operation_argument_requires_exact_identity_join() -> None:
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    wrong_q1 = EntityRef(id="q1", kind="logical_coupler")
    biases = dc_source(ModuleContext(), "flux", for_=each(q0, q1))
    levels = PerEntity(
        (
            (q0, Quantity(0.01, "V")),
            (wrong_q1, Quantity(0.02, "V")),
        )
    )

    with pytest.raises(
        ValueError,
        match=(
            r"exactly match.*missing logical_device:q1; "
            r"extra logical_coupler:q1"
        ),
    ):
        biases.source_voltage(range=Quantity(1, "V"), level=levels)


def test_symbolic_products_record_directly_from_a_root_experiment() -> None:
    @template(id="test.symbolic.root", kind="symbolic_root")
    def experiment(context: ExperimentContext) -> None:
        vna = network_sweep(context, "readout")
        vna.ensure(points=11)
        trace = vna.sweep()
        context.record(trace)

    definition = experiment.definition
    assert [product.id for product in definition.body.products] == [
        "frequency",
        "s_parameter",
    ]
    assert [
        selection.product_id.qualified_name
        for selection in definition.record_selections
    ] == ["readout/frequency", "readout/s_parameter"]
    assert [selection.record_id for selection in definition.record_selections] == [
        "readout/frequency",
        "readout/s_parameter",
    ]
    assert [selection.role for selection in definition.record_selections] == [
        "coordinate",
        "observable",
    ]
    assert {
        selection.recording_group_id for selection in definition.record_selections
    } == {"readout/sweep"}


def test_record_namespace_prefixes_typed_variables_and_their_group() -> None:
    context = ExperimentContext()
    vna = network_sweep(context, "readout")
    vna.ensure(points=11)

    context.record(vna.sweep(), namespace="calibration")

    definition = context.close_definition_internal(
        id="test.symbolic.record-namespace",
        kind="test",
        metadata=None,
        input_defaults={},
        required_inputs=(),
    )
    assert [selection.record_id for selection in definition.record_selections] == [
        "calibration/readout/frequency",
        "calibration/readout/s_parameter",
    ]
    assert {
        selection.recording_group_id for selection in definition.record_selections
    } == {"calibration/readout/sweep"}


def test_typed_result_members_keep_their_declared_recording_roles() -> None:
    context = ExperimentContext()
    vna = network_sweep(context, "readout")
    vna.ensure(points=11)

    trace = vna.sweep()
    context.record(trace.frequency, trace.s_parameter)

    definition = context.close_definition_internal(
        id="test.symbolic.record-members",
        kind="test",
        metadata=None,
        input_defaults={},
        required_inputs=(),
    )
    assert [selection.role for selection in definition.record_selections] == [
        "coordinate",
        "observable",
    ]
    assert {
        selection.recording_group_id for selection in definition.record_selections
    } == {"readout/sweep"}


def test_typed_result_recording_semantics_survive_a_module_boundary() -> None:
    @module(id="test.symbolic.sweep-module")
    def sweep_module(context: ModuleContext) -> NetworkSweepProducts:
        vna = network_sweep(context, "readout")
        vna.ensure(points=11)
        return vna.sweep()

    call = sweep_module.instantiate("segment")
    frequency = call.products.frequency

    context = ExperimentContext()
    context.run(call)
    context.record(frequency)
    definition = context.close_definition_internal(
        id="test.symbolic.record-module-member",
        kind="test",
        metadata=None,
        input_defaults={},
        required_inputs=(),
    )
    assert [selection.role for selection in definition.record_selections] == [
        "coordinate"
    ]
    assert [
        selection.recording_group_id for selection in definition.record_selections
    ] == ["segment/readout/sweep"]


def test_per_entity_symbolic_results_record_as_dataset_fragments() -> None:
    context = ExperimentContext()
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    analyzers = network_sweep(context, "readout", for_=each(q0, q1))
    analyzers.ensure(points=5)

    traces = analyzers.sweep()
    assert_type(traces, PerEntity[NetworkSweepProducts])
    context.record(traces, namespace="calibration")

    definition = context.close_definition_internal(
        id="test.symbolic.record-each",
        kind="test",
        metadata=None,
        input_defaults={},
        required_inputs=(),
    )
    assert [selection.role for selection in definition.record_selections] == [
        "coordinate",
        "observable",
        "coordinate",
        "observable",
    ]
    record_ids = [selection.record_id for selection in definition.record_selections]
    assert len(set(record_ids)) == 4
    assert all(
        record_id is not None and record_id.startswith("calibration/readout.")
        for record_id in record_ids
    )
    assert record_ids[0] is not None and record_ids[0].endswith("/frequency")
    assert record_ids[1] is not None and record_ids[1].endswith("/s_parameter")
    assert record_ids[2] is not None and record_ids[2].endswith("/frequency")
    assert record_ids[3] is not None and record_ids[3].endswith("/s_parameter")
    recording_group_ids = [
        selection.recording_group_id for selection in definition.record_selections
    ]
    assert len(set(recording_group_ids)) == 2
    assert recording_group_ids[0] == recording_group_ids[1]
    assert recording_group_ids[2] == recording_group_ids[3]
    assert all(
        group_id is not None and group_id.startswith("calibration/readout.")
        for group_id in recording_group_ids
    )


def test_root_finalization_accepts_a_typed_symbolic_client_and_declared_state() -> None:
    @template(id="test.symbolic.typed-finalization", kind="symbolic_root")
    def experiment(context: ExperimentContext) -> None:
        source = dc_source(context, "flux")
        context.finalize(source, DCSourceTarget(output_enabled=False))

    definition = experiment.definition
    assert definition.final_state is not None
    [assignment] = definition.final_state.assignments
    [resource] = definition.interface.resources
    assert assignment.port_id == resource.symbol_id
    assert assignment.property_id == "output_enabled"
    assert assignment.value is False


@pytest.mark.parametrize("per_entity", [False, True])
def test_root_finalization_accepts_group_broadcast_and_per_entity_state(
    *,
    per_entity: bool,
) -> None:
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")

    @template(
        id=f"test.symbolic.typed-group-finalization.{per_entity}",
        kind="symbolic_root",
    )
    def experiment(context: ExperimentContext) -> None:
        sources = dc_source(context, "flux", for_=each(q0, q1))
        target: DCSourceGroupTarget | PerEntity[DCSourceTarget]
        if per_entity:
            target = PerEntity(
                (
                    (q1, DCSourceTarget(output_enabled=True)),
                    (q0, DCSourceTarget(output_enabled=False)),
                )
            )
        else:
            target = DCSourceGroupTarget(output_enabled=False)
        context.finalize(sources, target)

    definition = experiment.definition
    assert definition.final_state is not None
    assert [
        assignment.port_id for assignment in definition.final_state.assignments
    ] == [resource.symbol_id for resource in definition.interface.resources]
    assert [assignment.value for assignment in definition.final_state.assignments] == (
        [False, True] if per_entity else [False, False]
    )


def test_two_scalar_clients_use_distinct_structured_product_scopes() -> None:
    context = ModuleContext()
    left = network_sweep(context, "left")
    right = network_sweep(context, "right")
    left.ensure(NetworkSweepTarget(points=3))
    right.ensure(NetworkSweepTarget(points=3))

    left_trace = left.sweep()
    right_trace = right.sweep()

    definition = context.close_definition_internal(id="test.symbolic.scopes")
    assert len({product.qualified_id for product in definition.body.products}) == 4
    assert left_trace.s_parameter.id == "left/s_parameter"
    assert right_trace.s_parameter.id == "right/s_parameter"


def test_state_clients_record_typed_state_and_operation_effects() -> None:
    context = ModuleContext()
    source = dc_source(context, "flux")
    rf = rf_output(context, "drive")

    source.ensure(
        DCSourceTarget(
            current_protection=Quantity(100.0, "uA"),
            output_enabled=True,
        )
    )
    source.source_voltage(
        range=Quantity(1.0, "V"),
        level=Quantity(0.05, "V"),
    )
    rf.ensure(
        RFOutputTarget(
            frequency=Quantity(5.0, "GHz"),
            power=Quantity(-20.0, "dBm"),
            output_enabled=True,
        )
    )

    definition = context.close_definition_internal(id="test.symbolic.state")
    assert len(definition.body.effects) == 3
    assert isinstance(definition.body.effects[0], EnsureStateIntent)
    assert isinstance(definition.body.effects[1], InvocationIntent)
    assert isinstance(definition.body.effects[2], EnsureStateIntent)
    assert [
        len(effect.assignments)
        for effect in definition.body.effects
        if isinstance(effect, EnsureStateIntent)
    ] == [2, 3]
    [invocation] = definition.body.invocations
    assert invocation.operation_id == "source_voltage"
    assert [argument.value for argument in invocation.arguments] == [
        Quantity(1.0, "V"),
        Quantity(0.05, "V"),
    ]


def test_dc_monitor_exposes_independent_fixed_result_acquisitions() -> None:
    context = ModuleContext()
    source = dc_source_monitor(context, "flux")
    assert_type(source, SymbolicDCSourceMonitorClient)
    source.ensure(DCSourceTarget(output_enabled=True))
    source.source_voltage(
        range=Quantity(1.0, "V"),
        level=Quantity(0.05, "V"),
    )
    source.ensure(DCMonitorTarget(measurement_enabled=True))

    current = source.measure_current()
    voltage = source.measure_voltage()

    assert_type(current, DCMonitorCurrentProducts)
    assert_type(current.current, ProductRef)
    assert_type(voltage, DCMonitorVoltageProducts)
    assert_type(voltage.voltage, ProductRef)
    definition = context.close_definition_internal(id="test.symbolic.dc-monitor")
    assert [product.id for product in definition.body.products] == [
        "monitored_current",
        "monitored_voltage",
    ]
    acquisitions = definition.body.effects[-2:]
    assert all(isinstance(effect, ModuleAcquireEffect) for effect in acquisitions)
    assert [
        [result.result_id for result in effect.results]
        for effect in acquisitions
        if isinstance(effect, ModuleAcquireEffect)
    ] == [["monitored_current"], ["monitored_voltage"]]


def test_dc_monitor_acquisition_does_not_require_symbolic_source_state() -> None:
    source = dc_source_monitor(ModuleContext(), "flux")

    assert_type(source.measure_current(), DCMonitorCurrentProducts)
    assert_type(source.measure_voltage(), DCMonitorVoltageProducts)


def test_dc_monitor_selection_is_a_static_symbolic_capability_boundary() -> None:
    context = ModuleContext()
    source = dc_source(context, "flux")
    monitor = dc_source_monitor(context, "meter")

    assert_type(source, SymbolicDCSourceClient)
    assert_type(monitor, SymbolicDCSourceMonitorClient)
    assert not hasattr(source, "measure_current")
    assert not hasattr(source, "measure_voltage")
    assert hasattr(monitor, "measure_current")
    assert hasattr(monitor, "measure_voltage")

    interface, _, _ = context.close_experiment_parts_internal()
    assert interface.resources[0].selector.interfaces == (DC_SOURCE.interface_id,)
    assert interface.resources[1].selector.interfaces == (
        DC_SOURCE.interface_id,
        DC_MONITOR.interface_id,
    )


def test_dc_monitor_group_selection_retains_monitor_verbs() -> None:
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")

    sources = dc_source_monitor(
        ModuleContext(),
        "flux",
        for_=each(q0, q1),
    )

    assert_type(sources, SymbolicDCSourceMonitorGroup)
    assert_type(sources[q0], SymbolicDCSourceMonitorClient)
    assert hasattr(sources, "measure_current")
    assert hasattr(sources, "measure_voltage")


def test_dc_monitor_group_maps_each_fixed_acquisition_per_entity() -> None:
    context = ModuleContext()
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    sources = dc_source_monitor(
        context,
        "flux",
        for_=each(q0, q1),
    )
    sources.source_voltage(
        range=PerEntity(
            (
                (q1, Quantity(2.0, "V")),
                (q0, Quantity(1.0, "V")),
            )
        ),
        level=PerEntity(
            (
                (q1, Quantity(0.02, "V")),
                (q0, Quantity(0.03, "V")),
            )
        ),
    )
    sources.ensure(DCMonitorGroupTarget(measurement_enabled=True))

    current_samples = sources.measure_current()
    voltage_samples = sources.measure_voltage()

    assert_type(current_samples, PerEntity[DCMonitorCurrentProducts])
    assert_type(voltage_samples, PerEntity[DCMonitorVoltageProducts])
    assert isinstance(current_samples[q0].current, ProductRef)
    assert isinstance(current_samples[q1].current, ProductRef)
    assert isinstance(voltage_samples[q0].voltage, ProductRef)
    assert isinstance(voltage_samples[q1].voltage, ProductRef)
    definition = context.close_definition_internal(
        id="test.symbolic.dc-monitor-each-acquisitions"
    )
    assert [product.id for product in definition.body.products] == [
        "monitored_current",
        "monitored_current",
        "monitored_voltage",
        "monitored_voltage",
    ]


def test_network_sweep_declares_contract_products_and_ensured_points() -> None:
    context = ModuleContext()
    vna = network_sweep(context, "readout")
    vna.ensure(
        NetworkSweepTarget(
            start_frequency=Quantity(4.9, "GHz"),
            stop_frequency=Quantity(5.1, "GHz"),
            points=337,
            s_parameter="S21",
        )
    )

    trace = vna.sweep()

    assert_type(trace, NetworkSweepProducts)
    assert_type(trace.frequency, ProductRef)
    assert_type(trace.s_parameter, ProductRef)
    definition = context.close_definition_internal(id="test.symbolic.sweep")
    assert [product.id for product in definition.body.products] == [
        "frequency",
        "s_parameter",
    ]
    assert [product.dtype for product in definition.body.products] == [
        "float64",
        "complex128",
    ]
    assert [product.unit for product in definition.body.products] == ["Hz", "ratio"]
    assert [product.axes[0].size for product in definition.body.products] == [337, 337]
    assert [product.axes[0].kind for product in definition.body.products] == [
        "frequency",
        "frequency",
    ]
    assert [product.axes[0].unit for product in definition.body.products] == [
        "Hz",
        "Hz",
    ]
    assert len({product.axes[0].shared_as for product in definition.body.products}) == 1
    assert definition.body.products[0].axes[0].shared_as == "frequency"
    acquisition = definition.body.effects[-1]
    assert isinstance(acquisition, ModuleAcquireEffect)
    assert acquisition.id == "readout.sweep"
    assert acquisition.acquisition_id == "sweep"
    assert [result.result_id for result in acquisition.results] == [
        "frequency",
        "s_parameter",
    ]
    assert [result.product for result in acquisition.results] == [
        trace.frequency,
        trace.s_parameter,
    ]


def test_network_sweep_rejects_point_varying_output_shape() -> None:
    context = ModuleContext()
    points = coordinate("points", ScalarType(IntType()))
    vna = network_sweep(context, "readout")
    vna.ensure(points=points)

    with pytest.raises(
        ValueError,
        match=r"output-shaping state.*configuration binding.*point execution",
    ):
        vna.sweep(id="second")


def test_explicit_acquisition_id_namespaces_the_scoped_local_products() -> None:
    context = ModuleContext()
    vna = network_sweep(context, "readout")
    vna.ensure(NetworkSweepTarget(points=5))

    trace = vna.sweep(id="second")

    definition = context.close_definition_internal(id="test.symbolic.second")
    products = {product.qualified_id: product for product in definition.body.products}
    assert trace.frequency.id == "readout/second.frequency"
    assert trace.s_parameter.id == "readout/second.s_parameter"
    assert products[trace.frequency.id].axes[0].shared_as == "second.frequency"


def test_network_sweep_requires_ensured_state_sized_axis() -> None:
    context = ModuleContext()
    vna = network_sweep(context, "readout")

    with pytest.raises(
        ValueError,
        match=r"axis 'frequency'.*ensure that state",
    ):
        vna.sweep()


def test_temperature_sample_declares_all_contract_products() -> None:
    context = ModuleContext()
    thermometer = temperature_readout(context, "thermometer")

    sample = thermometer.sample()

    assert_type(sample, TemperatureSampleProducts)
    assert_type(sample.temperature, ProductRef)
    assert_type(sample.resistance, ProductRef)
    definition = context.close_definition_internal(id="test.symbolic.temperature")
    assert [product.id for product in definition.body.products] == [
        "temperature",
        "resistance",
    ]
    assert [product.dtype for product in definition.body.products] == [
        "float64",
        "float64",
    ]
    assert [product.unit for product in definition.body.products] == ["K", "Ohm"]
    assert all(not product.axes for product in definition.body.products)
    [acquisition] = definition.body.effects
    assert isinstance(acquisition, ModuleAcquireEffect)
    assert [result.product for result in acquisition.results] == [
        sample.temperature,
        sample.resistance,
    ]
