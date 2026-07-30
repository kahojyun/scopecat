from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._identities import ComputeDeclarationKey
from scopecat.authoring._module_ir import (
    ModuleBodyIR,
    ModuleInterfaceIR,
    ModuleIR,
)
from scopecat.authoring._value_refs import internal_value_ref_operation_origin
from scopecat.compiler.frontend.elaboration import elaborate_module


def test_module_definition_splits_operation_from_python_implementation() -> None:
    def kernel() -> float:
        return 1.0

    @sc.module(id="test.operation-ir")
    def module(context: sc.ModuleContext) -> None:
        context.compute(
            "produce",
            fn=kernel,
            output_type=sc.ScalarType(sc.FloatType()),
        )

    assert len(module.ir.body.operations) == 1
    assert len(module.ir.python_implementations) == 1

    operation = module.ir.body.operations[0]
    implementation = module.ir.python_implementations[0]
    assert isinstance(operation.declaration_key, ComputeDeclarationKey)
    assert implementation.declaration_key == operation.declaration_key
    assert implementation.fn is kernel
    assert internal_value_ref_operation_origin(operation.result) == (
        operation.declaration_key,
    )


def test_module_ir_rejects_operation_without_python_implementation() -> None:
    @sc.module(id="test.operation-ir.complete")
    def complete(context: sc.ModuleContext) -> None:
        context.compute(
            "produce",
            fn=lambda: 1.0,
            output_type=sc.ScalarType(sc.FloatType()),
        )

    with pytest.raises(ValueError, match="missing Python implementations"):
        ModuleIR(
            id="test.operation-ir.incomplete",
            interface=ModuleInterfaceIR(),
            body=ModuleBodyIR(operations=complete.ir.body.operations),
        )


def test_python_implementation_identity_changes_with_its_declaration() -> None:
    @sc.module(id="test.impl.first")
    def first(context: sc.ModuleContext) -> None:
        context.compute(
            "produce",
            fn=lambda: 1.0,
            output_type=sc.ScalarType(sc.FloatType()),
        )

    @sc.module(id="test.impl.second")
    def second(context: sc.ModuleContext) -> None:
        context.compute(
            "produce",
            fn=lambda: 2.0,
            output_type=sc.ScalarType(sc.FloatType()),
        )

    first_ir = elaborate_module(first.ir)
    second_ir = elaborate_module(second.ir)

    first_id = next(iter(first_ir.implementations.values())).id
    second_id = next(iter(second_ir.implementations.values())).id
    assert first_id != second_id
    assert first_id.value.startswith("python:")
    assert first_id.value.endswith(":produce")
