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
    one,
    template,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.program.bindings import EnsureStateIntent
from scopecat.program.expressions import LiteralScalarExpr
from scopecat.program.module import ModuleAcquireEffect

from scopecat_instruments import (
    DCMonitorProducts,
    DCMonitorState,
    DCSourceState,
    DCSourceVoltage,
    NetworkSweepProducts,
    NetworkSweepState,
    RFOutputState,
    SymbolicDCSourceClient,
    SymbolicDCSourceGroup,
    SymbolicDCSourceMonitorClient,
    SymbolicDCSourceMonitorGroup,
    SymbolicInstrumentRecorder,
    SymbolicNetworkSweepClient,
    SymbolicNetworkSweepGroup,
    SymbolicRFOutputClient,
    SymbolicRFOutputGroup,
    SymbolicTemperatureReadoutClient,
    SymbolicTemperatureReadoutGroup,
    TemperatureSampleProducts,
    dc_source,
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
    analyzers.ensure(NetworkSweepState(points=11))
    traces = analyzers.sweep()

    assert_type(traces, PerEntity[NetworkSweepProducts])
    definition = context.close_definition_internal(id="test.symbolic.each")
    resources = definition.interface.resources
    assert len(resources) == 2
    assert tuple(analyzers.resources) == (q0, q1)
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


def test_each_factories_keep_the_typed_interface_specific_group_verbs() -> None:
    context = ModuleContext()
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    selection = each(q0, q1)

    outputs = rf_output(context, "drive", for_=selection)
    thermometers = temperature_readout(context, "temperature", for_=selection)
    assert_type(outputs, SymbolicRFOutputGroup)
    assert_type(thermometers, SymbolicTemperatureReadoutGroup)
    outputs.ensure(RFOutputState(output_enabled=False))
    samples = thermometers.sample()

    assert_type(samples, PerEntity[TemperatureSampleProducts])
    assert tuple(samples) == (q0, q1)


def test_dc_group_accepts_broadcast_and_typed_per_entity_state() -> None:
    context = ModuleContext()
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    biases = dc_source(context, "flux", for_=each(q0, q1))
    assert_type(biases, SymbolicDCSourceGroup)
    common = DCSourceVoltage(
        range=Quantity(1, "V"),
        level=Quantity(0.01, "V"),
    )
    biases.ensure(common)
    states = assert_type(
        PerEntity(
            (
                (
                    q1,
                    DCSourceVoltage(
                        range=Quantity(1, "V"),
                        level=Quantity(0.02, "V"),
                    ),
                ),
                (
                    q0,
                    DCSourceVoltage(
                        range=Quantity(1, "V"),
                        level=Quantity(0.03, "V"),
                    ),
                ),
            )
        ),
        PerEntity[DCSourceVoltage],
    )

    biases.ensure(states)

    definition = context.close_definition_internal(id="test.symbolic.dc-each")
    ensures = tuple(
        effect
        for effect in definition.body.effects
        if isinstance(effect, EnsureStateIntent)
    )
    assert len(ensures) == 4


def test_group_per_entity_state_requires_an_exact_full_identity_join() -> None:
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    wrong_q1 = EntityRef(id="q1", kind="logical_coupler")
    biases = dc_source(ModuleContext(), "flux", for_=each(q0, q1))
    state = DCSourceVoltage(
        range=Quantity(1, "V"),
        level=Quantity(0.01, "V"),
    )

    with pytest.raises(
        ValueError,
        match=(
            r"exactly match.*missing logical_device:q1; "
            r"extra logical_coupler:q1"
        ),
    ):
        biases.ensure(PerEntity(((q0, state), (wrong_q1, state))))


def test_experiment_context_satisfies_the_symbolic_recorder_protocol() -> None:
    context = ExperimentContext()
    recorder: SymbolicInstrumentRecorder = context

    vna = network_sweep(recorder, "readout")

    assert_type(vna, SymbolicNetworkSweepClient)
    assert vna.resource.id == "readout"


def test_symbolic_products_record_directly_from_a_root_experiment() -> None:
    @template(id="test.symbolic.root", kind="symbolic_root")
    def experiment(context: ExperimentContext) -> None:
        vna = network_sweep(context, "readout")
        vna.ensure(NetworkSweepState(points=11))
        trace = vna.sweep()
        context.record(trace.frequency, trace.s_parameter)

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
        "frequency",
        "s_parameter",
    ]


def test_root_finalization_accepts_a_typed_symbolic_client_and_declared_state() -> None:
    @template(id="test.symbolic.typed-finalization", kind="symbolic_root")
    def experiment(context: ExperimentContext) -> None:
        source = dc_source(context, "flux")
        context.finalize(source, DCSourceState(output_enabled=False))

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
        target: DCSourceState | PerEntity[DCSourceState]
        if per_entity:
            target = PerEntity(
                (
                    (q1, DCSourceState(output_enabled=True)),
                    (q0, DCSourceState(output_enabled=False)),
                )
            )
        else:
            target = DCSourceState(output_enabled=False)
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
    left.ensure(NetworkSweepState(points=3))
    right.ensure(NetworkSweepState(points=3))

    left_trace = left.sweep()
    right_trace = right.sweep()

    definition = context.close_definition_internal(id="test.symbolic.scopes")
    assert len({product.qualified_id for product in definition.body.products}) == 4
    assert left_trace.s_parameter.id == "left/s_parameter"
    assert right_trace.s_parameter.id == "right/s_parameter"


def test_state_clients_record_typed_ensure_effects() -> None:
    context = ModuleContext()
    source = dc_source(context, "flux")
    rf = rf_output(context, "drive")

    source.ensure(
        DCSourceVoltage(
            range=Quantity(1.0, "V"),
            level=Quantity(0.05, "V"),
            output_enabled=True,
        )
    )
    rf.ensure(
        RFOutputState(
            frequency=Quantity(5.0, "GHz"),
            power=Quantity(-20.0, "dBm"),
            output_enabled=True,
        )
    )

    definition = context.close_definition_internal(id="test.symbolic.state")
    assert len(definition.body.effects) == 2
    assert all(
        isinstance(effect, EnsureStateIntent) for effect in definition.body.effects
    )
    assert [
        len(effect.assignments)
        for effect in definition.body.effects
        if isinstance(effect, EnsureStateIntent)
    ] == [4, 3]


def test_dc_monitor_selects_the_contract_result_for_the_ensured_source_mode() -> None:
    context = ModuleContext()
    source = dc_source(context, "flux", monitor=True)
    assert_type(source, SymbolicDCSourceMonitorClient)
    source.ensure(
        DCSourceVoltage(
            range=Quantity(1.0, "V"),
            level=Quantity(0.05, "V"),
            output_enabled=True,
        )
    )
    source.ensure(DCMonitorState(measurement_enabled=True))

    sample = source.monitor()

    assert_type(sample, DCMonitorProducts)
    assert_type(sample.current, ProductRef | None)
    assert_type(sample.voltage, ProductRef | None)
    assert sample.current is not None
    assert sample.voltage is None
    definition = context.close_definition_internal(id="test.symbolic.dc-monitor")
    assert [product.id for product in definition.body.products] == ["monitored_current"]
    acquisition = definition.body.effects[-1]
    assert isinstance(acquisition, ModuleAcquireEffect)
    assert [result.result_id for result in acquisition.results] == ["monitored_current"]


def test_dc_monitor_requires_a_concrete_ensured_source_mode() -> None:
    source = dc_source(ModuleContext(), "flux", monitor=True)

    with pytest.raises(ValueError, match=r"state-dependent results.*concrete"):
        source.monitor()


def test_dc_monitor_selection_is_a_static_symbolic_capability_boundary() -> None:
    context = ModuleContext()
    source = dc_source(context, "flux")
    monitor = dc_source(context, "meter", monitor=True)

    assert_type(source, SymbolicDCSourceClient)
    assert_type(monitor, SymbolicDCSourceMonitorClient)
    assert not hasattr(source, "monitor")
    assert hasattr(monitor, "monitor")

    interface, _, _ = context.close_experiment_parts_internal()
    assert interface.resources[0].selector.interfaces == (DC_SOURCE.interface_id,)
    assert interface.resources[1].selector.interfaces == (
        DC_SOURCE.interface_id,
        DC_MONITOR.interface_id,
    )


def test_dc_monitor_group_selection_retains_monitor_verbs() -> None:
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")

    sources = dc_source(
        ModuleContext(),
        "flux",
        for_=each(q0, q1),
        monitor=True,
    )

    assert_type(sources, SymbolicDCSourceMonitorGroup)
    assert_type(sources[q0], SymbolicDCSourceMonitorClient)
    assert hasattr(sources, "monitor")


def test_network_sweep_declares_contract_products_and_ensured_points() -> None:
    context = ModuleContext()
    vna = network_sweep(context, "readout")
    vna.ensure(
        NetworkSweepState(
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
    vna.ensure(NetworkSweepState(points=points))

    with pytest.raises(
        ValueError,
        match=r"output-shaping state.*configuration binding.*point execution",
    ):
        vna.sweep(id="second")


def test_explicit_acquisition_id_namespaces_the_scoped_local_products() -> None:
    context = ModuleContext()
    vna = network_sweep(context, "readout")
    vna.ensure(NetworkSweepState(points=5))

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
