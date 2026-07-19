from __future__ import annotations

from dataclasses import replace

import pytest

from scopecat.compiler.relations.model import (
    ScalarExpr,
    col,
    grid,
    literal_rows,
    outer,
    point_col,
)
from scopecat.compiler.relations.verification import RelationPlanVerificationError
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    ImplementationCatalog,
    ImplementationId,
    LocalPythonImplementation,
    OperationId,
    operation_result_id,
)
from scopecat.compiler.semantic.operation_contract import (
    LOCAL_OPAQUE_OPERATION_CONTRACT,
)
from scopecat.compiler.typed.program import (
    CoreProgram,
    ResourceRouteIntent,
    RouteInput,
    TypedComputeNode,
    TypedComputeOutput,
    record_product,
    set_state_field,
)
from scopecat.compiler.typed.verification import verify_core_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Route, Scalar, Table, TableColumn
from tests.testkit.relation_plans import (
    point_domain,
    scalar_value_expr,
    table_value_expr,
)
from tests.testkit.typed_program import observable_product


def _program(**updates: object) -> CoreProgram:
    program = CoreProgram(
        id="verification",
        kind="test",
        point_domain=point_domain(
            literal_rows([{}]),
            expected_type=Table(columns=(), min_rows=1, max_rows=1),
        ),
    )
    return replace(program, **updates)


def _catalog(operation_id: OperationId) -> ImplementationCatalog:
    return ImplementationCatalog(
        local_python=(
            LocalPythonImplementation(
                id=ImplementationId(f"python.{operation_id.qualified_name}.v1"),
                operation_id=operation_id,
                operation_contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                kernel=_empty_kernel,
            ),
        )
    )


def _output(operation_id: OperationId, value_type: Scalar) -> TypedComputeOutput:
    return TypedComputeOutput(
        id=operation_result_id(operation_id),
        value_type=value_type,
    )


def test_typed_program_verifier_rejects_incomplete_compute_route() -> None:
    operation_id = OperationId(SymbolId(local_id="consume-route"))
    node = TypedComputeNode(
        id=operation_id,
        contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
        inputs={
            "route": RouteInput(
                port_id=logical_resource_port_id("drive"),
                value_type=Route(capabilities=("set_gain",)),
            )
        },
        result=_output(operation_id, Scalar(Float())),
    )
    program = _program(
        compute_nodes=(node,),
        implementation_catalog=_catalog(operation_id),
        route_intents=(
            ResourceRouteIntent(
                port_id=logical_resource_port_id("drive"),
                capabilities=("set_frequency",),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as error:
        verify_core_program(program)

    assert error.value.problems[0].code == ("compute_route_capability_missing")


def test_typed_program_verifier_rejects_non_payload_state_compute() -> None:
    operation_id = OperationId(SymbolId(local_id="numeric"))
    program = _program(
        compute_nodes=(
            TypedComputeNode(
                id=operation_id,
                contract=LOCAL_OPAQUE_OPERATION_CONTRACT,
                result=_output(operation_id, Scalar(Float())),
            ),
        ),
        implementation_catalog=_catalog(operation_id),
        effects=(
            set_state_field(
                scalar_value_expr("drive"),
                capability_id="set_gain",
                field_path="value",
                value=ComputeResultRef(value_id=operation_result_id(operation_id)),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as error:
        verify_core_program(program)

    assert error.value.problems[0].code == "compute_payload_unavailable"


def test_typed_program_verifier_checks_static_record_schema() -> None:
    product = observable_product("signal", unit="not-a-unit")
    product_use, record_use = record_product(product)
    program = _program(
        product_defs=(product,),
        product_uses=(product_use,),
        record_uses=(record_use,),
    )

    with pytest.raises(CheckFailed) as error:
        verify_core_program(program)

    assert error.value.problems[0].code == "product_unit_unsupported"


@pytest.mark.parametrize("reference", [col("x"), outer("x")])
def test_typed_program_verifier_rejects_unbound_point_domain_rows(
    reference: ScalarExpr,
) -> None:
    with pytest.raises(RelationPlanVerificationError) as error:
        table_value_expr(
            grid(x=reference),
            expected_type=Table(
                columns=(TableColumn("x", Scalar(Float())),),
                min_rows=1,
                max_rows=1,
            ),
        )

    assert error.value.code == "unbound_row_reference"


def test_typed_program_verifier_accepts_explicit_point_scope() -> None:
    program = _program(
        point_domain=point_domain(
            literal_rows([{"x": 1.0}]).point_cross(grid(copy=point_col("x"))),
            expected_type=Table(
                columns=(
                    TableColumn("x", Scalar(Float())),
                    TableColumn("copy", Scalar(Float())),
                ),
                min_rows=1,
                max_rows=1,
            ),
        )
    )

    assert verify_core_program(program) is program


def _empty_kernel(**_inputs: object) -> None:
    return None
