from __future__ import annotations

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.relations.model import (
    col,
    grid,
    literal_rows,
    outer,
    point_col,
)
from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.program import (
    ResourceRouteIntent,
    TypedProgram,
    bind_each,
    set_state_field,
)
from scopecat.compiler.typed.state import (
    ForEachStateSpec,
    SetStateSpec,
    StateSpec,
    StateSpecVariant,
)
from scopecat.compiler.typed.verification import verify_typed_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_types import Float, Scalar, String, Table, TableColumn
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import (
    point_domain,
    scalar_value_expr,
    table_value_expr,
)
from tests.testkit.typed_program import link_program

_EMPTY_POINTS = Table(columns=(), min_rows=1, max_rows=1)
_FLOAT = Scalar(Float())
_STRING = Scalar(String())


def _empty_program(
    *,
    state: tuple[StateSpecVariant, ...] = (),
    route_intents: tuple[ResourceRouteIntent, ...] = (),
) -> TypedProgram:
    return TypedProgram(
        id="proof-roles",
        kind="compiler_test",
        point_domain=point_domain(
            literal_rows([{}]),
            expected_type=_EMPTY_POINTS,
        ),
        state=state,
        route_intents=route_intents,
    )


def _fictional_current_row_state() -> TypedProgram:
    fictional_row = RowType((TableColumn("resource", _STRING),))
    resource = scalar_value_expr(
        col("resource"),
        bindings=RelationTypeBindings(current_row=fictional_row),
        expected_type=_STRING,
    )
    state = set_state_field(
        resource,
        capability_id="set_offset",
        field_path="offset",
        value=scalar_value_expr(1.0, expected_type=_FLOAT),
    )
    return _empty_program(state=(state,))


def test_program_verification_rejects_fictional_top_level_current_row() -> None:
    with pytest.raises(CheckFailed) as caught:
        verify_typed_program(_fictional_current_row_state())

    problem = caught.value.problems[0]
    assert problem.code == "compiler_relation_proof_role_mismatch"
    assert problem.location == model_location("state", 0, "physical_resource_id")


def test_linking_cannot_bypass_program_proof_role_verification() -> None:
    environment = validate_config_environment(load_config())

    with pytest.raises(CheckFailed) as caught:
        link_program(_fictional_current_row_state(), environment)

    problem = caught.value.problems[0]
    assert problem.code == "compiler_relation_proof_role_mismatch"
    assert problem.phase.value == "planning"


def test_program_verification_rechecks_point_schema_used_by_route_proof() -> None:
    actual_points = Table(
        columns=(TableColumn("selector", _STRING),),
        min_rows=1,
        max_rows=1,
    )
    fictional_point = RowType((TableColumn("selector", _FLOAT),))
    route = ResourceRouteIntent(
        port_id=logical_resource_port_id("drive"),
        entity_uses=(
            relation_use(
                scalar_value_expr(
                    point_col("selector"),
                    bindings=RelationTypeBindings(point_row=fictional_point),
                    expected_type=_FLOAT,
                )
            ),
        ),
    )
    program = TypedProgram(
        id="point-proof-role",
        kind="compiler_test",
        point_domain=point_domain(
            literal_rows([{"selector": "q0"}]),
            expected_type=actual_points,
        ),
        route_intents=(route,),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_typed_program(program)

    assert caught.value.problems[0].code == "compiler_relation_proof_role_mismatch"


def test_program_verification_rejects_assignable_but_stale_point_proof() -> None:
    actual_points = Table(
        columns=(TableColumn("selector", _FLOAT),),
        min_rows=1,
        max_rows=1,
    )
    fictional_point = RowType((TableColumn("selector", Scalar(Float(minimum=0.0))),))
    route = ResourceRouteIntent(
        port_id=logical_resource_port_id("drive"),
        entity_uses=(
            relation_use(
                scalar_value_expr(
                    point_col("selector"),
                    bindings=RelationTypeBindings(point_row=fictional_point),
                    expected_type=_FLOAT,
                )
            ),
        ),
    )
    program = TypedProgram(
        id="stale-point-proof",
        kind="compiler_test",
        point_domain=point_domain(
            literal_rows([{"selector": 1.5}]),
            expected_type=actual_points,
        ),
        route_intents=(route,),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_typed_program(program)

    assert caught.value.problems[0].code == "compiler_relation_proof_role_mismatch"


def test_state_each_body_proof_accepts_its_real_current_row() -> None:
    rows_type = Table(
        columns=(TableColumn("resource", _STRING),),
        min_rows=1,
        max_rows=1,
    )
    row = RowType.from_table(rows_type)
    child = set_state_field(
        scalar_value_expr(
            col("resource"),
            bindings=RelationTypeBindings(current_row=row),
            expected_type=_STRING,
        ),
        capability_id="set_offset",
        field_path="offset",
        value=scalar_value_expr(1.0, expected_type=_FLOAT),
    )
    state = bind_each(
        table_value_expr(
            literal_rows([{"resource": "source-0"}]),
            expected_type=rows_type,
        ),
        child,
    )
    assert isinstance(child, StateSpec)
    assert isinstance(child, SetStateSpec)
    assert isinstance(state, StateSpec)
    assert isinstance(state, ForEachStateSpec)
    program = _empty_program(state=(state,))

    assert verify_typed_program(program) is program


def test_nested_state_relation_uses_parent_current_row_as_outer() -> None:
    parent_type = Table(
        columns=(TableColumn("ambient", _FLOAT),),
        min_rows=1,
        max_rows=1,
    )
    nested_type = Table(
        columns=(TableColumn("observed", _FLOAT),),
        min_rows=1,
        max_rows=1,
    )
    nested = bind_each(
        table_value_expr(
            grid(observed=outer("ambient")),
            bindings=RelationTypeBindings(outer_row=RowType.from_table(parent_type)),
            expected_type=nested_type,
        ),
        set_state_field(
            scalar_value_expr("source-0", expected_type=_STRING),
            capability_id="set_offset",
            field_path="offset",
            value=scalar_value_expr(1.0, expected_type=_FLOAT),
        ),
    )
    state = bind_each(
        table_value_expr(
            literal_rows([{"ambient": 1.0}]),
            expected_type=parent_type,
        ),
        nested,
    )

    assert verify_typed_program(_empty_program(state=(state,)))
