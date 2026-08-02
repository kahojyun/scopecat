from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated

import pytest
from scopecat_instruments import NetworkSweepGroupTarget, network_sweep
from scopecat_instruments.members import NETWORK_SWEEP

import scopecat.authoring as authoring
from scopecat.authoring.scans import axis
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.quantity import Quantity
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingEndpointBinding,
    RoutingGraph,
)
from scopecat.sdk.instruments import InterfaceRef
from tests.testkit.authoring import bind_invocation, load_config
from tests.testkit.local_materialization import operations_of_type
from tests.testkit.materialized_effects import (
    materialized_effects_contract,
    materialized_state_properties,
)

_DRIVE_FREQUENCY = InterfaceRef("test.drive_frequency/v1")
_DRIVE_FREQUENCY_VALUE = _DRIVE_FREQUENCY.property("value")
_READOUT_ACQUIRE = InterfaceRef("test.readout_acquire/v1")
_READOUT_SAMPLE_IQ = _READOUT_ACQUIRE.acquisition("sample").result("iq")
_READOUT_EMIT = InterfaceRef("test.readout_emit/v1")
_READOUT_EMIT_FREQUENCY = _READOUT_EMIT.property("frequency")


def _resource_binding_config(
    *,
    instruments: Mapping[str, str],
    bindings: Sequence[RoutingEndpointBinding],
    extra_entities: Sequence[EntityRef] = (),
) -> ConfigProfileSnapshot:
    seed = load_config()
    seed_instrument = seed.instrument_registry.instruments[0]
    known_entity_ids = {entity.id for entity in seed.topology.entities}
    selected_entities = [
        entity for entity in extra_entities if entity.id not in known_entity_ids
    ]
    system = seed.system.model_copy(
        update={
            "topology": seed.topology.model_copy(
                update={
                    "entities": [*seed.topology.entities, *selected_entities],
                }
            ),
            "instrument_registry": seed.instrument_registry.model_copy(
                update={
                    "instruments": [
                        seed_instrument.model_copy(
                            update={
                                "id": instrument_id,
                                "exclusivity_key": instrument_id,
                                "kind": kind,
                            }
                        )
                        for instrument_id, kind in instruments.items()
                    ]
                }
            ),
            "routing": RoutingGraph(
                bindings=list(bindings),
            ),
        }
    )
    return seed.model_copy(update={"system": system})


def test_typed_each_resources_route_to_different_instruments() -> None:
    q0 = EntityRef(id="q0", kind="logical_device")
    q1 = EntityRef(id="q1", kind="logical_device")
    config = _resource_binding_config(
        instruments={"source-0": "vna", "source-1": "vna"},
        bindings=(
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id=NETWORK_SWEEP.interface_id,
                entity_id=q0.id,
            ),
            RoutingEndpointBinding(
                instrument_id="source-1",
                interface_id=NETWORK_SWEEP.interface_id,
                entity_id=q1.id,
            ),
        ),
        extra_entities=(q1,),
    )

    @authoring.template(id="test.symbolic.each-routing", kind="symbolic_each")
    def experiment(
        context: authoring.ExperimentContext,
        points: Annotated[
            authoring.Input[int],
            authoring.IntType(minimum=1),
        ],
    ) -> None:
        analyzers = network_sweep(
            context,
            "readout",
            for_=authoring.each(q0, q1),
        )
        analyzers.ensure(NetworkSweepGroupTarget(points=points))
        traces = analyzers.sweep()
        context.record(traces)

    record_ids = tuple(
        selection.record_id for selection in experiment.definition.record_selections
    )
    assert len(record_ids) == 4
    assert len(set(record_ids)) == 4
    assert all(
        record_id is not None and record_id.endswith(("/frequency", "/s_parameter"))
        for record_id in record_ids
    )

    bound = bind_invocation(experiment(points=3), config_profile=config)
    preview = materialized_effects_contract(
        bound,
        bound.environment.parameters,
        config=config,
    )
    operations = operations_of_type(preview, CollectOperation, point_index=0)
    assert {
        operation.instrument_id: tuple(operation.command.requests[0].entity_ids)
        for operation in operations
    } == {"source-0": ("q0",), "source-1": ("q1",)}


def test_entity_resource_selection_is_deterministic_across_instruments() -> None:
    config = _resource_binding_config(
        instruments={"drive-awg-0": "awg", "drive-awg-1": "awg"},
        bindings=(
            RoutingEndpointBinding(
                instrument_id="drive-awg-0",
                interface_id="test.drive_frequency/v1",
                entity_id="q0",
            ),
            RoutingEndpointBinding(
                instrument_id="drive-awg-1",
                interface_id="test.drive_frequency/v1",
                entity_id="q1",
            ),
        ),
        extra_entities=(EntityRef(id="q1", kind="logical_device"),),
    )
    qubit = authoring.coordinate(
        "qubit",
        authoring.ScalarType(authoring.EntityType(entity_kind="logical_device")),
    )

    @authoring.module(id="test.resource-binding-scenarios.entity-routing")
    def module(
        context: authoring.ModuleContext,
        qubit: Annotated[
            authoring.Input[EntityRef | str],
            authoring.EntityType(entity_kind="logical_device"),
        ],
    ) -> None:
        drive = context._resource(
            "drive",
            requires=(_DRIVE_FREQUENCY,),
            for_entities=(authoring.input_ref(qubit),),
        )
        context._bind_property(
            drive,
            _DRIVE_FREQUENCY_VALUE,
            value=Quantity(value=5.0, unit="GHz"),
        )

    @authoring.template(
        id="test.resource-binding-scenarios.entity-routing",
        kind="resource_binding_contract",
    )
    def template(experiment: authoring.ExperimentContext) -> None:
        experiment.run(module(qubit))
        experiment.scan(axis(qubit, ("q1", "q0", "q1")))

    resolved = bind_invocation(template(), config_profile=config)
    preview = materialized_effects_contract(
        resolved,
        resolved.environment.parameters,
        config=config,
    )

    assert [point.coordinates["qubit"] for point in preview.points] == [
        EntityRef(id="q1", kind="logical_device"),
        EntityRef(id="q0", kind="logical_device"),
        EntityRef(id="q1", kind="logical_device"),
    ]
    assert {
        (point_index, operation.instrument_id)
        for point_index, operation, _target in materialized_state_properties(preview)
    } == {
        (0, "drive-awg-1"),
        (1, "drive-awg-0"),
        (2, "drive-awg-1"),
    }


@pytest.mark.parametrize(
    ("q1_instrument", "expected_instruments"),
    (
        (
            "digitizer-0",
            ("digitizer-0", "digitizer-0", "digitizer-0"),
        ),
        (
            "digitizer-1",
            ("digitizer-0", "digitizer-1", "digitizer-0"),
        ),
    ),
    ids=("one-instrument-multiple-channels", "instrument-switch"),
)
def test_acquisition_selects_point_local_instruments_and_channels(
    q1_instrument: str,
    expected_instruments: tuple[str, str, str],
) -> None:
    config = _resource_binding_config(
        instruments=dict.fromkeys(("digitizer-0", q1_instrument), "digitizer"),
        bindings=(
            RoutingEndpointBinding(
                instrument_id="digitizer-0",
                interface_id="test.readout_acquire/v1",
                entity_id="q0",
                channel_id="readout-q0",
            ),
            RoutingEndpointBinding(
                instrument_id=q1_instrument,
                interface_id="test.readout_acquire/v1",
                entity_id="q1",
                channel_id="readout-q1",
            ),
        ),
        extra_entities=(EntityRef(id="q1", kind="logical_device"),),
    )
    qubit = authoring.coordinate(
        "qubit",
        authoring.ScalarType(authoring.EntityType(entity_kind="logical_device")),
    )

    @authoring.module(id="test.resource-binding-scenarios.channel-selection")
    def module(
        context: authoring.ModuleContext,
        qubit: Annotated[
            authoring.Input[EntityRef | str],
            authoring.EntityType(entity_kind="logical_device"),
        ],
    ) -> None:
        digitizer = context._resource(
            "digitizer",
            requires=(_READOUT_ACQUIRE,),
            for_entities=(authoring.input_ref(qubit),),
        )
        iq = context._product("iq", dtype="complex128")
        context._acquire(
            "capture-iq",
            resource=digitizer,
            results={_READOUT_SAMPLE_IQ: iq},
        )

    @authoring.template(
        id="test.resource-binding-scenarios.channel-selection",
        kind="resource_binding_contract",
    )
    def template(experiment: authoring.ExperimentContext) -> None:
        call = experiment.run(module(qubit))
        experiment.scan(axis(qubit, ("q0", "q1", "q0")))
        experiment.record(call.products.iq)

    resolved = bind_invocation(template(), config_profile=config)
    preview = materialized_effects_contract(
        resolved,
        resolved.environment.parameters,
        config=config,
    )

    selections: list[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]]] = []
    for point_index in range(3):
        [operation] = operations_of_type(
            preview,
            CollectOperation,
            point_index=point_index,
        )
        [request] = operation.command.requests
        selections.append(
            (
                operation.instrument_id,
                tuple(request.entity_ids),
                tuple(
                    (binding.entity_id, binding.channel_id)
                    for binding in request.channel_bindings
                ),
            )
        )
    assert selections == [
        (expected_instruments[0], ("q0",), (("q0", "readout-q0"),)),
        (expected_instruments[1], ("q1",), (("q1", "readout-q1"),)),
        (expected_instruments[2], ("q0",), (("q0", "readout-q0"),)),
    ]


def test_readout_source_and_digitizer_are_explicit_independent_ports() -> None:
    config = _resource_binding_config(
        instruments={
            "readout-source-0": "rf_source",
            "digitizer-0": "digitizer",
        },
        bindings=(
            RoutingEndpointBinding(
                instrument_id="readout-source-0",
                interface_id="test.readout_emit/v1",
                entity_id="q0",
            ),
            RoutingEndpointBinding(
                instrument_id="digitizer-0",
                interface_id="test.readout_acquire/v1",
                entity_id="q0",
            ),
        ),
    )

    @authoring.module(id="test.resource-binding-scenarios.split-readout")
    def module(
        context: authoring.ModuleContext,
        qubit: Annotated[
            authoring.Input[EntityRef | str],
            authoring.EntityType(entity_kind="logical_device"),
        ],
    ) -> None:
        readout_source = context._resource(
            "readout_source",
            requires=(_READOUT_EMIT,),
            for_entities=(authoring.input_ref(qubit),),
        )
        digitizer = context._resource(
            "digitizer",
            requires=(_READOUT_ACQUIRE,),
            for_entities=(authoring.input_ref(qubit),),
        )
        context._bind_property(
            readout_source,
            _READOUT_EMIT_FREQUENCY,
            value=Quantity(value=6.5, unit="GHz"),
        )
        iq = context._product(
            "iq",
            dtype="complex128",
        )
        context._acquire(
            "capture-iq",
            resource=digitizer,
            results={_READOUT_SAMPLE_IQ: iq},
        )

    @authoring.template(
        id="test.resource-binding-scenarios.split-readout",
        kind="resource_binding_contract",
    )
    def template(
        experiment: authoring.ExperimentContext,
        qubit: Annotated[
            authoring.Input[EntityRef | str],
            authoring.EntityType(entity_kind="logical_device"),
        ],
    ) -> None:
        call = experiment.run(module(qubit))
        experiment.record(call.products.iq)

    resolved = bind_invocation(template(qubit="q0"), config_profile=config)
    preview = materialized_effects_contract(
        resolved,
        resolved.environment.parameters,
        config=config,
    )

    [source_state] = operations_of_type(
        preview,
        ApplyStateOperation,
        point_index=0,
    )
    [digitizer_collect] = operations_of_type(
        preview,
        CollectOperation,
        point_index=0,
    )
    assert source_state.instrument_id == "readout-source-0"
    assert digitizer_collect.instrument_id == "digitizer-0"
    assert digitizer_collect.command.requests[0].entity_ids == ["q0"]
