from __future__ import annotations

from dataclasses import replace

import pytest

from scopecat.compiler.relations.point_domain import POINT_UNIT
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
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    CoreProgram,
    LogicalResourceRequirement,
    TypedComputeNode,
    TypedComputeOutput,
    record_product,
    set_state_field,
)
from scopecat.compiler.typed.verification import verify_core_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_types import Float, Scalar
from tests.testkit.typed_program import observable_product


def _program(**updates: object) -> CoreProgram:
    program = CoreProgram(
        id="verification",
        kind="test",
        point_domain=PointDomain(root=POINT_UNIT),
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
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("drive"),
                capabilities=("set_gain",),
            ),
        ),
        effects=(
            set_state_field(
                resource_port_id=logical_resource_port_id("drive"),
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


def _empty_kernel(**_inputs: object) -> None:
    return None
