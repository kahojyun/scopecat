from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._module_ir import (
    ModuleBodyIR,
    ModuleInterfaceIR,
    ModuleIR,
)
from scopecat.authoring._value_refs import internal_value_ref_operation_origin
from scopecat.authoring.values import ComputeDeclarationKey
from scopecat.compiler.frontend.elaboration import elaborate_module


def test_module_builder_splits_operation_from_python_implementation() -> None:
    def kernel() -> float:
        return 1.0

    definition = sc.compute(
        "produce",
        fn=kernel,
        output_type=sc.ScalarType(sc.FloatType()),
    )

    module = sc.module_body(id="test.operation-ir").computes(definition).build()

    assert len(module.ir.body.operations) == 1
    assert len(module.ir.python_implementations) == 1

    operation = module.ir.body.operations[0]
    implementation = module.ir.python_implementations[0]
    assert isinstance(operation.declaration_key, ComputeDeclarationKey)
    assert implementation.declaration_key == operation.declaration_key
    assert implementation.fn is kernel
    assert internal_value_ref_operation_origin(definition.output) == (
        operation.declaration_key,
    )


def test_module_ir_rejects_operation_without_python_implementation() -> None:
    definition = sc.compute(
        "produce",
        fn=lambda: 1.0,
        output_type=sc.ScalarType(sc.FloatType()),
    )
    complete = (
        sc.module_body(id="test.operation-ir.complete").computes(definition).build()
    )

    with pytest.raises(ValueError, match="missing Python implementations"):
        ModuleIR(
            id="test.operation-ir.incomplete",
            interface=ModuleInterfaceIR(),
            body=ModuleBodyIR(operations=complete.ir.body.operations),
        )


def test_python_implementation_identity_changes_with_its_declaration() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    first = sc.compute("produce", fn=lambda: 1.0, output_type=value_type)
    second = sc.compute("produce", fn=lambda: 2.0, output_type=value_type)

    first_ir = elaborate_module(
        sc.module_body(id="test.impl.first").computes(first).build().ir
    )
    second_ir = elaborate_module(
        sc.module_body(id="test.impl.second").computes(second).build().ir
    )

    first_id = next(iter(first_ir.implementations.values())).id
    second_id = next(iter(second_ir.implementations.values())).id
    assert first_id != second_id
    assert first_id.value.startswith("python:")
    assert first_id.value.endswith(":produce")
