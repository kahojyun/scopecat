from __future__ import annotations

from typing import assert_type

import pytest
from scopecat.authoring import (
    EntityType,
    ExperimentContext,
    IntType,
    ModuleContext,
    ProductRef,
    ScalarType,
    coordinate,
    template,
)
from scopecat.kernel.quantity import Quantity
from scopecat.program.bindings import EnsureStateIntent
from scopecat.program.module import ModuleAcquireEffect

from scopecat_instruments import (
    DCMonitorProducts,
    DCMonitorState,
    DCSourceVoltage,
    NetworkSweepProducts,
    NetworkSweepState,
    RFOutputState,
    SymbolicDCSourceClient,
    SymbolicInstrumentRecorder,
    SymbolicNetworkSweepClient,
    SymbolicRFOutputClient,
    SymbolicTemperatureReadoutClient,
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

    source = dc_source(context, "flux", for_entities=(qubit,))
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
        (DC_SOURCE.interface_id, DC_MONITOR.interface_id),
        (RF_OUTPUT.interface_id,),
        (NETWORK_SWEEP.interface_id,),
        (TEMPERATURE_READOUT.interface_id,),
    ]
    assert interface.resources[0].selector.entity_inputs == (qubit,)


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
    ] == ["frequency", "s_parameter"]


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
    source = dc_source(context, "flux")
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
    source = dc_source(ModuleContext(), "flux")

    with pytest.raises(ValueError, match=r"state-dependent results.*concrete"):
        source.monitor()


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


def test_network_sweep_preserves_symbolic_points_as_product_axis_size() -> None:
    context = ModuleContext()
    points = coordinate("points", ScalarType(IntType()))
    vna = network_sweep(context, "readout")
    vna.ensure(NetworkSweepState(points=points))

    trace = vna.sweep(id="second")

    _, body, _ = context.close_experiment_parts_internal()
    assert trace.frequency.id == "second.frequency"
    assert trace.s_parameter.id == "second.s_parameter"
    products = {product.id: product for product in body.products}
    assert products[trace.frequency.id].axes[0].size is points
    assert products[trace.s_parameter.id].axes[0].size is points
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
