from __future__ import annotations

import pytest

from scopecat.compiler.relations.model import (
    RowScopeId,
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
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar, String, Table, TableColumn
from tests.testkit.relation_plans import (
    scalar_value_expr,
    table_value_expr,
)

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


def test_state_each_body_proof_accepts_its_lexical_row_scope() -> None:
    rows_type = Table(
        columns=(TableColumn("value", _FLOAT),),
        min_rows=1,
        max_rows=1,
    )
    row = RowType.from_table(rows_type)
    row_scope = RowScopeId(SymbolId(local_id="state-each-row"))
    child = set_state_field(
        resource_port_id=logical_resource_port_id("source"),
        capability_id="set_offset",
        field_path="offset",
        value=scalar_value_expr(
            col("value", row_scope_id=row_scope),
            bindings=RelationTypeBindings(row_arguments={row_scope: row}),
            expected_type=_FLOAT,
        ),
    )
    state = bind_each(
        table_value_expr(
            literal_rows([{"value": 1.0}]),
            expected_type=rows_type,
        ),
        child,
        row_scope_id=row_scope,
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
