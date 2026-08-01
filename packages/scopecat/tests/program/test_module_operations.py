from __future__ import annotations

import scopecat as sc
from scopecat.program.identities import ComputeDeclarationKey
from scopecat.program.value_refs import internal_value_ref_operation_origin


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

    assert len(module.definition.body.operations) == 1
    assert len(module.definition.python_implementations) == 1

    operation = module.definition.body.operations[0]
    implementation = module.definition.python_implementations[0]
    assert isinstance(operation.declaration_key, ComputeDeclarationKey)
    assert implementation.declaration_key == operation.declaration_key
    assert implementation.fn is kernel
    assert internal_value_ref_operation_origin(operation.result) == (
        operation.declaration_key,
    )
