from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest

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
from tests.testkit.authoring import link_invocation, load_config, template_fixture
from tests.testkit.local_materialization import operations_of_type
from tests.testkit.materialized_effects import (
    materialized_effects_contract,
    materialized_state_fields,
)


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
                            update={"id": instrument_id, "kind": kind}
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


def test_entity_resource_selection_is_deterministic_across_instruments() -> None:
    config = _resource_binding_config(
        instruments={"drive-awg-0": "awg", "drive-awg-1": "awg"},
        bindings=(
            RoutingEndpointBinding(
                instrument_id="drive-awg-0",
                capability="drive.frequency",
                entity_id="q0",
            ),
            RoutingEndpointBinding(
                instrument_id="drive-awg-1",
                capability="drive.frequency",
                entity_id="q1",
            ),
        ),
        extra_entities=(EntityRef(id="q1", kind="logical_device"),),
    )
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType(entity_kind="logical_device")),
    )
    module = (
        authoring.module_body(id="test.resource-binding-scenarios.entity-shards")
        .inputs(qubit)
        .resource(
            "drive",
            requires=("drive.frequency",),
            for_entities=(qubit,),
        )
        .bind_field(
            "drive",
            capability="drive.frequency",
            field="value",
            value=Quantity(value=5.0, unit="GHz"),
        )
        .build()
    )
    invocation = template_fixture(
        module,
        id="test.resource-binding-scenarios.entity-shards",
        kind="resource_binding_contract",
        scans=(
            axis(
                authoring.coordinate(
                    "qubit",
                    authoring.ScalarType(
                        authoring.EntityType(entity_kind="logical_device")
                    ),
                ),
                ("q1", "q0", "q1"),
            ),
        ),
    ).bind()

    resolved = link_invocation(invocation, config_profile=config)
    preview = materialized_effects_contract(
        resolved.program,
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
        for point_index, operation, _field in materialized_state_fields(preview)
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
                capability="readout.acquire",
                entity_id="q0",
                channel_id="readout-q0",
            ),
            RoutingEndpointBinding(
                instrument_id=q1_instrument,
                capability="readout.acquire",
                entity_id="q1",
                channel_id="readout-q1",
            ),
        ),
        extra_entities=(EntityRef(id="q1", kind="logical_device"),),
    )
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType(entity_kind="logical_device")),
    )
    module = (
        authoring.module_body(id="test.resource-binding-scenarios.channel-selection")
        .inputs(qubit)
        .resource(
            "digitizer",
            requires=("readout.acquire",),
            for_entities=(qubit,),
        )
        .product("iq", dtype="complex128")
        .acquire(
            "capture-iq",
            "iq",
            resource="digitizer",
            capability="readout.acquire",
        )
        .build()
    )
    invocation = template_fixture(
        module,
        id="test.resource-binding-scenarios.channel-selection",
        kind="resource_binding_contract",
        scans=(
            axis(
                authoring.coordinate(
                    "qubit",
                    authoring.ScalarType(
                        authoring.EntityType(entity_kind="logical_device")
                    ),
                ),
                ("q0", "q1", "q0"),
            ),
        ),
        records=(authoring.record_product("iq"),),
    ).bind()

    resolved = link_invocation(invocation, config_profile=config)
    preview = materialized_effects_contract(
        resolved.program,
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
                capability="readout.emit",
                entity_id="q0",
            ),
            RoutingEndpointBinding(
                instrument_id="digitizer-0",
                capability="readout.acquire",
                entity_id="q0",
            ),
        ),
    )
    qubit = authoring.input(
        "qubit",
        authoring.ScalarType(authoring.EntityType(entity_kind="logical_device")),
    )
    module = (
        authoring.module_body(id="test.resource-binding-scenarios.split-readout")
        .inputs(qubit)
        .resource(
            "readout_source",
            requires=("readout.emit",),
            for_entities=(qubit,),
        )
        .resource(
            "digitizer",
            requires=("readout.acquire",),
            for_entities=(qubit,),
        )
        .bind_field(
            "readout_source",
            capability="readout.emit",
            field="frequency",
            value=Quantity(value=6.5, unit="GHz"),
        )
        .product(
            "iq",
            dtype="complex128",
        )
        .acquire(
            "capture-iq",
            "iq",
            resource="digitizer",
            capability="readout.acquire",
        )
        .build()
    )
    invocation = template_fixture(
        module,
        id="test.resource-binding-scenarios.split-readout",
        kind="resource_binding_contract",
        records=(authoring.record_product("iq"),),
    ).bind(qubit="q0")

    resolved = link_invocation(invocation, config_profile=config)
    preview = materialized_effects_contract(
        resolved.program,
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
