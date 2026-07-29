from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from scopecat.compiler.environment import ConfigEnvironment
from scopecat.compiler.linking.linked import (
    link_program,
    materialize_linked_points,
)
from scopecat.compiler.relations.context import (
    ParameterRelationData,
)
from scopecat.compiler.relations.uses import RelationUse, relation_use
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.model import AcquireEffect
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    LogicalResourceRequirement,
    record_product,
    set_state_property,
)
from scopecat.compiler.typed.verification import (
    ProgramRelationConsumerKind,
    program_relation_consumers,
)
from scopecat.config.environment import build_config_environment
from scopecat.execution.local.program import CollectOperation
from scopecat.graph.relations.model import (
    CellValue,
    ParameterLookupUse,
    ScalarExpr,
    input_ref,
    param,
    parameter_lookup,
)
from scopecat.graph.relations.point_domain import (
    PointAxis,
    point_axis_linear,
    point_axis_values,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ProblemPhase,
    model_location,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_types import (
    Entity,
    Float,
    Scalar,
    String,
)
from scopecat.kernel.value_types import Quantity as QuantityType
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import (
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.relation_plans import (
    scalar_value_expr,
)
from tests.testkit.typed_program import instrument_acquisition, observable_product

_FLOAT = Scalar(Float())
_FREQUENCY = Scalar(QuantityType(unit="GHz"))
_DRIVE_FREQUENCY = Scalar(QuantityType(unit="GHz", minimum=4.0, maximum=6.0))
_SPAN = Quantity(value=2.0, unit="GHz")


def _lookup_use(table_id: str) -> ParameterLookupUse:
    return ParameterLookupUse(
        table_id=table_id,
        key_input_types=(("key", Scalar(String())),),
        literal_key_columns=frozenset({"key"}),
        column_id="value",
        result_type=_FREQUENCY,
    )


def _values_axis(
    axis_id: str,
    value_type: Scalar,
    values: tuple[CellValue, ...],
) -> PointAxis[RelationUse[ScalarValueExpr]]:
    return cast(
        "PointAxis[RelationUse[ScalarValueExpr]]",
        point_axis_values(axis_id, value_type, values),
    )


def _linear_axis(
    axis_id: str,
    expression: ScalarExpr,
    *,
    bindings: RelationTypeBindings | None = None,
    count: int = 2,
) -> PointAxis[RelationUse[ScalarValueExpr]]:
    return point_axis_linear(
        axis_id,
        _FREQUENCY,
        relation_use(
            scalar_value_expr(
                expression,
                bindings=bindings,
                expected_type=_FREQUENCY,
            )
        ),
        _SPAN,
        count,
    )


def _entity_rows(
    values: tuple[CellValue, ...],
) -> PointAxis[RelationUse[ScalarValueExpr]]:
    return _values_axis(
        "subject",
        Scalar(Entity()),
        values,
    )


def _symbolic_program() -> CoreProgram:
    axes = (
        _values_axis("a", _FLOAT, (1.0,)),
        _values_axis(
            "b",
            _FREQUENCY,
            (
                Quantity(value=5.0, unit="GHz"),
                Quantity(value=7.0, unit="GHz"),
            ),
        ),
        _linear_axis(
            "c",
            param("drive_frequency"),
            bindings=RelationTypeBindings(
                parameters={"drive_frequency": _DRIVE_FREQUENCY}
            ),
        ),
        _values_axis(
            "d",
            _FREQUENCY,
            (Quantity(value=8.0, unit="GHz"),),
        ),
    )
    selected_product = observable_product(
        "signal",
        metadata={"owner": "selected"},
    )
    available_product = observable_product(
        "available",
        metadata={"owner": "unselected"},
    )
    selected_use, selected_record = record_product(
        selected_product,
        metadata={"owner": "record"},
    )
    selected_acquisition = instrument_acquisition(
        selected_product,
        id="read-signal",
        interface="test.scalar_signal/v1",
        metadata={"owner": "selected-producer"},
    )
    return CoreProgram(
        id="symbolic-linked-plan",
        kind="compiler_test",
        point_domain=PointDomain(axes=axes),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                interfaces=("test.scalar_signal/v1",),
            ),
        ),
        effects=(selected_acquisition,),
        product_defs=(selected_product, available_product),
        product_uses=(selected_use,),
        record_uses=(selected_record,),
    )


def _environment() -> ConfigEnvironment:
    return build_config_environment(load_config())


def test_link_specializes_config_values_and_retains_backend_neutral_domain() -> None:
    program = _symbolic_program()

    linked = link_program(program, _environment())

    assert linked.program != program
    assert linked.point_domain is linked.verified_program.point_domain
    assert linked.point_domain.axes != program.point_domain.axes
    assert linked.point_domain.cardinality == 4
    assert tuple(column.id for column in linked.point_domain.coordinate_columns) == (
        "a",
        "b",
        "c",
        "d",
    )
    assert tuple(
        consumer.location.path
        for consumer in program_relation_consumers(linked.verified_program)
        if consumer.kind is ProgramRelationConsumerKind.POINT_AXIS_CENTER
    ) == (("axes", 2, "source", "center"),)


def test_link_retains_unit_domain() -> None:
    program = CoreProgram(
        id="unit-linked-plan",
        kind="compiler_test",
        point_domain=PointDomain(axes=()),
    )

    linked = link_program(program, _environment())

    assert linked.point_domain.axes == ()
    assert linked.point_domain.cardinality == 1
    assert all(
        consumer.kind is not ProgramRelationConsumerKind.POINT_AXIS_CENTER
        for consumer in program_relation_consumers(linked.verified_program)
    )
    assert linked.point_domain.coordinate_columns == ()


def test_raw_link_retains_product_metadata_and_accepted_environment() -> None:
    program = _symbolic_program()
    environment = _environment()
    linked = link_program(program, environment)
    acquisition = next(
        effect for effect in program.effects if isinstance(effect, AcquireEffect)
    )

    assert linked.environment is environment

    for metadata in (
        program.product_defs[0].metadata,
        acquisition.results[0].metadata,
        program.record_uses[0].metadata,
    ):
        with pytest.raises(TypeError, match="frozen mapping is immutable"):
            cast("dict[str, object]", metadata)["mutated-source"] = True

    assert linked.program.product_defs[0].metadata == {"owner": "selected"}
    assert acquisition.results[0].metadata == {"owner": "selected-producer"}
    assert linked.program.record_uses[0].metadata == {"owner": "record"}


def test_unselected_product_definition_survives_link_without_collection() -> None:
    program = _symbolic_program()

    linked = link_program(program, _environment())
    plan = materialize_local_execution(linked)

    selected_id, unselected_id = (product.id for product in linked.program.product_defs)
    assert linked.program.product_defs == program.product_defs
    assert tuple(use.product_id for use in linked.program.product_uses) == (
        selected_id,
    )
    assert tuple(record.product_use_id for record in linked.program.record_uses) == (
        linked.program.product_uses[0].id,
    )
    assert {
        product_use_id
        for operation in operations_of_type(plan, CollectOperation)
        for binding in operation.result_bindings
        for product_use_id in binding.product_use_ids
    } == {linked.program.product_uses[0].id}
    assert unselected_id != selected_id


def test_config_problems_do_not_produce_an_environment() -> None:
    config = load_config()
    invalid = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={"primary_entity_id": "missing-entity"},
            )
        }
    )

    with pytest.raises(CheckFailed) as caught:
        build_config_environment(invalid)

    assert tuple(problem.code for problem in caught.value.problems) == (
        "configuration.unknown_primary_entity",
    )


@pytest.mark.parametrize(
    ("expression", "bindings"),
    (
        (
            param("definitely_missing"),
            RelationTypeBindings(parameters={"definitely_missing": _FREQUENCY}),
        ),
        (
            parameter_lookup(
                _lookup_use("definitely_missing"),
                key={"key": "selected"},
            ),
            RelationTypeBindings(),
        ),
    ),
    ids=("scalar-center", "lookup-center"),
)
def test_link_closes_every_used_axis_center_parameter_import(
    expression: ScalarExpr,
    bindings: RelationTypeBindings,
) -> None:
    program = CoreProgram(
        id="missing-parameter-link",
        kind="compiler_test",
        point_domain=PointDomain(
            axes=(_linear_axis("value", expression, bindings=bindings),)
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, _environment())

    assert tuple(problem.code for problem in caught.value.problems) == (
        "linked_parameter_missing",
    )
    assert caught.value.problems[0].phase is ProblemPhase.PLANNING
    assert caught.value.problems[0].details["consumer_kind"] == "point_axis_center"
    assert caught.value.problems[0].details["parameter_id"] == "definitely_missing"


def test_link_classifies_a_lookup_bound_to_the_wrong_parameter_shape() -> None:
    parameter_id = "lookup-bound-as-scalar"
    program = CoreProgram(
        id="lookup-parameter-shape-link",
        kind="compiler_test",
        point_domain=PointDomain(
            axes=(
                _linear_axis(
                    "value",
                    parameter_lookup(
                        _lookup_use(parameter_id),
                        key={"key": "selected"},
                    ),
                    bindings=RelationTypeBindings(),
                ),
            ),
        ),
    )
    environment = replace(
        _environment(),
        parameters=ParameterRelationData(
            scalars={parameter_id: Quantity(value=1.0, unit="GHz")}
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, environment)

    assert tuple(problem.code for problem in caught.value.problems) == (
        "linked_parameter_contract_mismatch",
    )
    assert caught.value.problems[0].details["consumer_kind"] == "point_axis_center"
    assert "expected table parameter, got scalar" in caught.value.problems[0].message


def test_link_rejects_remaining_relation_input_imports() -> None:
    input_id = "unresolved"
    program = CoreProgram(
        id="unresolved-input-link",
        kind="compiler_test",
        point_domain=PointDomain(axes=()),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                interfaces=("test.set_frequency/v1",),
            ),
        ),
        effects=(
            set_state_property(
                resource_port_id=logical_resource_port_id("source"),
                interface_id="test.set_frequency/v1",
                property_id="value",
                value=scalar_value_expr(
                    input_ref(input_id),
                    bindings=RelationTypeBindings(inputs={input_id: _FLOAT}),
                    expected_type=_FLOAT,
                ),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, _environment())

    assert tuple(problem.code for problem in caught.value.problems) == (
        "linked_input_unresolved",
    )
    assert caught.value.problems[0].details == {
        "consumer_kind": "state_value",
        "input_id": input_id,
    }


def test_link_reports_every_missing_import_in_one_axis_center() -> None:
    missing_ids = ("missing-left", "missing-right")
    program = CoreProgram(
        id="multiple-missing-parameter-link",
        kind="compiler_test",
        point_domain=PointDomain(
            axes=(
                _linear_axis(
                    "value",
                    param(missing_ids[0]) + param(missing_ids[1]),
                    bindings=RelationTypeBindings(
                        parameters=dict.fromkeys(missing_ids, _FREQUENCY)
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        link_program(program, _environment())

    assert tuple(problem.code for problem in caught.value.problems) == (
        "linked_parameter_missing",
        "linked_parameter_missing",
    )
    assert {
        problem.details["parameter_id"] for problem in caught.value.problems
    } == set(missing_ids)
    assert {problem.details["consumer_kind"] for problem in caught.value.problems} == {
        "point_axis_center"
    }


def test_linked_points_retain_exact_proofs_when_materialized() -> None:
    linked = link_program(_symbolic_program(), _environment())
    materialized = materialize_linked_points(linked)

    assert materialized.linked_plan is linked
    assert materialized.point_domain.id == linked.point_domain.id
    assert [point.logical_ordinal for point in materialized.point_domain.points] == [
        0,
        1,
        2,
        3,
    ]


def test_linked_points_normalize_entities_before_point_identity_is_sealed() -> None:
    program = CoreProgram(
        id="linked-entity-points",
        kind="compiler_test",
        point_domain=PointDomain(axes=(_entity_rows(("q0",)),)),
    )

    linked = link_program(program, _environment())
    assert linked.point_domain.entity_columns == ("subject",)
    materialized = materialize_linked_points(linked)

    assert materialized.point_domain.points[0].row["subject"] == EntityRef(
        id="q0",
        kind="logical_device",
    )


def test_linked_points_reject_unknown_entities_at_the_planning_boundary() -> None:
    program = CoreProgram(
        id="unknown-linked-entity-point",
        kind="compiler_test",
        point_domain=PointDomain(axes=(_entity_rows(("missing",)),)),
    )

    with pytest.raises(CheckFailed) as caught:
        materialize_linked_points(link_program(program, _environment()))

    assert len(caught.value.problems) == 1
    problem = caught.value.problems[0]
    assert problem.code == "unknown_authoring_entity"
    assert problem.phase is ProblemPhase.PLANNING
    assert problem.location == model_location("entity", "missing")
    assert dict(problem.details) == {}


def test_linked_points_preserve_entity_kind_mismatch_problem() -> None:
    program = CoreProgram(
        id="wrong-kind-linked-entity-point",
        kind="compiler_test",
        point_domain=PointDomain(
            axes=(_entity_rows((EntityRef(id="q0", kind="logical_coupler"),)),),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        materialize_linked_points(link_program(program, _environment()))

    assert len(caught.value.problems) == 1
    problem = caught.value.problems[0]
    assert problem.code == "authoring_entity_kind_mismatch"
    assert problem.phase is ProblemPhase.PLANNING
    assert problem.location == model_location("entity", "q0")
    assert dict(problem.details) == {}
    assert problem.message == ("entity q0 has kind logical_device, not logical_coupler")


def test_linked_points_report_unknown_normalized_entities() -> None:
    program = CoreProgram(
        id="invalid-normalized-linked-entity-points",
        kind="compiler_test",
        point_domain=PointDomain(
            axes=(
                _entity_rows(
                    (
                        "q0",
                        EntityRef(id="q0", kind="logical_device"),
                        "missing",
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        materialize_linked_points(link_program(program, _environment()))

    assert [problem.code for problem in caught.value.problems] == [
        "unknown_authoring_entity"
    ]
