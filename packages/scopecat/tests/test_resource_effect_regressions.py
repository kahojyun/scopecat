from __future__ import annotations

from dataclasses import replace

from scopecat._compiler.binding import bind_program
from scopecat._compiler.bound import BoundPlan
from scopecat._compiler.environment import validate_config_environment
from scopecat._compiler.point_domain import PointDomain
from scopecat._compiler.products import InstrumentProductProducer, ProductDef
from scopecat._compiler.program import (
    ResourceRouteIntent,
    TypedProgram,
    instrument_product_producer,
    observable_product,
    record_product,
    set_state_field,
    typed_program,
)
from scopecat._compiler.run_plan import build_run_plan_record
from scopecat._execution.engine import ExecutionEngine
from scopecat._execution.journal import (
    MemoryCollectionRepository,
    MemoryExecutionJournal,
    MemoryPayloadEvidenceCommitter,
)
from scopecat._execution.lowering import build_execution_program
from scopecat._execution.program import (
    ApplyStateOperation,
    ApplyStateStage,
    CollectStage,
    ExecutionProgram,
    PointProgram,
    StateTarget,
)
from scopecat._point_domain_algebra import POINT_UNIT
from scopecat._relation_use import relation_use
from scopecat._relations import lit
from scopecat._resource_identity import (
    LogicalResourcePortId,
    logical_resource_port_id,
)
from scopecat._value_expressions import ScalarValueExpr
from scopecat.instruments import (
    ActionReceipt,
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    CommandChannelBinding,
    InstrumentActionCommand,
    InstrumentDescription,
    InstrumentReadback,
    InstrumentStateCommand,
    InstrumentStateField,
    InstrumentStateSnapshot,
    apply_state_command_to_snapshot,
    capability,
    float_field,
)
from scopecat.measurement_recording import MemoryMeasurementRecordCommitter
from scopecat.models.config import (
    ConfigProfileSnapshot,
    RoutingChannelBinding,
    RoutingEdge,
    RoutingGraph,
    RoutingResource,
    SharedResourceGroup,
)
from scopecat.models.entity import EntityRef
from scopecat.models.run_plan import RunPlanPointInstrumentExecution
from scopecat.models.state import StateValue
from scopecat.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.value_types import Entity, Float, Scalar, String
from tests.support.authoring import load_config, parameters
from tests.support.experiment_preview import config_with_physical_resources
from tests.support.relation_plans import scalar_value_expr


def _port(value: str) -> LogicalResourcePortId:
    return logical_resource_port_id(value)


def _text(value: str) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(String()))


def _number(value: float) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(Float()))


def _entity(value: str) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(Entity()))


def _unit_program(
    *,
    experiment_id: str,
    route_intents: tuple[ResourceRouteIntent, ...] = (),
    state=(),
    products: tuple[ProductDef, ...] = (),
    producers: tuple[InstrumentProductProducer, ...] = (),
) -> TypedProgram:
    uses_and_records = tuple(record_product(product) for product in products)
    return typed_program(
        id=experiment_id,
        kind="resource_effect_regression",
        point_domain=PointDomain(root=POINT_UNIT),
        route_intents=route_intents,
        state=state,
        product_defs=products,
        instrument_product_producers=producers,
        product_uses=tuple(item[0] for item in uses_and_records),
        record_uses=tuple(item[1] for item in uses_and_records),
    )


def _bind(
    program: TypedProgram,
    *,
    config: ConfigProfileSnapshot,
) -> BoundPlan:
    environment = replace(
        validate_config_environment(config),
        parameters=parameters(),
    )
    return bind_program(program, environment)


def test_record_products_keep_their_exact_logical_route_bindings() -> None:
    config = _same_instrument_record_config()
    left = _port("left")
    right = _port("right")
    left_product = observable_product("left-result")
    right_product = observable_product("right-result")
    direct_product = observable_product("direct-result")
    program = _unit_program(
        experiment_id="per-product-route-bindings",
        route_intents=(
            ResourceRouteIntent(
                port_id=left,
                capabilities=("measure.left",),
            ),
            ResourceRouteIntent(
                port_id=right,
                capabilities=("measure.right",),
            ),
        ),
        products=(left_product, right_product, direct_product),
        producers=(
            instrument_product_producer(
                left_product,
                resource_port_id=left,
                capability="measure.left",
                provider_key="left",
            ),
            instrument_product_producer(
                right_product,
                resource_port_id=right,
                capability="measure.right",
                provider_key="right",
            ),
            instrument_product_producer(
                direct_product,
                physical_resource_id="source-0",
                capability="measure.direct",
                provider_key="direct",
            ),
        ),
    )

    plan = _bind(program, config=config)
    execution = build_execution_program(plan)

    assert plan.valid, plan.problems
    requests_by_key = {
        request.provider_key: request
        for collect in plan.points[0].collect
        for request in collect.requests
    }
    assert {
        key: (
            request.resource_port_id,
            request.entity_ids,
            tuple(binding.channel_id for binding in request.channel_bindings),
        )
        for key, request in requests_by_key.items()
    } == {
        "left": (left, ("q0",), ("drive-q0",)),
        "right": (right, ("q1",), ("readout-q0",)),
        "direct": (None, (), ()),
    }

    collect_stage = next(
        stage for stage in execution.points[0].stages if isinstance(stage, CollectStage)
    )
    requests = {
        request.id: request for request in collect_stage.operations[0].command.requests
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


def test_logical_product_schema_is_invariant_across_instrument_producers() -> None:
    config = config_with_physical_resources(
        {
            "source-0": ("measure.signal",),
            "source-1": ("measure.signal",),
        }
    )
    product = observable_product("signal", unit="ratio")
    product_use, record_use = record_product(product)
    source_0_producer = instrument_product_producer(
        product,
        id="source-0-signal",
        physical_resource_id="source-0",
        capability="measure.signal",
        provider_key="raw-signal",
    )
    source_1_producer = instrument_product_producer(
        product,
        id="source-1-signal",
        physical_resource_id="source-1",
        capability="measure.signal",
        provider_key="demodulated-signal",
    )
    source_0_program = typed_program(
        id="producer-independent-schema",
        kind="resource_effect_regression",
        point_domain=PointDomain(root=POINT_UNIT),
        product_defs=(product,),
        instrument_product_producers=(source_0_producer,),
        product_uses=(product_use,),
        record_uses=(record_use,),
    )
    source_1_program = source_0_program.model_copy(
        update={"instrument_product_producers": (source_1_producer,)},
        deep=True,
    )

    source_0_plan = _bind(source_0_program, config=config)
    source_1_plan = _bind(source_1_program, config=config)

    assert source_0_plan.valid, source_0_plan.problems
    assert source_1_plan.valid, source_1_plan.problems
    assert source_0_plan.product_defs == source_1_plan.product_defs
    assert source_0_plan.records == source_1_plan.records
    assert (
        source_0_plan.expected_dataset_schema == source_1_plan.expected_dataset_schema
    )

    source_0_collect = source_0_plan.points[0].collect[0]
    source_1_collect = source_1_plan.points[0].collect[0]
    source_0_request = source_0_collect.requests[0]
    source_1_request = source_1_collect.requests[0]
    assert source_0_request != source_1_request
    assert (
        source_0_collect.resource_id.value,
        source_0_request.provider_key,
        source_0_request.capability,
    ) == ("source-0", "raw-signal", "measure.signal")
    assert (
        source_1_collect.resource_id.value,
        source_1_request.provider_key,
        source_1_request.capability,
    ) == ("source-1", "demodulated-signal", "measure.signal")

    assert source_0_plan.local_product_realizations is not None
    assert source_1_plan.local_product_realizations is not None
    assert (
        source_0_plan.local_product_realizations.selected_for(product_use.id).producer
        == source_0_producer
    )
    assert (
        source_1_plan.local_product_realizations.selected_for(product_use.id).producer
        == source_1_producer
    )


def test_multi_capability_route_unions_capability_specific_edges() -> None:
    config = _same_instrument_record_config()
    combined = _port("combined")
    left_product = observable_product("left-result")
    right_product = observable_product("right-result")
    all_product = observable_product("all-result")
    program = _unit_program(
        experiment_id="capability-indexed-route-topology",
        route_intents=(
            ResourceRouteIntent(
                port_id=combined,
                capabilities=("measure.left", "measure.right"),
            ),
        ),
        products=(left_product, right_product, all_product),
        producers=(
            instrument_product_producer(
                left_product,
                resource_port_id=combined,
                capability="measure.left",
                provider_key="left",
            ),
            instrument_product_producer(
                right_product,
                resource_port_id=combined,
                capability="measure.right",
                provider_key="right",
            ),
            instrument_product_producer(
                all_product,
                resource_port_id=combined,
                provider_key="all",
            ),
        ),
    )

    plan = _bind(program, config=config)

    assert plan.valid, plan.problems
    route = plan.points[0].routes[0]
    assert route.served_entity_ids == ("q0", "q1")
    assert {
        (binding.capability, binding.entity_id, binding.channel_id)
        for binding in route.channel_bindings
    } == {
        ("measure.left", "q0", "drive-q0"),
        ("measure.right", "q1", "readout-q0"),
    }
    requests_by_key = {
        request.provider_key: request
        for collect in plan.points[0].collect
        for request in collect.requests
    }
    assert {
        key: tuple(binding.channel_id for binding in request.channel_bindings)
        for key, request in requests_by_key.items()
    } == {
        "left": ("drive-q0",),
        "right": ("readout-q0",),
        "all": ("drive-q0", "readout-q0"),
    }


def test_capability_unspecified_collection_stays_within_its_logical_port() -> None:
    config = load_config()
    routing = RoutingGraph(
        resources=[
            RoutingResource(
                id="source-0",
                capabilities=["A", "B"],
                served_entities=["q0"],
                channels=["drive-q0", "readout-q0"],
            )
        ],
        edges=[
            RoutingEdge(
                id="source-0-A",
                resource_id="source-0",
                entity_ids=["q0"],
                capabilities=["A"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q0",
                        channel_id="drive-q0",
                        capability="A",
                    )
                ],
            ),
            RoutingEdge(
                id="source-0-B",
                resource_id="source-0",
                entity_ids=["q0"],
                capabilities=["B"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q0",
                        channel_id="readout-q0",
                        capability="B",
                    )
                ],
            ),
        ],
    )
    config = config.model_copy(
        update={"system": config.system.model_copy(update={"routing": routing})}
    )
    port = _port("A-only")
    product = observable_product("result")
    program = _unit_program(
        experiment_id="capability-unspecified-logical-record",
        route_intents=(
            ResourceRouteIntent(
                port_id=port,
                capabilities=("A",),
                entity_uses=(relation_use(_entity("q0")),),
            ),
        ),
        products=(product,),
        producers=(
            instrument_product_producer(
                product,
                resource_port_id=port,
                provider_key="result",
            ),
        ),
    )

    plan = _bind(program, config=config)

    assert plan.valid, plan.problems
    request = plan.points[0].collect[0].requests[0]
    assert [
        (binding.capability, binding.channel_id) for binding in request.channel_bindings
    ] == [(None, "drive-q0")]


def test_mixed_explicit_and_fallback_route_topology_closes_durably() -> None:
    config = load_config()
    duplicate = RoutingChannelBinding(
        entity_id="q0",
        channel_id="drive-q0",
        capability="B",
    )
    routing = RoutingGraph(
        resources=[
            RoutingResource(
                id="source-0",
                capabilities=["A", "B"],
                served_entities=["q0"],
                channels=["drive-q0"],
            )
        ],
        edges=[
            RoutingEdge(
                id="source-0-B",
                resource_id="source-0",
                entity_ids=["q0"],
                capabilities=["B"],
                channels=["drive-q0"],
                bindings=[duplicate, duplicate.model_copy(deep=True)],
            )
        ],
    )
    config = config.model_copy(
        update={"system": config.system.model_copy(update={"routing": routing})}
    )
    port = _port("source")
    program = _unit_program(
        experiment_id="mixed-explicit-fallback-topology",
        route_intents=(
            ResourceRouteIntent(
                port_id=port,
                capabilities=("A", "B"),
                entity_uses=(relation_use(_entity("q0")),),
            ),
        ),
        state=(
            set_state_field(
                resource_port_id=port,
                capability_id="A",
                field_path="level",
                value=_number(1.0),
                route_entities=(_entity("q0"),),
            ),
        ),
    )

    plan = _bind(program, config=config)
    durable = build_run_plan_record(
        plan,
        execution=RunPlanPointInstrumentExecution(
            unit_id="point-instrument",
            backend_id="scopecat.point-instrument.v1",
            provider_id="tests.resource-effects",
        ),
    )

    assert plan.valid, plan.problems
    assert [
        (binding.capability, binding.channel_id)
        for binding in plan.points[0].routes[0].channel_bindings
    ] == [("B", "drive-q0"), ("A", "drive-q0")]
    assert [
        (binding.capability, binding.channel_id)
        for binding in plan.points[0].desired_state[0].fields[0].channel_bindings
    ] == [("A", "drive-q0")]
    assert durable.state_changes[0].resource_port_id == "source"


def test_direct_physical_state_bindings_reach_claims_and_shared_constraints() -> None:
    config = _shared_group_config()
    first_state = set_state_field(
        _text("source-0"),
        capability_id="set.level",
        field_path="level",
        value=_number(1.0),
        route_entities=(_entity("q0"),),
    )
    second_state = set_state_field(
        _text("source-1"),
        capability_id="set.level",
        field_path="level",
        value=_number(2.0),
        route_entities=(_entity("q1"),),
    )

    single_plan = _bind(
        _unit_program(experiment_id="direct-state-claims", state=(first_state,)),
        config=config,
    )
    execution = build_execution_program(single_plan)

    assert single_plan.valid, single_plan.problems
    field = single_plan.points[0].desired_state[0].fields[0]
    assert field.entity_ids == ("q0",)
    assert tuple(binding.channel_id for binding in field.channel_bindings) == (
        "drive-q0",
    )
    assert [(claim.kind, claim.id) for claim in execution.resource_claims] == [
        ("instrument", "source-0"),
        ("channel", "drive-q0"),
        ("group", "shared.lo"),
    ]

    conflicting_plan = _bind(
        _unit_program(
            experiment_id="direct-state-shared-group-conflict",
            state=(first_state, second_state),
        ),
        config=config,
    )

    assert not conflicting_plan.valid
    assert "routing_shared_group_resource_conflict" in {
        problem.code for problem in conflicting_plan.problems
    }


def test_entity_only_targets_survive_bound_and_execution_boundaries() -> None:
    config = _entity_only_config()
    signal = _port("signal")
    product = observable_product("signal-result")
    program = _unit_program(
        experiment_id="entity-only-targets",
        route_intents=(
            ResourceRouteIntent(
                port_id=signal,
                capabilities=("set.level", "measure.signal"),
                entity_uses=(relation_use(_entity("q0")),),
            ),
        ),
        state=(
            set_state_field(
                resource_port_id=signal,
                capability_id="set.level",
                field_path="level",
                value=_number(1.0),
                route_entities=(_entity("q0"),),
            ),
        ),
        products=(product,),
        producers=(
            instrument_product_producer(
                product,
                resource_port_id=signal,
                capability="measure.signal",
                provider_key="signal",
            ),
        ),
    )

    plan = _bind(program, config=config)
    execution = build_execution_program(plan)

    assert plan.valid, plan.problems
    state_field = plan.points[0].desired_state[0].fields[0]
    request = plan.points[0].collect[0].requests[0]
    assert (state_field.entity_ids, state_field.channel_bindings) == (("q0",), ())
    assert (request.entity_ids, request.channel_bindings) == (("q0",), ())

    state_stage = next(
        stage
        for stage in execution.points[0].stages
        if isinstance(stage, ApplyStateStage)
    )
    collect_stage = next(
        stage for stage in execution.points[0].stages if isinstance(stage, CollectStage)
    )
    target = state_stage.operations[0].targets[0]
    request = collect_stage.operations[0].command.requests[0]
    assert (target.entity_ids, target.channel_bindings) == (("q0",), ())
    assert (tuple(request.entity_ids), tuple(request.channel_bindings)) == (("q0",), ())


def test_distinct_logical_ports_cannot_own_one_physical_state_slot() -> None:
    config = _entity_only_config()
    left = _port("left")
    right = _port("right")
    program = _unit_program(
        experiment_id="aliased-logical-state-target",
        route_intents=(
            ResourceRouteIntent(
                port_id=left,
                capabilities=("set.level",),
                entity_uses=(relation_use(_entity("q0")),),
            ),
            ResourceRouteIntent(
                port_id=right,
                capabilities=("set.level",),
                entity_uses=(relation_use(_entity("q0")),),
            ),
        ),
        state=(
            set_state_field(
                resource_port_id=left,
                capability_id="set.level",
                field_path="level",
                value=_number(1.0),
                route_entities=(_entity("q0"),),
            ),
            set_state_field(
                resource_port_id=right,
                capability_id="set.level",
                field_path="level",
                value=_number(1.0),
                route_entities=(_entity("q0"),),
            ),
        ),
    )

    plan = _bind(program, config=config)

    assert not plan.valid
    assert "experiment_aliased_desired_state_target" in {
        problem.code for problem in plan.problems
    }


def test_scoped_same_field_targets_survive_snapshot_reconciliation() -> None:
    q0_binding = CommandChannelBinding(entity_id="q0", channel_id="drive-q0")
    q1_binding = CommandChannelBinding(entity_id="q1", channel_id="readout-q0")
    driver = _ScopedStateDriver(
        InstrumentStateSnapshot(
            instrument_id="source-0",
            fields=[
                InstrumentStateField(
                    capability_id="set_gain",
                    field_path="gain",
                    value=StateValue(1.0),
                    entity_ids=["q0"],
                    channel_bindings=[q0_binding],
                ),
                InstrumentStateField(
                    capability_id="set_gain",
                    field_path="gain",
                    value=StateValue(0.0),
                    entity_ids=["q1"],
                    channel_bindings=[q1_binding],
                ),
            ],
        )
    )
    program = ExecutionProgram(
        experiment_id="scoped-same-field-reconciliation",
        points=(
            PointProgram(
                point_index=0,
                point_uid="scoped-same-field-point",
                coordinates={},
                stages=(
                    ApplyStateStage(
                        operations=(
                            ApplyStateOperation(
                                operation_id="scoped-same-field-point.state.source-0",
                                instrument_id="source-0",
                                targets=(
                                    StateTarget(
                                        capability_id="set_gain",
                                        field_path="gain",
                                        value=StateValue(1.0),
                                        entity_ids=("q0",),
                                        channel_bindings=(q0_binding,),
                                    ),
                                    StateTarget(
                                        capability_id="set_gain",
                                        field_path="gain",
                                        value=StateValue(2.0),
                                        entity_ids=("q1",),
                                        channel_bindings=(q1_binding,),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        product_uses=(),
        collection_product_use_ids=(),
        record_projections=(),
        resource_order=("source-0",),
    )

    result = ExecutionEngine(
        run_id="scoped-same-field-run",
        program=program,
        drivers={driver.instrument_id: driver},
        descriptions={driver.instrument_id: driver.describe()},
        journal=MemoryExecutionJournal(),
        measurements=MemoryMeasurementRecordCommitter(),
        readbacks=MemoryCollectionRepository(),
        payloads=MemoryPayloadEvidenceCommitter(),
    ).run()

    assert result.status == "completed"
    assert len(driver.applied) == 1
    assert [field.entity_ids for field in driver.applied[0].fields] == [["q1"]]
    assert {
        (tuple(field.entity_ids), field.value) for field in driver.state.fields
    } == {
        (("q0",), StateValue(1.0)),
        (("q1",), StateValue(2.0)),
    }
    assert len(result.final_state) == 1
    assert len(result.final_state[0].fields) == 2


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
        resources=[
            RoutingResource(
                id="source-0",
                capabilities=["measure.left", "measure.right", "measure.direct"],
                served_entities=["q0", "q1"],
                channels=["drive-q0", "readout-q0"],
            )
        ],
        edges=[
            RoutingEdge(
                id="source-0-left",
                resource_id="source-0",
                entity_ids=["q0"],
                capabilities=["measure.left"],
                channels=["drive-q0"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q0",
                        channel_id="drive-q0",
                        capability="measure.left",
                    )
                ],
            ),
            RoutingEdge(
                id="source-0-right",
                resource_id="source-0",
                entity_ids=["q1"],
                capabilities=["measure.right"],
                channels=["readout-q0"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q1",
                        channel_id="readout-q0",
                        capability="measure.right",
                    )
                ],
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


def _shared_group_config() -> ConfigProfileSnapshot:
    config = load_config()
    source = config.instrument_registry.instruments[0]
    group = SharedResourceGroup(
        id="shared.lo",
        kind="local_oscillator",
        members=["drive-q0", "readout-q0"],
    )
    channels = [
        channel.model_copy(update={"group_ids": [group.id]})
        for channel in config.topology.channels
    ]
    topology = config.topology.model_copy(
        update={
            "entities": [
                *config.topology.entities,
                EntityRef(id="q1", kind="logical_device"),
            ],
            "channels": channels,
            "groups": [group],
        }
    )
    routing = RoutingGraph(
        resources=[
            RoutingResource(
                id="source-0",
                capabilities=["set.level"],
                served_entities=["q0"],
                channels=["drive-q0"],
            ),
            RoutingResource(
                id="source-1",
                capabilities=["set.level"],
                served_entities=["q1"],
                channels=["readout-q0"],
            ),
        ],
        edges=[
            RoutingEdge(
                id="source-0-level",
                resource_id="source-0",
                entity_ids=["q0"],
                capabilities=["set.level"],
                channels=["drive-q0"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q0",
                        channel_id="drive-q0",
                        capability="set.level",
                        group_ids=[group.id],
                    )
                ],
            ),
            RoutingEdge(
                id="source-1-level",
                resource_id="source-1",
                entity_ids=["q1"],
                capabilities=["set.level"],
                channels=["readout-q0"],
                bindings=[
                    RoutingChannelBinding(
                        entity_id="q1",
                        channel_id="readout-q0",
                        capability="set.level",
                        group_ids=[group.id],
                    )
                ],
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
                        source.model_copy(update={"id": "source-1"}),
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
        resources=[
            RoutingResource(
                id="source-0",
                capabilities=["set.level", "measure.signal"],
                served_entities=["q0"],
            )
        ]
    )
    return config.model_copy(
        update={"system": config.system.model_copy(update={"routing": routing})}
    )


class _ScopedStateDriver:
    instrument_id = "source-0"
    implementation_id = "tests.scoped-state-driver"
    implementation_version = "v1"

    def __init__(self, state: InstrumentStateSnapshot) -> None:
        self.state = state
        self.applied: list[InstrumentStateCommand] = []

    def describe(self) -> InstrumentDescription:
        return InstrumentDescription(
            instrument_id=self.instrument_id,
            implementation_id=self.implementation_id,
            implementation_version=self.implementation_version,
            capabilities=[capability("set_gain", fields=[float_field("gain")])],
        )

    def read_state(self) -> InstrumentStateSnapshot:
        return self.state.model_copy(deep=True)

    def apply_state(self, command: InstrumentStateCommand) -> ApplyReceipt:
        self.applied.append(command)
        self.state = apply_state_command_to_snapshot(self.state, command)
        return ApplyReceipt(status="applied")

    def action(self, command: InstrumentActionCommand) -> ActionReceipt:
        return ActionReceipt(
            status="not_performed",
            problems=(
                blocking_problem(
                    "scoped_state_driver_action_unsupported",
                    f"{self.instrument_id} does not support one-shot actions",
                    category=ProblemCategory.PROVIDER_CONTRACT,
                    phase=ProblemPhase.EXECUTION,
                    location=model_location(
                        "scoped_state_driver",
                        "actions",
                        command.operation_id,
                    ),
                ),
            ),
        )

    def collect(self, command: CollectCommand) -> CollectReceipt:
        del command
        return CollectReceipt(readback=InstrumentReadback())

    def cleanup(self) -> None:
        return None

    def abort(self) -> None:
        return None
