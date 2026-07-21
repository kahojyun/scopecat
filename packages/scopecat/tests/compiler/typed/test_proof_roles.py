from __future__ import annotations

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.relations.model import (
    col,
    literal_rows,
    point_col,
)
from scopecat.compiler.relations.point_domain import POINT_UNIT, point_literal_rows
from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    LogicalResourceRequirement,
    bind_each,
    set_state_field,
)
from scopecat.compiler.typed.state import (
    ForEachStateSpec,
    SetStateSpec,
    StateSpec,
    StateSpecVariant,
)
from scopecat.compiler.typed.verification import verify_core_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_types import Float, Scalar, String, Table, TableColumn
from tests.testkit.authoring import load_config
from tests.testkit.relation_plans import (
    scalar_value_expr,
    table_value_expr,
)
from tests.testkit.typed_program import link_program

_FLOAT = Scalar(Float())
_STRING = Scalar(String())


def _empty_program(
    *,
    state: tuple[StateSpecVariant, ...] = (),
    resource_requirements: tuple[LogicalResourceRequirement, ...] = (),
) -> CoreProgram:
    return CoreProgram(
        id="proof-roles",
        kind="compiler_test",
        point_domain=PointDomain(root=POINT_UNIT),
        effects=state,
        resource_requirements=resource_requirements,
    )


def _fictional_current_row_state() -> CoreProgram:
    fictional_row = RowType((TableColumn("value", _FLOAT),))
    value = scalar_value_expr(
        col("value"),
        bindings=RelationTypeBindings(current_row=fictional_row),
        expected_type=_FLOAT,
    )
    state = set_state_field(
        resource_port_id=logical_resource_port_id("source"),
        capability_id="set_offset",
        field_path="offset",
        value=value,
    )
    return _empty_program(
        state=(state,),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                capabilities=("set_offset",),
            ),
        ),
    )


def test_program_verification_rejects_fictional_top_level_current_row() -> None:
    with pytest.raises(CheckFailed) as caught:
        verify_core_program(_fictional_current_row_state())

    problem = caught.value.problems[0]
    assert problem.code == "compiler_relation_proof_role_mismatch"
    assert problem.location == model_location("state", 0, "value")


def test_linking_cannot_bypass_program_proof_role_verification() -> None:
    environment = validate_config_environment(load_config())

    with pytest.raises(CheckFailed) as caught:
        link_program(_fictional_current_row_state(), environment)

    problem = caught.value.problems[0]
    assert problem.code == "compiler_relation_proof_role_mismatch"
    assert problem.phase.value == "planning"


def test_program_verification_rechecks_resource_requirement_point_proof() -> None:
    actual_points = Table(
        columns=(TableColumn("selector", _STRING),),
        min_rows=1,
        max_rows=1,
    )
    fictional_point = RowType((TableColumn("selector", _FLOAT),))
    requirement = LogicalResourceRequirement(
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
    program = CoreProgram(
        id="point-proof-role",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_literal_rows(
                actual_points.columns,
                (("q0",),),
            )
        ),
        resource_requirements=(requirement,),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_core_program(program)

    assert caught.value.problems[0].code == "compiler_relation_proof_role_mismatch"


def test_program_verification_rejects_assignable_but_stale_point_proof() -> None:
    actual_points = Table(
        columns=(TableColumn("selector", _FLOAT),),
        min_rows=1,
        max_rows=1,
    )
    fictional_point = RowType((TableColumn("selector", Scalar(Float(minimum=0.0))),))
    requirement = LogicalResourceRequirement(
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
    program = CoreProgram(
        id="stale-point-proof",
        kind="compiler_test",
        point_domain=PointDomain(
            root=point_literal_rows(
                actual_points.columns,
                ((1.5,),),
            )
        ),
        resource_requirements=(requirement,),
    )

    with pytest.raises(CheckFailed) as caught:
        verify_core_program(program)

    assert caught.value.problems[0].code == "compiler_relation_proof_role_mismatch"


def test_state_each_body_proof_accepts_its_real_current_row() -> None:
    rows_type = Table(
        columns=(TableColumn("value", _FLOAT),),
        min_rows=1,
        max_rows=1,
    )
    row = RowType.from_table(rows_type)
    child = set_state_field(
        resource_port_id=logical_resource_port_id("source"),
        capability_id="set_offset",
        field_path="offset",
        value=scalar_value_expr(
            col("value"),
            bindings=RelationTypeBindings(current_row=row),
            expected_type=_FLOAT,
        ),
    )
    state = bind_each(
        table_value_expr(
            literal_rows([{"value": 1.0}]),
            expected_type=rows_type,
        ),
        child,
    )
    assert isinstance(child, StateSpec)
    assert isinstance(child, SetStateSpec)
    assert isinstance(state, StateSpec)
    assert isinstance(state, ForEachStateSpec)
    program = _empty_program(
        state=(state,),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                capabilities=("set_offset",),
            ),
        ),
    )

    assert verify_core_program(program) is program
