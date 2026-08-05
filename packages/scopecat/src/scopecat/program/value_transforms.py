"""Scope, substitute, and transform canonical typed value edges."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace

from scopecat.kernel.product_identity import parse_product_id
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.program.expression_analysis import expression_input_refs
from scopecat.program.expression_binding import substitute_scalar_input_refs
from scopecat.program.expressions import (
    BinaryScalarExpr,
    ComputeResultScalarExpr,
    InputScalarExpr,
    ModuleExportScalarExpr,
    ParameterLookupScalarExpr,
    ScalarExpr,
)
from scopecat.program.table_values import InputTableSource
from scopecat.program.value_refs import (
    ValueRef,
    internal_value_ref_first_module_export,
    internal_value_ref_module_export,
    internal_value_ref_requires_execution,
    internal_value_ref_source_id,
)


def internal_transform_value_ref(
    value: ValueRef,
    transform_leaf: Callable[[ValueRef], ValueRef],
) -> ValueRef:
    """Transform source leaves throughout one typed canonical value."""

    source = value.source
    if not isinstance(source, ParameterLookupScalarExpr | BinaryScalarExpr):
        return _transform_value_leaf(value, transform_leaf)
    transformed_source = _transform_scalar_leaves(source, transform_leaf)
    if transformed_source is source:
        return value
    return ValueRef(
        source=transformed_source,
        value_type=value.value_type,
        id=value.id,
    )


def internal_scope_value_ref(
    value: ValueRef,
    *scope: str,
    origin: tuple[object, ...] = (),
) -> ValueRef:
    """Scope declarations and compute symbols owned by one module instance."""

    if not scope and not origin:
        return value
    source = value.source
    if isinstance(source, ModuleExportScalarExpr):
        source_value_id = source.source_value_id
        if source_value_id is None:
            return value
        return ValueRef(
            source=replace(
                source,
                source_value_id=(
                    parse_product_id(source_value_id).prefixed(*scope).qualified_name
                ),
            ),
            value_type=value.value_type,
            id=value.id,
        )
    if internal_value_ref_module_export(value) is not None:
        return value
    selected_source = (
        _scope_scalar_expression(source, scope=scope, origin=origin)
        if isinstance(source, ScalarExpr)
        else source
    )
    return ValueRef(
        source=selected_source,
        value_type=value.value_type,
        id=value.id.prefixed(*scope),
    )


def internal_project_value_ref_source_id(
    value: ValueRef,
    inputs: Mapping[str, ValueRef],
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
) -> str | None:
    """Derive the stable identity produced by one module-boundary projection."""

    projected = internal_bind_value_ref_inputs(
        internal_scope_value_ref(value, *scope, origin=origin),
        inputs,
    )
    return internal_value_ref_source_id(projected)


def internal_bind_value_ref_inputs(
    value: ValueRef,
    inputs: Mapping[str, ValueRef],
) -> ValueRef:
    """Attach one typed module-input environment without lowering the edge."""

    source = value.source
    if isinstance(source, InputScalarExpr):
        selected = inputs.get(source.name)
        return value if selected is None else _preserve_bound_value_use(value, selected)
    if isinstance(source, InputTableSource):
        selected = inputs.get(source.input_id)
        return value if selected is None else _preserve_bound_value_use(value, selected)
    if not isinstance(source, ScalarExpr) or not inputs:
        return value
    reachable = frozenset(expression_input_refs(source)) & inputs.keys()
    if not reachable:
        return value
    selected = {
        input_id: inputs[input_id] for input_id in inputs if input_id in reachable
    }
    _require_relation_bindings(tuple(selected.values()))
    replacements = {
        input_id: _scalar_expression(bound) for input_id, bound in selected.items()
    }
    bound_source = substitute_scalar_input_refs(source, replacements)
    return ValueRef(
        source=bound_source,
        value_type=value.value_type,
        id=value.id,
    )


def internal_value_ref_unbound_input_ids(value: ValueRef) -> frozenset[str]:
    """Return lexical input ids that remain free in one typed value edge."""

    source = value.source
    if not isinstance(source, ScalarExpr):
        return frozenset()
    return frozenset(expression_input_refs(source))


def _require_relation_bindings(values: tuple[ValueRef, ...]) -> None:
    if any(
        internal_value_ref_first_module_export(value) is None
        and internal_value_ref_requires_execution(value)
        for value in values
    ):
        msg = (
            "compute outputs cannot be bound inside scalar expressions; "
            "express this calculation with ModuleContext.compute"
        )
        raise TypeError(msg)


def _scalar_expression(value: ValueRef) -> ScalarExpr:
    source = value.source
    if not isinstance(source, ScalarExpr):
        msg = "scalar expression requires a scalar value"
        raise TypeError(msg)
    if isinstance(source, ComputeResultScalarExpr):
        msg = (
            "compute outputs cannot be bound inside scalar expressions; "
            "express this calculation with ModuleContext.compute"
        )
        raise TypeError(msg)
    return source


def _transform_scalar_leaves(
    expression: ScalarExpr,
    transform_leaf: Callable[[ValueRef], ValueRef],
) -> ScalarExpr:
    if isinstance(expression, ParameterLookupScalarExpr):
        transformed_key = {
            name: _transform_scalar_leaves(value, transform_leaf)
            for name, value in expression.key.items()
        }
        if all(
            transformed_key[name] is value for name, value in expression.key.items()
        ):
            return expression
        return replace(expression, key=transformed_key)
    if isinstance(expression, BinaryScalarExpr):
        left = _transform_scalar_leaves(expression.left, transform_leaf)
        right = _transform_scalar_leaves(expression.right, transform_leaf)
        if left is expression.left and right is expression.right:
            return expression
        return replace(expression, left=left, right=right)
    transformed = _transform_value_leaf(
        ValueRef(source=expression, value_type=expression.value_type),
        transform_leaf,
    )
    source = transformed.source
    if not isinstance(source, ScalarExpr):
        msg = "scalar expression leaf must transform to a scalar value"
        raise TypeError(msg)
    return source


def _transform_value_leaf(
    value: ValueRef,
    transform_leaf: Callable[[ValueRef], ValueRef],
) -> ValueRef:
    transformed = transform_leaf(value)
    if transformed.value_type == value.value_type:
        return transformed
    if not is_assignable(transformed.value_type, value.value_type):
        msg = "value reference transform must preserve an assignable value type"
        raise TypeError(msg)
    return ValueRef(
        source=transformed.source,
        value_type=value.value_type,
        id=value.id,
    )


def _preserve_bound_value_use(value: ValueRef, selected: ValueRef) -> ValueRef:
    """Retain a narrowed module-input contract around its assigned producer."""

    if selected.value_type == value.value_type:
        return selected
    return ValueRef(
        source=selected.source,
        value_type=value.value_type,
        id=value.id,
    )


def _scope_scalar_expression(
    expression: ScalarExpr,
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
) -> ScalarExpr:
    if isinstance(expression, ComputeResultScalarExpr):
        return replace(
            expression,
            value_id=expression.value_id.prefixed(*scope),
            origin=(*origin, *expression.origin),
        )
    if isinstance(expression, ParameterLookupScalarExpr):
        return replace(
            expression,
            key={
                name: _scope_scalar_expression(value, scope=scope, origin=origin)
                for name, value in expression.key.items()
            },
        )
    if isinstance(expression, BinaryScalarExpr):
        return replace(
            expression,
            left=_scope_scalar_expression(
                expression.left,
                scope=scope,
                origin=origin,
            ),
            right=_scope_scalar_expression(
                expression.right,
                scope=scope,
                origin=origin,
            ),
        )
    return expression
