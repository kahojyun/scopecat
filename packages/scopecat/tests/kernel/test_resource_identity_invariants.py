from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.linking.linked import link_verified_program
from scopecat.compiler.linking.materialization import materialize_local_semantics
from scopecat.compiler.relations.model import (
    lit,
    literal_rows,
    point_col,
)
from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import InstrumentProductProducer, ProductDef
from scopecat.compiler.typed.program import (
    CoreProgram,
    ResourceRouteIntent,
    product_output,
    record_product,
    set_state_field,
)
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ModelLocation, ProblemPhase, model_location
from scopecat.kernel.resource_identity import (
    LogicalResourcePortId,
    PhysicalResourceId,
    logical_resource_port_id,
)
from scopecat.kernel.value_types import Float, Scalar, String, Table, TableColumn
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.config import ConfigProfileSnapshot, RoutingGraph, RoutingResource
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import point_domain, scalar_value_expr
from tests.testkit.typed_program import instrument_product_producer, link_program


def _text(value: str) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(String()))


def _number(value: float) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(Float()))


def _unit_program(
    *,
    products: tuple[ProductDef, ...] = (),
    producers: tuple[InstrumentProductProducer, ...] | None = None,
    **updates: object,
) -> CoreProgram:
    uses_and_records = tuple(record_product(product) for product in products)
    selected_producers = (
        tuple(instrument_product_producer(product) for product in products)
        if producers is None
        else producers
    )
    return replace(
        CoreProgram(
            id="resource-identity-invariants",
            kind="compiler_test",
            point_domain=PointDomain(root=POINT_UNIT),
            product_defs=products,
            instrument_product_producers=selected_producers,
            product_uses=tuple(item[0] for item in uses_and_records),
            record_uses=tuple(item[1] for item in uses_and_records),
        ),
        **updates,
    )


def _config_with_resources(
    *resources: RoutingResource,
    instrument_ids: tuple[str, ...] = (),
) -> ConfigProfileSnapshot:
    config = load_config()
    seed = config.instrument_registry.instruments[0]
    instruments = list(config.instrument_registry.instruments)
    existing_instrument_ids = {instrument.id for instrument in instruments}
    instruments.extend(
        seed.model_copy(update={"id": instrument_id})
        for instrument_id in instrument_ids
        if instrument_id not in existing_instrument_ids
    )
    system = config.system.model_copy(
        update={
            "instrument_registry": config.instrument_registry.model_copy(
                update={"instruments": instruments}
            ),
            "routing": RoutingGraph(resources=list(resources)),
        }
    )
    return config.model_copy(update={"system": system})


def test_logical_and_physical_resource_ids_with_same_text_do_not_alias() -> None:
    logical = logical_resource_port_id("source-0")
    physical = PhysicalResourceId("source-0")

    assert logical.qualified_name == physical.value
    assert len({logical, physical}) == 2
    assert isinstance(logical, LogicalResourcePortId)
    assert isinstance(physical, PhysicalResourceId)


def test_seal_closes_logical_state_and_product_ports_and_capabilities() -> None:
    drive = logical_resource_port_id("drive")
    missing_record = product_output("missing-record")
    unsupported_record = product_output("unsupported-record")
    program = _unit_program(
        route_intents=(
            ResourceRouteIntent(
                port_id=drive,
                capabilities=("set.frequency",),
            ),
        ),
        effects=(
            set_state_field(
                resource_port_id=logical_resource_port_id("missing-state"),
                capability_id="set.frequency",
                field_path="value",
                value=_number(1.0),
            ),
            set_state_field(
                resource_port_id=drive,
                capability_id="set.power",
                field_path="value",
                value=_number(2.0),
            ),
        ),
        products=(missing_record, unsupported_record),
        producers=(
            instrument_product_producer(
                missing_record,
                resource_port_id="missing-record-port",
                capability="set.frequency",
            ),
            instrument_product_producer(
                unsupported_record,
                resource_port_id=drive,
                capability="measure.signal",
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        seal_typed_program(program)

    assert {problem.code for problem in caught.value.problems} == {
        "state_resource_port_missing",
        "state_resource_port_capability_missing",
        "product_resource_port_missing",
        "product_resource_port_capability_missing",
    }
    assert {problem.code: problem.location for problem in caught.value.problems} == {
        "state_resource_port_missing": model_location("state", 0, "resource_port_id"),
        "state_resource_port_capability_missing": model_location(
            "state", 1, "resource_port_id"
        ),
        "product_resource_port_missing": model_location(
            "instrument_product_producers", 0, "resource_port_id"
        ),
        "product_resource_port_capability_missing": model_location(
            "instrument_product_producers", 1, "resource_port_id"
        ),
    }
    assert all(
        problem.phase is ProblemPhase.AUTHORING for problem in caught.value.problems
    )


def test_public_dsl_direct_physical_state_is_not_captured_by_same_named_port(
    tmp_path: Path,
) -> None:
    rows = sc.input(
        "rows",
        sc.TableType(
            columns=(
                sc.TableColumn("resource", sc.ScalarType(sc.StringType())),
                sc.TableColumn("value", sc.ScalarType(sc.FloatType())),
            )
        ),
    )
    module = (
        sc.module("test.resource-identity.same-text")
        .inputs(rows)
        .resource("source-0", requires=("route.only",))
        .state_each(
            rows,
            resource=lambda row: row["resource"],
            capability="state.only",
            field="value",
            value=lambda row: row["value"],
        )
        .build()
    )
    invocation = (
        module.template(
            "test.resource-identity.same-text",
            kind="resource_identity",
        )
        .build()
        .bind(rows=({"resource": "source-0", "value": 1.0},))
    )
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
                        capabilities=["state.only"],
                    ),
                    RoutingResource(
                        id="source-1",
                        capabilities=["route.only"],
                    ),
                ]
            ),
        }
    )
    config = config.model_copy(update={"system": system})

    resolved = resolve_experiment(
        invocation,
        config_profile=config,
    )
    plan = materialize_local_semantics(
        link_verified_program(resolved.verified_program, resolved.environment)
    )

    assert plan.valid, plan.problems
    assert plan.points[0].routes[0].port_id == logical_resource_port_id("source-0")
    assert plan.points[0].routes[0].resource_id == PhysicalResourceId("source-1")
    assert plan.points[0].desired_state[0].resource_id == PhysicalResourceId("source-0")


def test_direct_physical_record_is_not_captured_by_same_named_logical_port() -> None:
    product = product_output("direct")
    producer = instrument_product_producer(
        product,
        physical_resource_id="source-0",
        capability="record.only",
    )
    program = _unit_program(
        route_intents=(
            ResourceRouteIntent(
                port_id=logical_resource_port_id("source-0"),
                capabilities=("route.only",),
            ),
        ),
        products=(product,),
        producers=(producer,),
    )
    config = _config_with_resources(
        RoutingResource(id="source-0", capabilities=["record.only"]),
        RoutingResource(id="source-1", capabilities=["route.only"]),
        instrument_ids=("source-0", "source-1"),
    )

    plan = materialize_local_semantics(
        link_program(program, validate_config_environment(config))
    )

    assert plan.valid, plan.problems
    assert plan.points[0].routes[0].resource_id == PhysicalResourceId("source-1")
    producer_target = program.instrument_product_producers[0].resource_target
    assert producer_target == PhysicalResourceId("source-0")
    assert plan.points[0].collect[0].resource_id == PhysicalResourceId("source-0")


@pytest.mark.parametrize(
    ("program", "expected_code", "expected_location"),
    [
        pytest.param(
            _unit_program(
                route_intents=(
                    ResourceRouteIntent(
                        port_id=logical_resource_port_id("drive"),
                        fixed_resource_id=PhysicalResourceId("definitely-missing"),
                    ),
                )
            ),
            "physical_resource_not_found",
            model_location("route_intents", 0, "fixed_resource_id"),
            id="missing-fixed-route",
        ),
        pytest.param(
            _unit_program(
                route_intents=(
                    ResourceRouteIntent(
                        port_id=logical_resource_port_id("drive"),
                        capabilities=("definitely.unsupported",),
                        fixed_resource_id=PhysicalResourceId("source-0"),
                    ),
                )
            ),
            "physical_resource_contract_mismatch",
            model_location("route_intents", 0, "fixed_resource_id"),
            id="fixed-route-capability-mismatch",
        ),
    ],
)
def test_link_rejects_invalid_static_physical_resource_contracts(
    program: CoreProgram,
    expected_code: str,
    expected_location: ModelLocation,
) -> None:
    with pytest.raises(CheckFailed) as caught:
        link_program(program, validate_config_environment(load_config()))

    assert [problem.code for problem in caught.value.problems] == [expected_code]
    problem = caught.value.problems[0]
    assert problem.phase is ProblemPhase.PLANNING
    assert problem.location == expected_location


@pytest.mark.parametrize(
    ("resource_id", "capability", "expected_code"),
    (
        (
            "definitely-missing",
            None,
            "physical_resource_not_found",
        ),
        (
            "source-0",
            "definitely.unsupported",
            "physical_resource_contract_mismatch",
        ),
    ),
)
def test_binding_rejects_invalid_selected_physical_product_producer(
    resource_id: str,
    capability: str | None,
    expected_code: str,
) -> None:
    product = product_output("signal")
    producer = instrument_product_producer(
        product,
        physical_resource_id=resource_id,
        capability=capability,
    )
    program = _unit_program(
        products=(product,),
        producers=(producer,),
    )

    plan = materialize_local_semantics(
        link_program(program, validate_config_environment(load_config()))
    )

    assert not plan.valid
    assert [problem.code for problem in plan.problems] == [expected_code]
    assert plan.problems[0].phase is ProblemPhase.PLANNING
    assert plan.problems[0].location == model_location(
        "instrument_product_producers",
        producer.id.qualified_name,
        "physical_resource_id",
    )


def test_unused_logical_product_producer_does_not_constrain_route_placement() -> None:
    port = logical_resource_port_id("scheduler")
    product = product_output("unused")
    producer = instrument_product_producer(
        product,
        resource_port_id=port,
        capability="schedule",
    )
    program = _unit_program(
        products=(product,),
        producers=(producer,),
        product_uses=(),
        record_uses=(),
        route_intents=(
            ResourceRouteIntent(
                port_id=port,
                capabilities=("schedule",),
                fixed_resource_id=PhysicalResourceId("scheduler-0"),
            ),
        ),
    )
    environment = validate_config_environment(
        _config_with_resources(
            RoutingResource(
                id="scheduler-0",
                kind="scheduler",
                capabilities=["schedule"],
            )
        )
    )

    linked = link_program(program, environment)
    plan = materialize_local_semantics(
        link_verified_program(linked.verified_program, linked.environment)
    )

    assert plan.valid, plan.problems
    assert plan.points[0].routes[0].resource_kind == "scheduler"
    assert plan.points[0].collect == ()


def test_demanded_logical_product_producer_requires_instrument_during_binding() -> None:
    port = logical_resource_port_id("scheduler")
    product = product_output("selected")
    producer = instrument_product_producer(
        product,
        resource_port_id=port,
        capability="schedule",
    )
    program = _unit_program(
        products=(product,),
        producers=(producer,),
        route_intents=(
            ResourceRouteIntent(
                port_id=port,
                capabilities=("schedule",),
                fixed_resource_id=PhysicalResourceId("scheduler-0"),
            ),
        ),
    )
    environment = validate_config_environment(
        _config_with_resources(
            RoutingResource(
                id="scheduler-0",
                kind="scheduler",
                capabilities=["schedule"],
            )
        )
    )

    linked = link_program(program, environment)
    plan = materialize_local_semantics(
        link_verified_program(linked.verified_program, linked.environment)
    )

    assert not plan.valid
    assert [problem.code for problem in plan.problems] == [
        "physical_resource_kind_unsupported"
    ]


def test_link_rejects_non_instrument_physical_effect_resource() -> None:
    program = _unit_program(
        effects=(
            set_state_field(
                _text("scheduler-0"),
                capability_id="schedule",
                field_path="value",
                value=_number(1.0),
            ),
        )
    )
    config = _config_with_resources(
        RoutingResource(
            id="scheduler-0",
            kind="scheduler",
            capabilities=["schedule"],
        )
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, validate_config_environment(config))

    assert [problem.code for problem in caught.value.problems] == [
        "physical_resource_kind_unsupported"
    ]
    problem = caught.value.problems[0]
    assert problem.phase is ProblemPhase.PLANNING
    assert problem.location == model_location("state", 0, "physical_resource_id")


def test_capability_less_authored_port_rejects_state_and_record_at_assembly() -> None:
    module = (
        sc.module("test.resource-identity.capability-less")
        .resource("drive")
        .bind_field(
            "drive",
            capability="set.frequency",
            field="value",
            value=1.0,
        )
        .record(
            "signal",
            resource="drive",
            capability="measure.signal",
        )
        .build()
    )

    with pytest.raises(CheckFailed) as caught:
        verify_assembly_graph(elaborate_module(module))

    assert [problem.code for problem in caught.value.problems] == [
        "module_resource_port_capability_missing",
        "module_resource_port_capability_missing",
    ]
    assert all(
        problem.phase is ProblemPhase.AUTHORING for problem in caught.value.problems
    )


def test_link_rejects_missing_literal_physical_state_resource() -> None:
    program = _unit_program(
        effects=(
            set_state_field(
                _text("definitely-missing"),
                capability_id="set_frequency",
                field_path="frequency",
                value=_number(1.0),
            ),
        )
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, validate_config_environment(load_config()))

    assert [problem.code for problem in caught.value.problems] == [
        "physical_resource_not_found"
    ]
    problem = caught.value.problems[0]
    assert problem.phase is ProblemPhase.PLANNING
    assert problem.location == model_location("state", 0, "physical_resource_id")


def test_binding_rejects_missing_dynamic_physical_resource() -> None:
    point_type = Table(
        columns=(TableColumn("resource", Scalar(String())),),
        min_rows=1,
        max_rows=1,
    )
    bindings = RelationTypeBindings(point_row=RowType.from_table(point_type))
    program = CoreProgram(
        id="dynamic-physical-resource",
        kind="compiler_test",
        point_domain=point_domain(
            literal_rows([{"resource": "definitely-missing"}]),
            expected_type=point_type,
        ),
        effects=(
            set_state_field(
                scalar_value_expr(
                    point_col("resource"),
                    bindings=bindings,
                    expected_type=Scalar(String()),
                ),
                capability_id="set_frequency",
                field_path="frequency",
                value=_number(1.0),
            ),
        ),
    )

    plan = materialize_local_semantics(
        link_program(program, validate_config_environment(load_config()))
    )

    assert not plan.valid
    assert [problem.code for problem in plan.problems] == [
        "physical_resource_not_found"
    ]
    assert plan.problems[0].location == model_location(
        "desired_state", "physical_resource_id"
    )
