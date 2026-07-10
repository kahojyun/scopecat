from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat._compiler.program import LinkedProgram, ResourceRouteIntent, set_state
from scopecat._planning.planner import build_planner_snapshot
from scopecat._relations import input_series, lit, literal_rows, values
from scopecat._runtime.lowering import compile_point_routes
from scopecat._value_expressions import as_value_expr
from scopecat.models.config import (
    Channel,
    Device,
    RoutingChannelBinding,
    RoutingEdge,
    RoutingGraph,
    RoutingResource,
    SharedResourceGroup,
    TopologyLine,
)
from scopecat.models.entity import EntityRef
from scopecat.planning.validation import validate_config
from scopecat.routing import RoutingError, RoutingView
from tests.support.authoring import load_config, parameters
from tests.support.experiment_preview import preview_result


def test_routing_view_routes_by_capability_and_entity() -> None:
    config = load_config()
    source = config.instrument_registry.instruments[0]
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        source,
                        source.model_copy(update={"id": "source-1"}),
                    ]
                }
            ),
            "routing": RoutingGraph(
                resources=[
                    RoutingResource(
                        id="source-0",
                        capabilities=["set_frequency"],
                        served_entities=["q0"],
                    ),
                    RoutingResource(
                        id="source-1",
                        capabilities=["set_frequency"],
                        served_entities=["q1"],
                    ),
                ]
            ),
        }
    )
    routing = RoutingView.from_config(config.model_copy(update={"system": system}))

    binding = routing.route(
        port_id="drive",
        capabilities=("set_frequency",),
        entity_ids=("q1",),
    )

    assert binding.resource_id == "source-1"
    assert binding.port_id == "drive"


def test_routing_view_prefers_explicit_routing_graph() -> None:
    config = load_config()
    source = config.instrument_registry.instruments[0]
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        source,
                        source.model_copy(update={"id": "source-1"}),
                    ]
                }
            ),
            "routing": RoutingGraph(
                resources=[
                    RoutingResource(
                        id="source-1",
                        capabilities=["set_frequency"],
                        served_entities=["q1"],
                    )
                ]
            ),
        }
    )
    routing = RoutingView.from_config(config.model_copy(update={"system": system}))

    binding = routing.route(
        port_id="drive",
        capabilities=("set_frequency",),
        entity_ids=("q1",),
    )

    assert binding.resource_id == "source-1"


def test_routing_view_routes_through_graph_edges() -> None:
    config = load_config()
    source = config.instrument_registry.instruments[0]
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        source,
                        source.model_copy(update={"id": "source-1"}),
                    ]
                }
            ),
            "routing": RoutingGraph(
                resources=[
                    RoutingResource(
                        id="source-0",
                        capabilities=["set_frequency"],
                    ),
                    RoutingResource(
                        id="source-1",
                        capabilities=["set_frequency"],
                    ),
                ],
                edges=[
                    RoutingEdge(
                        id="source-0-q0",
                        resource_id="source-0",
                        entity_ids=["q0"],
                    ),
                    RoutingEdge(
                        id="source-1-q1",
                        resource_id="source-1",
                        entity_ids=["q1"],
                    ),
                ],
            ),
        }
    )
    routing = RoutingView.from_config(config.model_copy(update={"system": system}))

    binding = routing.route(
        port_id="drive",
        capabilities=("set_frequency",),
        entity_ids=("q1",),
    )

    assert binding.resource_id == "source-1"


def test_routing_view_returns_channel_bindings_from_edges() -> None:
    config = load_config()
    source = config.instrument_registry.instruments[0]
    topology = config.topology.model_copy(
        update={
            "entities": [
                *config.topology.entities,
                EntityRef(id="q1", kind="logical_qubit"),
            ],
            "devices": [
                *config.topology.devices,
                Device(id="source-1", kind="logical_instrument"),
            ],
            "lines": [
                TopologyLine(
                    id="q1.xy",
                    kind="control_line",
                    signal="drive",
                    endpoints=["q1", "source-1"],
                )
            ],
            "channels": [
                *config.topology.channels,
                Channel(
                    id="awg0.ch2",
                    kind="drive",
                    signal="drive",
                    port="ch2",
                    line_id="q1.xy",
                    group_ids=["lo.xy0"],
                ),
            ],
            "groups": [
                SharedResourceGroup(
                    id="lo.xy0",
                    kind="lo",
                    members=["awg0.ch2"],
                )
            ],
        }
    )
    system = config.system.model_copy(
        update={
            "topology": topology,
            "instrument_registry": config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        source,
                        source.model_copy(update={"id": "source-1"}),
                    ]
                }
            ),
            "routing": RoutingGraph(
                resources=[
                    RoutingResource(
                        id="source-1",
                        capabilities=["set_frequency"],
                    )
                ],
                edges=[
                    RoutingEdge(
                        id="source-1-q1-drive",
                        resource_id="source-1",
                        capabilities=["set_frequency"],
                        bindings=[
                            RoutingChannelBinding(
                                entity_id="q1",
                                channel_id="awg0.ch2",
                                capability="set_frequency",
                            )
                        ],
                    )
                ],
            ),
        }
    )
    selected_config = config.model_copy(update={"system": system})
    routing = RoutingView.from_config(selected_config)

    binding = routing.route(
        port_id="drive",
        capabilities=("set_frequency",),
        entity_ids=("q1",),
    )

    assert not validate_config(selected_config)
    assert binding.resource_id == "source-1"
    assert [item.channel_id for item in binding.channel_bindings] == ["awg0.ch2"]
    assert [item.line_id for item in binding.channel_bindings] == ["q1.xy"]
    assert [item.group_ids for item in binding.channel_bindings] == [["lo.xy0"]]


def test_routing_view_fallback_channel_bindings_follow_served_entity_order() -> None:
    config = load_config()
    system = config.system.model_copy(
        update={
            "routing": RoutingGraph(
                resources=[
                    RoutingResource(
                        id="coupler-stack",
                        capabilities=["set_flux_bias"],
                        served_entities=["coupler-q0-q1", "coupler-q2-q3"],
                        channels=["bias0", "bias1"],
                    )
                ]
            )
        }
    )
    routing = RoutingView.from_config(config.model_copy(update={"system": system}))

    binding = routing.route(
        port_id="spectator_bias",
        capabilities=("set_flux_bias",),
        entity_ids=("coupler-q2-q3",),
    )

    assert [(item.entity_id, item.channel_id) for item in binding.channel_bindings] == [
        ("coupler-q2-q3", "bias1")
    ]


def test_routing_view_reports_ambiguous_port_without_entity_filter() -> None:
    config = load_config()
    source = config.instrument_registry.instruments[0]
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        source,
                        source.model_copy(update={"id": "source-1"}),
                    ]
                }
            ),
            "routing": RoutingGraph(
                resources=[
                    RoutingResource(
                        id="source-0",
                        capabilities=["set_frequency"],
                    ),
                    RoutingResource(
                        id="source-1",
                        capabilities=["set_frequency"],
                    ),
                ]
            ),
        }
    )
    routing = RoutingView.from_config(config.model_copy(update={"system": system}))

    with pytest.raises(RoutingError) as error:
        routing.route(port_id="drive", capabilities=("set_frequency",))

    assert error.value.code == "module_resource_port_ambiguous"


def test_routing_view_rejects_explicit_resource_entity_mismatch() -> None:
    routing = RoutingView.from_config(load_config())

    with pytest.raises(RoutingError) as error:
        routing.route(
            port_id="drive",
            capabilities=("set_frequency",),
            entity_ids=("q1",),
            resource_id="source-0",
        )

    assert error.value.code == "module_resource_port_entity_mismatch"


def test_runtime_graph_reports_shared_group_resource_conflict() -> None:
    config = _routing_constraint_config(
        resources=[
            RoutingResource(id="source-0", capabilities=["set_frequency"]),
            RoutingResource(id="source-1", capabilities=["set_frequency"]),
        ],
        edges=[
            RoutingEdge(
                id="source-0-q0-drive",
                resource_id="source-0",
                capabilities=["set_frequency"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q0",
                        channel_id="awg0.ch1",
                        capability="set_frequency",
                        group_ids=["lo.xy0"],
                    )
                ],
            ),
            RoutingEdge(
                id="source-1-q1-drive",
                resource_id="source-1",
                capabilities=["set_frequency"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q1",
                        channel_id="awg1.ch1",
                        capability="set_frequency",
                        group_ids=["lo.xy0"],
                    )
                ],
            ),
        ],
    )

    _preview, diagnostics = preview_result(
        _two_route_experiment(),
        parameters(),
        config=config,
    )

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_shared_group_resource_conflict"
    }


def test_runtime_graph_allows_configured_shared_group_resource_fanout() -> None:
    config = _routing_constraint_config(
        resources=[
            RoutingResource(id="source-0", capabilities=["set_frequency"]),
            RoutingResource(id="source-1", capabilities=["set_frequency"]),
        ],
        edges=[
            RoutingEdge(
                id="source-0-q0-drive",
                resource_id="source-0",
                capabilities=["set_frequency"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q0",
                        channel_id="awg0.ch1",
                        capability="set_frequency",
                        group_ids=["lo.xy0"],
                    )
                ],
            ),
            RoutingEdge(
                id="source-1-q1-drive",
                resource_id="source-1",
                capabilities=["set_frequency"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q1",
                        channel_id="awg1.ch1",
                        capability="set_frequency",
                        group_ids=["lo.xy0"],
                    )
                ],
            ),
        ],
        groups=[
            SharedResourceGroup(
                id="lo.xy0",
                kind="lo",
                members=["awg0.ch1", "awg1.ch1"],
                max_resources_per_point=2,
            )
        ],
    )

    _preview, diagnostics = preview_result(
        _two_route_experiment(),
        parameters(),
        config=config,
    )

    assert "routing_shared_group_resource_conflict" not in {
        diagnostic.code for diagnostic in diagnostics
    }


def test_runtime_graph_reports_channel_shared_by_multiple_ports() -> None:
    config = _routing_constraint_config(
        resources=[RoutingResource(id="source-0", capabilities=["set_frequency"])],
        edges=[
            RoutingEdge(
                id="source-0-q0-drive",
                resource_id="source-0",
                capabilities=["set_frequency"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q0",
                        channel_id="awg0.ch1",
                        capability="set_frequency",
                    )
                ],
            ),
            RoutingEdge(
                id="source-0-q1-drive",
                resource_id="source-0",
                capabilities=["set_frequency"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q1",
                        channel_id="awg0.ch1",
                        capability="set_frequency",
                    )
                ],
            ),
        ],
    )

    _preview, diagnostics = preview_result(
        _two_route_experiment(),
        parameters(),
        config=config,
    )

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "routing_channel_shared_by_ports"
    }


def test_runtime_graph_allows_configured_channel_route_port_fanout() -> None:
    config = _routing_constraint_config(
        resources=[RoutingResource(id="source-0", capabilities=["set_frequency"])],
        edges=[
            RoutingEdge(
                id="source-0-q0-drive",
                resource_id="source-0",
                capabilities=["set_frequency"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q0",
                        channel_id="awg0.ch1",
                        capability="set_frequency",
                    )
                ],
            ),
            RoutingEdge(
                id="source-0-q1-drive",
                resource_id="source-0",
                capabilities=["set_frequency"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q1",
                        channel_id="awg0.ch1",
                        capability="set_frequency",
                    )
                ],
            ),
        ],
        channels=[
            Channel(
                id="awg0.ch1",
                kind="drive",
                signal="drive",
                port="ch1",
                max_route_ports_per_point=2,
            )
        ],
    )

    _preview, diagnostics = preview_result(
        _two_route_experiment(),
        parameters(),
        config=config,
    )

    assert "routing_channel_shared_by_ports" not in {
        diagnostic.code for diagnostic in diagnostics
    }


def test_runtime_graph_reports_conflicting_state_field_values() -> None:
    experiment = LinkedProgram(
        id="conflicting-state",
        kind="routing_test",
        points=literal_rows([{}]),
        state=[
            set_state("source-0", "set_frequency.frequency", 1.0),
            set_state("source-0", "set_frequency.frequency", 2.0),
        ],
    )

    _preview, diagnostics = preview_result(
        experiment,
        parameters(),
        config=load_config(),
    )

    assert {diagnostic.code for diagnostic in diagnostics} >= {
        "runtime_state_field_conflict"
    }


def test_route_entity_expressions_reject_table_shape() -> None:
    with pytest.raises(ValidationError):
        ResourceRouteIntent.model_validate(
            {
                "port_id": "source",
                "entity_exprs": [as_value_expr(literal_rows([{"entity": "q0"}]))],
            }
        )


def test_runtime_graph_reports_invalid_route_entity_member() -> None:
    experiment = LinkedProgram(
        id="invalid-route-entity",
        kind="routing_test",
        points=literal_rows([{}]),
        route_intents=[
            ResourceRouteIntent(
                port_id="source",
                capabilities=["set_frequency"],
                entity_exprs=[as_value_expr(lit(1))],
            ),
            ResourceRouteIntent(
                port_id="empty-source",
                capabilities=["set_frequency"],
                entity_exprs=[as_value_expr(values([]))],
            ),
        ],
    )

    _preview, diagnostics = preview_result(
        experiment,
        parameters(),
        config=load_config(),
    )

    assert [diagnostic.code for diagnostic in diagnostics].count(
        "module_resource_entity_invalid"
    ) == 2


def test_route_entity_evaluation_failure_does_not_create_wildcard_binding() -> None:
    experiment = LinkedProgram(
        id="failed-route-entity-expression",
        kind="routing_test",
        points=literal_rows([{}]),
        route_intents=[
            ResourceRouteIntent(
                port_id="source",
                capabilities=["set_frequency"],
                entity_exprs=[as_value_expr(input_series("missing"))],
            )
        ],
    )
    plan = build_planner_snapshot(experiment, parameters())

    bindings, diagnostics = compile_point_routes(plan, config=load_config())

    assert bindings == {}
    assert {diagnostic["code"] for diagnostic in diagnostics} == {
        "runtime_graph_route_entity_invalid"
    }


def _two_route_experiment() -> LinkedProgram:
    return LinkedProgram(
        id="two-route-conflict",
        kind="routing_test",
        points=literal_rows([{}]),
        route_intents=[
            ResourceRouteIntent(
                port_id="drive_a",
                capabilities=["set_frequency"],
                entity_exprs=[as_value_expr(lit("q0"))],
            ),
            ResourceRouteIntent(
                port_id="drive_b",
                capabilities=["set_frequency"],
                entity_exprs=[as_value_expr(lit("q1"))],
            ),
        ],
    )


def _routing_constraint_config(
    *,
    resources: list[RoutingResource],
    edges: list[RoutingEdge],
    groups: list[SharedResourceGroup] | None = None,
    channels: list[Channel] | None = None,
):
    config = load_config()
    source = config.instrument_registry.instruments[0]
    system = config.system.model_copy(
        update={
            "topology": config.topology.model_copy(
                update={
                    "entities": [
                        *config.topology.entities,
                        EntityRef(id="q1", kind="logical_qubit"),
                    ],
                    "groups": list(groups or config.topology.groups),
                    "channels": list(channels or config.topology.channels),
                }
            ),
            "instrument_registry": config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        source,
                        source.model_copy(update={"id": "source-1"}),
                    ]
                }
            ),
            "routing": RoutingGraph(resources=resources, edges=edges),
        }
    )
    return config.model_copy(update={"system": system})
