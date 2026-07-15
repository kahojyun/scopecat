from __future__ import annotations

from dataclasses import replace

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.linking.bound import BoundPlan
from scopecat.compiler.linking.linked import link_program
from scopecat.compiler.linking.materialization import (
    channel_signature,
    materialize_local_plan,
)
from scopecat.compiler.relations.model import (
    input_series,
    lit,
    values,
)
from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    ResourceRouteIntent,
    TypedProgram,
    instrument_product_producer,
    observable_product,
    record_product,
    set_state_field,
    typed_program,
)
from scopecat.execution.local.lowering import build_execution_program
from scopecat.execution.local.program import ApplyStateStage, CollectStage
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
    logical_resource_port_id,
    physical_resource_id,
)
from scopecat.kernel.value_types import (
    Entity,
    Float,
    Int,
    Scalar,
    Series,
    String,
)
from scopecat.planning.routing import RoutingError, RoutingView
from scopecat.planning.validation import validate_config
from scopecat.records.config import (
    Channel,
    ConfigProfileSnapshot,
    Device,
    RoutingChannelBinding,
    RoutingEdge,
    RoutingGraph,
    RoutingResource,
    SharedResourceGroup,
    TopologyLine,
)
from scopecat.records.entity import EntityRef
from tests.testkit.authoring import load_config, parameters
from tests.testkit.relation_plans import (
    scalar_value_expr,
    series_value_expr,
)


def _resource(value: str) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(String()))


def _port(value: str) -> LogicalResourcePortId:
    return logical_resource_port_id(value)


def _physical(value: str) -> PhysicalResourceId:
    return physical_resource_id(value)


def _number(value: float) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(Float()))


def _entity(value: str) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(Entity()))


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
        port_id=_port("drive"),
        capabilities=("set_frequency",),
        entity_ids=("q1",),
    )

    assert binding.resource_id == _physical("source-1")
    assert binding.port_id == _port("drive")


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
        port_id=_port("drive"),
        capabilities=("set_frequency",),
        entity_ids=("q1",),
    )

    assert binding.resource_id == _physical("source-1")


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
        port_id=_port("drive"),
        capabilities=("set_frequency",),
        entity_ids=("q1",),
    )

    assert binding.resource_id == _physical("source-1")


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
        port_id=_port("drive"),
        capabilities=("set_frequency",),
        entity_ids=("q1",),
    )

    assert not validate_config(selected_config)
    assert binding.resource_id == _physical("source-1")
    assert [item.channel_id for item in binding.channel_bindings] == ["awg0.ch2"]
    assert [item.line_id for item in binding.channel_bindings] == ["q1.xy"]
    assert [item.group_ids for item in binding.channel_bindings] == [["lo.xy0"]]


def test_capability_entity_domain_limits_resource_channel_fallback() -> None:
    config = load_config()
    routing = RoutingView(
        resources=(
            RoutingResource(
                id="source-0",
                capabilities=["B"],
                served_entities=["q0", "q1"],
                channels=["drive-q0", "readout-q0"],
            ),
        ),
        edges=(
            RoutingEdge(
                id="source-0-B-q0",
                resource_id="source-0",
                entity_ids=["q0"],
                capabilities=["B"],
            ),
        ),
        channel_lines_by_id={
            channel.id: channel.line_id for channel in config.topology.channels
        },
        channel_groups_by_id={
            channel.id: tuple(channel.group_ids) for channel in config.topology.channels
        },
    )

    binding = routing.route(
        port_id=_port("signal"),
        capabilities=("B",),
    )

    assert binding.served_entity_ids == ("q0",)
    assert [
        (item.capability, item.entity_id, item.channel_id)
        for item in binding.channel_bindings
    ] == [("B", "q0", "drive-q0")]


def test_multi_channel_entity_binding_reaches_state_and_collect_commands() -> None:
    config = _multi_channel_config()
    product = observable_product(
        "signal_value",
        unit="ratio",
    )
    producer = instrument_product_producer(
        product,
        resource_port_id=_port("signal"),
        capability="signal",
    )
    product_use, record_use = record_product(product)
    experiment = typed_program(
        id="multi-channel-binding",
        kind="routing_test",
        point_domain=_empty_point_domain(),
        route_intents=[
            ResourceRouteIntent(
                port_id=_port("signal"),
                capabilities=("signal",),
                entity_uses=(relation_use(_entity("q0")),),
            )
        ],
        state=[
            set_state_field(
                resource_port_id=_port("signal"),
                capability_id="signal",
                field_path="level",
                value=_number(1.0),
                route_entities=(_entity("q0"),),
            )
        ],
        product_defs=[product],
        instrument_product_producers=[producer],
        product_uses=[product_use],
        record_uses=[record_use],
    )

    plan = _bind(experiment, config=config)
    program = build_execution_program(plan, instrument_order=("source-0",))

    assert not validate_config(config)
    assert plan.valid
    assert [
        binding.channel_id for binding in plan.points[0].routes[0].channel_bindings
    ] == ["drive-q0", "readout-q0"]
    state_stage = next(
        stage
        for stage in program.points[0].stages
        if isinstance(stage, ApplyStateStage)
    )
    collect_stage = next(
        stage for stage in program.points[0].stages if isinstance(stage, CollectStage)
    )
    assert [
        binding.channel_id
        for binding in state_stage.operations[0].targets[0].channel_bindings
    ] == ["drive-q0", "readout-q0"]
    assert [
        binding.channel_id
        for binding in collect_stage.operations[0].command.requests[0].channel_bindings
    ] == ["drive-q0", "readout-q0"]


def test_channel_state_identity_is_structured_and_injective() -> None:
    delimiter_in_entity = (RoutingChannelBinding(entity_id="a:b", channel_id="c"),)
    delimiter_in_channel = (RoutingChannelBinding(entity_id="a", channel_id="b:c"),)
    delimiter_in_group = (
        RoutingChannelBinding(
            entity_id="a",
            channel_id="b",
            group_ids=["x,y"],
        ),
    )
    separate_groups = (
        RoutingChannelBinding(
            entity_id="a",
            channel_id="b",
            group_ids=["x", "y"],
        ),
    )

    assert channel_signature(delimiter_in_entity) != channel_signature(
        delimiter_in_channel
    )
    assert channel_signature(delimiter_in_group) != channel_signature(separate_groups)


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
        port_id=_port("spectator_bias"),
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
        routing.route(port_id=_port("drive"), capabilities=("set_frequency",))

    assert error.value.code == "module_resource_port_ambiguous"


def test_routing_view_rejects_explicit_resource_entity_mismatch() -> None:
    routing = RoutingView.from_config(load_config())

    with pytest.raises(RoutingError) as error:
        routing.route(
            port_id=_port("drive"),
            capabilities=("set_frequency",),
            entity_ids=("q1",),
            fixed_resource_id=_physical("source-0"),
        )

    assert error.value.code == "module_resource_port_entity_mismatch"


def test_bound_plan_reports_shared_group_resource_conflict() -> None:
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

    problems = _bind(_two_route_experiment(), config=config).problems

    assert {problem.code for problem in problems} >= {
        "routing_shared_group_resource_conflict"
    }


def test_bound_plan_allows_configured_shared_group_resource_fanout() -> None:
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

    problems = _bind(_two_route_experiment(), config=config).problems

    assert "routing_shared_group_resource_conflict" not in {
        problem.code for problem in problems
    }


def test_bound_plan_reports_channel_shared_by_multiple_ports() -> None:
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

    problems = _bind(_two_route_experiment(), config=config).problems

    assert {problem.code for problem in problems} >= {"routing_channel_shared_by_ports"}


def test_bound_plan_allows_configured_channel_route_port_fanout() -> None:
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

    problems = _bind(_two_route_experiment(), config=config).problems

    assert "routing_channel_shared_by_ports" not in {
        problem.code for problem in problems
    }


def test_bound_plan_rejects_product_duplicates_after_route_resolution() -> None:
    config = load_config()
    channels = [
        channel.model_copy(update={"max_route_ports_per_point": 2})
        for channel in config.topology.channels
    ]
    system = config.system.model_copy(
        update={"topology": config.topology.model_copy(update={"channels": channels})}
    )
    selected_config = config.model_copy(update={"system": system})
    products = (
        observable_product("left_signal"),
        observable_product("right_signal"),
    )
    producers = (
        instrument_product_producer(
            products[0],
            resource_port_id=_port("left"),
            provider_key="signal",
        ),
        instrument_product_producer(
            products[1],
            resource_port_id=_port("right"),
            provider_key="signal",
        ),
    )
    uses_and_records = tuple(record_product(product) for product in products)
    experiment = typed_program(
        id="resolved-product-duplicate",
        kind="routing_test",
        point_domain=_empty_point_domain(),
        route_intents=[
            ResourceRouteIntent(
                port_id=_port("left"),
                fixed_resource_id=_physical("source-0"),
            ),
            ResourceRouteIntent(
                port_id=_port("right"),
                fixed_resource_id=_physical("source-0"),
            ),
        ],
        product_defs=products,
        instrument_product_producers=producers,
        product_uses=[item[0] for item in uses_and_records],
        record_uses=[item[1] for item in uses_and_records],
    )

    plan = _bind(experiment, config=selected_config)

    assert not plan.valid
    assert [problem.code for problem in plan.problems] == [
        "collection_provider_key_duplicate"
    ]


def test_bound_plan_rejects_broadcast_and_explicit_product_duplicates() -> None:
    products = (
        observable_product("broadcast_signal"),
        observable_product("explicit_signal"),
    )
    producers = (
        instrument_product_producer(products[0], provider_key="signal"),
        instrument_product_producer(
            products[1],
            physical_resource_id=_physical("source-0"),
            provider_key="signal",
        ),
    )
    uses_and_records = tuple(record_product(product) for product in products)
    experiment = typed_program(
        id="broadcast-product-duplicate",
        kind="routing_test",
        point_domain=_empty_point_domain(),
        product_defs=products,
        instrument_product_producers=producers,
        product_uses=[item[0] for item in uses_and_records],
        record_uses=[item[1] for item in uses_and_records],
    )

    plan = _bind(experiment)

    assert not plan.valid
    assert [problem.code for problem in plan.problems] == [
        "collection_provider_key_duplicate"
    ]


def test_bound_plan_reports_conflicting_state_field_values() -> None:
    experiment = typed_program(
        id="conflicting-state",
        kind="routing_test",
        point_domain=_empty_point_domain(),
        state=[
            set_state_field(
                _resource("source-0"),
                capability_id="set_frequency",
                field_path="frequency",
                value=_number(1.0),
            ),
            set_state_field(
                _resource("source-0"),
                capability_id="set_frequency",
                field_path="frequency",
                value=_number(2.0),
            ),
        ],
    )

    problems = _bind(experiment).problems

    assert {problem.code for problem in problems} >= {
        "experiment_conflicting_desired_state"
    }


def test_bound_plan_reports_invalid_route_entity_member() -> None:
    experiment = typed_program(
        id="invalid-route-entity",
        kind="routing_test",
        point_domain=_empty_point_domain(),
        route_intents=[
            ResourceRouteIntent(
                port_id=_port("source"),
                capabilities=("set_frequency",),
                entity_uses=(
                    relation_use(
                        scalar_value_expr(lit(1), expected_type=Scalar(Int()))
                    ),
                ),
            ),
            ResourceRouteIntent(
                port_id=_port("empty-source"),
                capabilities=("set_frequency",),
                entity_uses=(
                    relation_use(
                        series_value_expr(
                            values([]),
                            expected_type=Series(Scalar(Entity())),
                        )
                    ),
                ),
            ),
        ],
    )

    problems = _bind(experiment).problems

    assert [problem.code for problem in problems].count(
        "module_resource_entity_invalid"
    ) == 2


def test_unresolved_route_entity_input_is_rejected_during_linking() -> None:
    experiment = typed_program(
        id="failed-route-entity-expression",
        kind="routing_test",
        point_domain=_empty_point_domain(),
        route_intents=[
            ResourceRouteIntent(
                port_id=_port("source"),
                capabilities=("set_frequency",),
                entity_uses=(
                    relation_use(
                        series_value_expr(
                            input_series("missing"),
                            expected_type=Series(Scalar(Entity())),
                            bindings=RelationTypeBindings(
                                inputs={"missing": Series(Scalar(Entity()))}
                            ),
                        ),
                    ),
                ),
            )
        ],
    )
    with pytest.raises(CheckFailed) as failure:
        _bind(experiment)

    assert {problem.code for problem in failure.value.problems} == {
        "linked_input_unresolved"
    }


def _two_route_experiment() -> TypedProgram:
    return typed_program(
        id="two-route-conflict",
        kind="routing_test",
        point_domain=_empty_point_domain(),
        route_intents=[
            ResourceRouteIntent(
                port_id=_port("drive_a"),
                capabilities=("set_frequency",),
                entity_uses=(relation_use(_entity("q0")),),
            ),
            ResourceRouteIntent(
                port_id=_port("drive_b"),
                capabilities=("set_frequency",),
                entity_uses=(relation_use(_entity("q1")),),
            ),
        ],
    )


def _empty_point_domain() -> PointDomain:
    return PointDomain(root=POINT_UNIT)


def _bind(
    experiment: TypedProgram,
    *,
    config: ConfigProfileSnapshot | None = None,
) -> BoundPlan:
    environment = replace(
        validate_config_environment(config or load_config()),
        parameters=parameters(),
    )
    return materialize_local_plan(link_program(experiment, environment))


def _routing_constraint_config(
    *,
    resources: list[RoutingResource],
    edges: list[RoutingEdge],
    groups: list[SharedResourceGroup] | None = None,
    channels: list[Channel] | None = None,
):
    config = load_config()
    source = config.instrument_registry.instruments[0]
    route_bindings = [binding for edge in edges for binding in edge.bindings]
    group_ids_by_channel: dict[str, set[str]] = {}
    for binding in route_bindings:
        group_ids_by_channel.setdefault(binding.channel_id, set()).update(
            binding.group_ids
        )
    selected_channels = list(channels or ())
    if channels is None:
        selected_channels = [
            Channel(
                id=channel_id,
                kind="routing_test",
                signal="routing_test",
                port=channel_id,
                group_ids=sorted(group_ids),
            )
            for channel_id, group_ids in sorted(group_ids_by_channel.items())
        ]
    selected_groups = list(groups or ())
    if groups is None:
        members_by_group: dict[str, list[str]] = {}
        for channel_id, group_ids in group_ids_by_channel.items():
            for group_id in group_ids:
                members_by_group.setdefault(group_id, []).append(channel_id)
        selected_groups = [
            SharedResourceGroup(
                id=group_id,
                kind="routing_test",
                members=sorted(members),
            )
            for group_id, members in sorted(members_by_group.items())
        ]
    selected_channel_ids = {channel.id for channel in selected_channels}
    selected_group_ids = {group.id for group in selected_groups}
    system = config.system.model_copy(
        update={
            "topology": config.topology.model_copy(
                update={
                    "entities": [
                        *config.topology.entities,
                        EntityRef(id="q1", kind="logical_qubit"),
                    ],
                    "groups": [
                        *(
                            group
                            for group in config.topology.groups
                            if group.id not in selected_group_ids
                        ),
                        *selected_groups,
                    ],
                    "channels": [
                        *(
                            channel
                            for channel in config.topology.channels
                            if channel.id not in selected_channel_ids
                        ),
                        *selected_channels,
                    ],
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


def _multi_channel_config() -> ConfigProfileSnapshot:
    config = load_config()
    routing = RoutingGraph(
        resources=[
            RoutingResource(
                id="source-0",
                capabilities=["signal"],
                served_entities=["q0"],
                channels=["drive-q0", "readout-q0"],
            )
        ],
        edges=[
            RoutingEdge(
                id="source-0-q0-signal",
                resource_id="source-0",
                entity_ids=["q0"],
                capabilities=["signal"],
                channels=["drive-q0", "readout-q0"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q0",
                        channel_id="drive-q0",
                        capability="signal",
                    ),
                    RoutingChannelBinding(
                        entity_id="q0",
                        channel_id="readout-q0",
                        capability="signal",
                    ),
                ],
            )
        ],
    )
    return config.model_copy(
        update={"system": config.system.model_copy(update={"routing": routing})}
    )
