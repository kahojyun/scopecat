from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.authoring._identities import InvocationKey
from scopecat.authoring._value_refs import (
    internal_bind_value_ref_inputs,
    internal_input_value_ref,
    internal_literal_value_ref,
    internal_lower_scalar_value_ref,
    internal_lower_value_ref,
    internal_module_export_value_ref,
    internal_require_resolved_value_ref,
    internal_scope_value_ref,
    internal_transform_value_ref,
    internal_value_ref_module_export,
)
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.relations.context import EvalContext
from scopecat.kernel.value_types import Float, Scalar, String
from tests.testkit.relation_plans import evaluate_scalar


def _float_type() -> Scalar:
    return Scalar(Float())


def test_module_export_edge_remains_symbolic_until_elaboration() -> None:
    invocation_key = InvocationKey.fresh()
    value_type = _float_type()
    exported = internal_module_export_value_ref(
        invocation_key,
        "frequency",
        value_type,
    )

    assert exported.value_type == value_type
    assert internal_value_ref_module_export(exported) == (
        invocation_key,
        "frequency",
    )
    assert internal_bind_value_ref_inputs(exported, {}) is exported
    assert internal_scope_value_ref(exported, "outer") is exported

    with pytest.raises(ValueError, match="cannot lower unresolved module export"):
        internal_lower_value_ref(exported)
    with pytest.raises(ValueError, match="unresolved module export 'frequency'"):
        internal_require_resolved_value_ref(exported, context="compute input")


def test_transform_resolves_exports_nested_in_expression_binding_layers() -> None:
    value_type = _float_type()
    exported = internal_module_export_value_ref(
        InvocationKey.fresh(),
        "value",
        value_type,
    )
    inner_input = internal_input_value_ref("inner", value_type)
    inner = internal_bind_value_ref_inputs(inner_input + 1.0, {"inner": exported})
    outer_input = internal_input_value_ref("outer", value_type)
    nested = internal_bind_value_ref_inputs(outer_input * 2.0, {"outer": inner})

    literal = internal_literal_value_ref(
        3.0,
        value_type,
        path=("test", "value"),
    )
    resolved = internal_transform_value_ref(
        nested,
        lambda leaf: (
            literal if internal_value_ref_module_export(leaf) is not None else leaf
        ),
    )

    internal_require_resolved_value_ref(resolved)
    lowered = internal_lower_scalar_value_ref(resolved)
    assert evaluate_scalar(lowered, EvalContext()) == 8.0


def test_transform_requires_exact_value_type_preservation() -> None:
    exported = internal_module_export_value_ref(
        InvocationKey.fresh(),
        "value",
        _float_type(),
    )
    incompatible = internal_input_value_ref("text", Scalar(String()))

    with pytest.raises(TypeError, match="preserve the exact value type"):
        internal_transform_value_ref(exported, lambda _leaf: incompatible)


def test_flattened_ir_rejects_export_edges_hidden_in_root_inputs() -> None:
    value_type = sc.ScalarType(sc.FloatType())
    value = sc.input("value", value_type)
    producer = (
        sc.procedure(id="test.value-export.root-input-producer")
        .inputs(value)
        .export(value=value)
        .build()
        .instantiate("producer", value=1.0)
    )
    root = sc.procedure(id="test.value-export.root-input").build()

    with pytest.raises(ValueError, match="unresolved module export 'value'"):
        elaborate_module(root.ir, hidden=producer.outputs.value)
