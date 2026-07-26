from __future__ import annotations

from dataclasses import replace

import pytest

from scopecat.compiler.frontend.environment import build_config_environment
from scopecat.compiler.relations.model import lit
from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.semantic.model import AcquireEffect
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.compiler.typed.point_domain import (
    PointDomain,
)
from scopecat.compiler.typed.products import ProductDef
from scopecat.compiler.typed.program import (
    CoreProgram,
    LogicalResourceRequirement,
    record_product,
    set_state_field,
)
from scopecat.compiler.typed.state import SetStateSpec
from scopecat.execution.effect_interpreter import RunEffectInterpreter
from scopecat.execution.events import TransitionRecorder
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
    StateTarget,
)
from scopecat.execution.points import RunPoint
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    ResourceClaim,
    logical_resource_port_id,
)
from scopecat.kernel.state import StateValue
from scopecat.kernel.value_types import Entity, Float, Scalar
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingEndpointBinding,
    RoutingGraph,
)
from scopecat.records.entity import EntityRef
from scopecat.sdk.instruments import (
    ApplyReceipt,
    CollectCommand,
    CollectReceipt,
    CommandChannelBinding,
    InstrumentDescription,
    InstrumentReadback,
    InstrumentStateCommand,
    InstrumentStateField,
    InstrumentStateSnapshot,
    apply_state_command_to_snapshot,
    capability,
    float_field,
)
from tests.testkit.authoring import load_config, parameters
from tests.testkit.local_materialization import (
    LocalEffectInspection,
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.relation_plans import scalar_value_expr
from tests.testkit.run_operations import complete_coverage_operations
from tests.testkit.runtime import FakeExecutionJournal
from tests.testkit.typed_program import (
    instrument_acquisition,
    link_program,
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
        point_domain=PointDomain(root=POINT_UNIT),
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
    return materialize_local_execution(link_program(program, environment))


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
                capabilities=("measure.left",),
            ),
            LogicalResourceRequirement(
                port_id=right,
                capabilities=("measure.right",),
            ),
            LogicalResourceRequirement(
                port_id=direct,
                capabilities=("measure.direct",),
            ),
        ),
        products=(left_product, right_product, direct_product),
        acquisitions=(
            instrument_acquisition(
                left_product,
                resource_port_id=left,
                capability="measure.left",
                provider_key="left",
            ),
            instrument_acquisition(
                right_product,
                resource_port_id=right,
                capability="measure.right",
                provider_key="right",
            ),
            instrument_acquisition(
                direct_product,
                resource_port_id=direct,
                capability="measure.direct",
                provider_key="direct",
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


def test_each_effect_uses_only_its_explicit_capability_endpoints() -> None:
    config = load_config()
    routing = RoutingGraph(
        bindings=[
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="A",
                entity_id="q0",
                channel_id="drive-q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="B",
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
        experiment_id="explicit-capability-endpoints",
        resource_requirements=(
            LogicalResourceRequirement(
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
                target_entities=(_entity("q0"),),
            ),
        ),
        products=(a_product, b_product),
        acquisitions=(
            instrument_acquisition(
                a_product,
                resource_port_id=port,
                capability="A",
                provider_key="A-result",
            ),
            instrument_acquisition(
                b_product,
                resource_port_id=port,
                capability="B",
                provider_key="B-result",
            ),
        ),
    )

    plan = _bind(program, config=config)

    [state] = operations_of_type(plan, ApplyStateOperation, point_index=0)
    assert state.instrument_id == "source-0"
    assert [
        (binding.capability, binding.channel_id)
        for binding in state.targets[0].channel_bindings
    ] == [("A", "drive-q0")]

    requests = {
        request.id: request
        for operation in operations_of_type(plan, CollectOperation, point_index=0)
        for request in operation.command.requests
    }
    assert {
        key: (
            request.capability_id,
            tuple(
                (binding.capability, binding.channel_id)
                for binding in request.channel_bindings
            ),
        )
        for key, request in requests.items()
    } == {
        "A-result": ("A", (("A", "drive-q0"),)),
        "B-result": ("B", (("B", "readout-q0"),)),
    }


def test_logical_state_bindings_reach_owning_instrument_claim() -> None:
    config = _shared_group_config()
    source = _port("source")
    first_state = set_state_field(
        resource_port_id=source,
        capability_id="set.level",
        field_path="level",
        value=_number(1.0),
        target_entities=(_entity("q0"),),
    )

    single_plan = _bind(
        _unit_program(
            experiment_id="logical-state-claims",
            resource_requirements=(
                LogicalResourceRequirement(
                    port_id=source,
                    capabilities=("set.level",),
                    entity_uses=(relation_use(_entity("q0")),),
                ),
            ),
            state=(first_state,),
        ),
        config=config,
    )
    field = operations_of_type(single_plan, ApplyStateOperation, point_index=0)[
        0
    ].targets[0]
    assert field.entity_ids == ("q0",)
    assert tuple(binding.channel_id for binding in field.channel_bindings) == (
        "drive-q0",
    )
    assert [(claim.kind, claim.id) for claim in single_plan.resource_claims] == [
        ("instrument", "source-0"),
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
                target_entities=(_entity("q0"),),
            ),
        ),
        products=(product,),
        acquisitions=(
            instrument_acquisition(
                product,
                resource_port_id=signal,
                capability="measure.signal",
                provider_key="signal",
            ),
        ),
    )

    plan = _bind(program, config=config)
    execution = plan

    state_field = operations_of_type(plan, ApplyStateOperation, point_index=0)[
        0
    ].targets[0]
    request = operations_of_type(plan, CollectOperation, point_index=0)[
        0
    ].command.requests[0]
    assert (state_field.entity_ids, state_field.channel_bindings) == (("q0",), ())
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
                capabilities=("set.level",),
                entity_uses=(relation_use(_entity("q0")),),
            ),
            LogicalResourceRequirement(
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
                target_entities=(_entity("q0"),),
            ),
            set_state_field(
                resource_port_id=right,
                capability_id="set.level",
                field_path="level",
                value=_number(1.0),
                target_entities=(_entity("q0"),),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as failure:
        _bind(program, config=config)

    assert "experiment_aliased_desired_state_target" in {
        problem.code for problem in failure.value.problems
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
    program = LocalEffectInspection.at_point(
        RunPoint(
            LogicalPointId(PointDomainId("scoped-same-field", "root"), 0),
            {},
        ),
        (
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
        resource_order=("source-0",),
        resource_claims=(ResourceClaim(id="source-0"),),
    )

    result = RunEffectInterpreter(
        run_id="scoped-same-field-run",
        coordinate_ids=tuple(program.points[0].coordinates),
        resource_order=program.resource_order,
        drivers={driver.instrument_id: driver},
        recorder=TransitionRecorder(FakeExecutionJournal()),
    ).run(complete_coverage_operations(program))

    assert not result.problems and not result.indeterminate
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
        bindings=[
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="measure.left",
                entity_id="q0",
                channel_id="drive-q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="measure.right",
                entity_id="q1",
                channel_id="readout-q0",
            ),
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability="measure.direct",
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
                capability="set.level",
                entity_id="q0",
                channel_id="drive-q0",
                group_ids=["shared.lo"],
            ),
            RoutingEndpointBinding(
                instrument_id="source-1",
                capability="set.level",
                entity_id="q1",
                channel_id="readout-q0",
                group_ids=["shared.lo"],
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
        bindings=[
            RoutingEndpointBinding(
                instrument_id="source-0",
                capability=capability,
                entity_id="q0",
            )
            for capability in ("set.level", "measure.signal")
        ],
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

    def collect(self, command: CollectCommand) -> CollectReceipt:
        del command
        return CollectReceipt(readback=InstrumentReadback())

    def cleanup(self) -> None:
        return None

    def abort(self) -> None:
        return None
