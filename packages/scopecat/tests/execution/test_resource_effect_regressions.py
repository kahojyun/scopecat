from __future__ import annotations

from dataclasses import replace

import pytest

from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.semantic.model import AcquireEffect
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.compiler.typed.point_domain import (
    PointDomain,
)
from scopecat.compiler.typed.program import (
    CoreProgram,
    LogicalResourceRequirement,
    record_product,
    set_state_property,
)
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.config.environment import build_config_environment
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
)
from scopecat.graph.relations.model import lit
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat.kernel.value_types import Entity, Float, Scalar
from scopecat.measurements.products import ProductDef
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingEndpointBinding,
    RoutingGraph,
)
from tests.testkit.authoring import load_config, parameters
from tests.testkit.local_materialization import (
    LocalEffectInspection,
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.relation_plans import scalar_value_expr
from tests.testkit.typed_program import (
    bind_core_program,
    instrument_acquisition,
    observable_product,
    typed_program,
)


def _port(value: str) -> LogicalResourcePortId:
    return logical_resource_port_id(value)


def _number(value: float) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(Float()))


def _entity(value: str) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(Entity()))


def _unit_program(
    *,
    experiment_id: str,
    resource_requirements: tuple[LogicalResourceRequirement, ...] = (),
    state: tuple[SetStateSpec, ...] = (),
    products: tuple[ProductDef, ...] = (),
    acquisitions: tuple[AcquireEffect, ...] = (),
) -> CoreProgram:
    uses_and_records = tuple(record_product(product) for product in products)
    return typed_program(
        id=experiment_id,
        kind="resource_effect_regression",
        point_domain=PointDomain(axes=()),
        resource_requirements=resource_requirements,
        state=state,
        product_defs=products,
        instrument_acquisitions=acquisitions,
        product_uses=tuple(item[0] for item in uses_and_records),
        record_uses=tuple(item[1] for item in uses_and_records),
    )


def _bind(
    program: CoreProgram,
    *,
    config: ConfigProfileSnapshot,
) -> LocalEffectInspection:
    environment = replace(
        build_config_environment(config),
        parameters=parameters(),
    )
    return materialize_local_execution(bind_core_program(program, environment))


def test_record_products_keep_their_exact_logical_resource_bindings() -> None:
    config = _same_instrument_record_config()
    left = _port("left")
    right = _port("right")
    direct = _port("direct")
    left_product = observable_product("left-result")
    right_product = observable_product("right-result")
    direct_product = observable_product("direct-result")
    program = _unit_program(
        experiment_id="per-product-resource-bindings",
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=left,
                interfaces=("test.measure_left/v1",),
            ),
            LogicalResourceRequirement(
                port_id=right,
                interfaces=("test.measure_right/v1",),
            ),
            LogicalResourceRequirement(
                port_id=direct,
                interfaces=("test.measure_direct/v1",),
            ),
        ),
        products=(left_product, right_product, direct_product),
        acquisitions=(
            instrument_acquisition(
                left_product,
                resource_port_id=left,
                interface="test.measure_left/v1",
                result_id="left",
            ),
            instrument_acquisition(
                right_product,
                resource_port_id=right,
                interface="test.measure_right/v1",
                result_id="right",
            ),
            instrument_acquisition(
                direct_product,
                resource_port_id=direct,
                interface="test.measure_direct/v1",
                result_id="direct",
            ),
        ),
    )

    plan = _bind(program, config=config)
    requests = {
        request.id: request
        for operation in operations_of_type(plan, CollectOperation, point_index=0)
        for request in operation.command.requests
    }
    assert {
        key: (
            tuple(request.entity_ids),
            tuple(binding.channel_id for binding in request.channel_bindings),
        )
        for key, request in requests.items()
    } == {
        "left": (("q0",), ("drive-q0",)),
        "right": (("q1",), ("readout-q0",)),
        "direct": ((), ()),
    }


def test_each_effect_uses_only_its_explicit_interface_endpoints() -> None:
    config = load_config()
    routing = RoutingGraph(
        bindings=[
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.a/v1",
                entity_id="q0",
                channel_id="drive-q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.b/v1",
                entity_id="q0",
                channel_id="readout-q0",
            ),
        ],
    )
    config = config.model_copy(
        update={"system": config.system.model_copy(update={"routing": routing})}
    )
    port = _port("combined")
    a_product = observable_product("A-result")
    b_product = observable_product("B-result")
    program = _unit_program(
        experiment_id="explicit-interface-endpoints",
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=port,
                interfaces=("test.a/v1", "test.b/v1"),
                entity_uses=(relation_use(_entity("q0")),),
            ),
        ),
        state=(
            set_state_property(
                resource_port_id=port,
                interface_id="test.a/v1",
                property_id="level",
                value=_number(1.0),
            ),
        ),
        products=(a_product, b_product),
        acquisitions=(
            instrument_acquisition(
                a_product,
                resource_port_id=port,
                interface="test.a/v1",
                result_id="A-result",
            ),
            instrument_acquisition(
                b_product,
                resource_port_id=port,
                interface="test.b/v1",
                result_id="B-result",
            ),
        ),
    )

    plan = _bind(program, config=config)

    [state] = operations_of_type(plan, ApplyStateOperation, point_index=0)
    assert state.instrument_id == "source-0"
    assert [
        (binding.interface_id, binding.channel_id)
        for binding in state.targets[0].channel_bindings
    ] == [("test.a/v1", "drive-q0")]

    requests = {
        request.id: request
        for operation in operations_of_type(plan, CollectOperation, point_index=0)
        for request in operation.command.requests
    }
    assert {
        key: (
            request.interface_id,
            tuple(
                (binding.interface_id, binding.channel_id)
                for binding in request.channel_bindings
            ),
        )
        for key, request in requests.items()
    } == {
        "A-result": ("test.a/v1", (("test.a/v1", "drive-q0"),)),
        "B-result": ("test.b/v1", (("test.b/v1", "readout-q0"),)),
    }


def test_logical_state_bindings_reach_required_instrument() -> None:
    config = _split_instrument_config()
    source = _port("source")
    first_state = set_state_property(
        resource_port_id=source,
        interface_id="test.set_level/v1",
        property_id="level",
        value=_number(1.0),
    )

    single_plan = _bind(
        _unit_program(
            experiment_id="logical-state-requirements",
            resource_requirements=(
                LogicalResourceRequirement(
                    port_id=source,
                    interfaces=("test.set_level/v1",),
                    entity_uses=(relation_use(_entity("q0")),),
                ),
            ),
            state=(first_state,),
        ),
        config=config,
    )
    target = operations_of_type(single_plan, ApplyStateOperation, point_index=0)[
        0
    ].targets[0]
    assert target.entity_ids == ("q0",)
    assert tuple(binding.channel_id for binding in target.channel_bindings) == (
        "drive-q0",
    )
    assert [
        (requirement.kind, requirement.id)
        for requirement in single_plan.resource_requirements
    ] == [("instrument", "source-0")]


def test_logical_state_does_not_broadcast_across_instruments() -> None:
    config = _split_instrument_config()
    source = _port("source")
    program = _unit_program(
        experiment_id="ambiguous-logical-state-claim",
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=source,
                interfaces=("test.set_level/v1",),
                entity_uses=(
                    relation_use(_entity("q0")),
                    relation_use(_entity("q1")),
                ),
            ),
        ),
        state=(
            set_state_property(
                resource_port_id=source,
                interface_id="test.set_level/v1",
                property_id="level",
                value=_number(1.0),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as failure:
        _bind(program, config=config)

    assert [problem.code for problem in failure.value.problems] == [
        "module_resource_port_ambiguous"
    ]


def test_entity_only_targets_survive_bound_and_execution_boundaries() -> None:
    config = _entity_only_config()
    signal = _port("signal")
    product = observable_product("signal-result")
    program = _unit_program(
        experiment_id="entity-only-targets",
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=signal,
                interfaces=("test.set_level/v1", "test.measure_signal/v1"),
                entity_uses=(relation_use(_entity("q0")),),
            ),
        ),
        state=(
            set_state_property(
                resource_port_id=signal,
                interface_id="test.set_level/v1",
                property_id="level",
                value=_number(1.0),
            ),
        ),
        products=(product,),
        acquisitions=(
            instrument_acquisition(
                product,
                resource_port_id=signal,
                interface="test.measure_signal/v1",
                result_id="signal",
            ),
        ),
    )

    plan = _bind(program, config=config)
    execution = plan

    state_property = operations_of_type(plan, ApplyStateOperation, point_index=0)[
        0
    ].targets[0]
    request = operations_of_type(plan, CollectOperation, point_index=0)[
        0
    ].command.requests[0]
    assert (state_property.entity_ids, state_property.channel_bindings) == (("q0",), ())
    assert (request.entity_ids, request.channel_bindings) == (["q0"], [])

    target = operations_of_type(execution, ApplyStateOperation, point_index=0)[
        0
    ].targets[0]
    request = operations_of_type(execution, CollectOperation, point_index=0)[
        0
    ].command.requests[0]
    assert (target.entity_ids, target.channel_bindings) == (("q0",), ())
    assert (tuple(request.entity_ids), tuple(request.channel_bindings)) == (("q0",), ())


def test_distinct_logical_ports_cannot_own_one_physical_state_slot() -> None:
    config = _entity_only_config()
    left = _port("left")
    right = _port("right")
    program = _unit_program(
        experiment_id="aliased-logical-state-target",
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=left,
                interfaces=("test.set_level/v1",),
                entity_uses=(relation_use(_entity("q0")),),
            ),
            LogicalResourceRequirement(
                port_id=right,
                interfaces=("test.set_level/v1",),
                entity_uses=(relation_use(_entity("q0")),),
            ),
        ),
        state=(
            set_state_property(
                resource_port_id=left,
                interface_id="test.set_level/v1",
                property_id="level",
                value=_number(1.0),
            ),
            set_state_property(
                resource_port_id=right,
                interface_id="test.set_level/v1",
                property_id="level",
                value=_number(1.0),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as failure:
        _bind(program, config=config)

    assert "experiment_aliased_desired_state_target" in {
        problem.code for problem in failure.value.problems
    }


def _same_instrument_record_config() -> ConfigProfileSnapshot:
    config = load_config()
    topology = config.topology.model_copy(
        update={
            "entities": [
                *config.topology.entities,
                EntityRef(id="q1", kind="logical_device"),
            ]
        }
    )
    routing = RoutingGraph(
        bindings=[
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.measure_left/v1",
                entity_id="q0",
                channel_id="drive-q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.measure_right/v1",
                entity_id="q1",
                channel_id="readout-q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.measure_direct/v1",
            ),
        ],
    )
    return config.model_copy(
        update={
            "system": config.system.model_copy(
                update={"topology": topology, "routing": routing}
            )
        }
    )


def _split_instrument_config() -> ConfigProfileSnapshot:
    config = load_config()
    source = config.instrument_registry.instruments[0]
    topology = config.topology.model_copy(
        update={
            "entities": [
                *config.topology.entities,
                EntityRef(id="q1", kind="logical_device"),
            ],
        }
    )
    routing = RoutingGraph(
        bindings=[
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id="test.set_level/v1",
                entity_id="q0",
                channel_id="drive-q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-1",
                interface_id="test.set_level/v1",
                entity_id="q1",
                channel_id="readout-q0",
            ),
        ],
    )
    system = config.system.model_copy(
        update={
            "topology": topology,
            "instrument_registry": config.instrument_registry.model_copy(
                update={
                    "instruments": [
                        source,
                        source.model_copy(
                            update={
                                "id": "source-1",
                                "exclusivity_key": "source-1",
                            }
                        ),
                    ]
                }
            ),
            "routing": routing,
        }
    )
    return config.model_copy(update={"system": system})


def _entity_only_config() -> ConfigProfileSnapshot:
    config = load_config()
    routing = RoutingGraph(
        bindings=[
            RoutingEndpointBinding(
                instrument_id="source-0",
                interface_id=interface_id,
                entity_id="q0",
            )
            for interface_id in (
                "test.set_level/v1",
                "test.measure_signal/v1",
            )
        ],
    )
    return config.model_copy(
        update={"system": config.system.model_copy(update={"routing": routing})}
    )
