"""Typed value edges used while composing symbolic programs."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Never, cast, override
from uuid import uuid4

import scopecat.kernel.frozen as _frozen
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_data import Row
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import Scalar, Table, ValueType
from scopecat.kernel.value_validation import (
    ValuePath,
    coerce_literal,
)
from scopecat.program.expression_analysis import (
    plan_input_refs,
    plan_module_exports,
    plan_requires_execution,
    scalar_nodes,
)
from scopecat.program.expression_binding import substitute_scalar_input_refs
from scopecat.program.expression_operators import ScalarOperator
from scopecat.program.expressions import (
    BinaryScalarExpr,
    ComputeResultScalarExpr,
    InputScalarExpr,
    LiteralScalarExpr,
    ModuleExportScalarExpr,
    ParameterLookupScalarExpr,
    ParameterLookupUse,
    ParameterScalarExpr,
    PointColumnScalarExpr,
    ScalarExpr,
    ScalarExpression,
    as_scalar_expr,
    input_ref,
    lit,
    parameter_lookup,
    point_col,
)
from scopecat.program.identities import InvocationKey
from scopecat.program.parameters import (
    ParameterContract,
    ParameterValueContract,
    merge_parameter_contracts,
)
from scopecat.program.table_values import (
    InputTableSource,
    LiteralTableSource,
    ParameterTableSource,
    TableSource,
    literal_table_source,
)
from scopecat.program.value_graph import (
    OperationId,
    ValueId,
    operation_result_id,
)

type FrozenScalarLiteral = (
    Quantity | EntityRef | PayloadValue | str | int | float | bool | None
)
type ScalarOperand = ValueRef | FrozenScalarLiteral


@dataclass(frozen=True, slots=True)
class _ModuleExportTableSource:
    """One unresolved table projection from a particular module invocation."""

    invocation_key: InvocationKey
    export_id: str
    value_type: Table


type _ValueSource = ScalarExpr | _ModuleExportTableSource | TableSource


def _fresh_value_id() -> ValueId:
    return ValueId(
        SymbolId(
            scope=("values",),
            local_id=f"v_{uuid4().hex}",
        )
    )


@dataclass(frozen=True, slots=True)
class PointValueDependency:
    """One point value consumed by a canonical scalar expression."""

    id: str
    value_type: Scalar


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class ValueRef:
    """Opaque public handle for one typed canonical program value.

    Values are created by DSL factories such as :func:`scopecat.input` and
    :func:`scopecat.parameter`. Their source expression and provenance remain
    compiler-facing semantic state.
    """

    source: _ValueSource
    value_type: ValueType
    id: ValueId = field(default_factory=_fresh_value_id)

    def __post_init__(self) -> None:
        source = self.source
        if isinstance(source, ScalarExpr):
            if not isinstance(self.value_type, Scalar) or not is_assignable(
                source.value_type,
                self.value_type,
            ):
                msg = "scalar value source must be assignable to its value type"
                raise TypeError(msg)
            return
        if not isinstance(self.value_type, Table):
            msg = "table value source requires a table value type"
            raise TypeError(msg)
        if isinstance(source, _ModuleExportTableSource) and not is_assignable(
            source.value_type, self.value_type
        ):
            msg = "module export table source must be assignable to its value type"
            raise TypeError(msg)

    def __copy__(self) -> ValueRef:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> ValueRef:
        del memo
        return self

    @override
    def __repr__(self) -> str:
        return f"{type(self).__qualname__}()"

    @override
    def __eq__(self, other: object) -> bool:
        return isinstance(other, ValueRef) and self.id == other.id

    @override
    def __hash__(self) -> int:
        return hash(self.id)

    def __add__(self, other: object) -> ValueRef:
        return _binary_value(self, other, "+")

    def __radd__(self, other: object) -> ValueRef:
        return _binary_value(other, self, "+")

    def __sub__(self, other: object) -> ValueRef:
        return _binary_value(self, other, "-")

    def __rsub__(self, other: object) -> ValueRef:
        return _binary_value(other, self, "-")

    def __mul__(self, other: object) -> ValueRef:
        return _binary_value(self, other, "*")

    def __rmul__(self, other: object) -> ValueRef:
        return _binary_value(other, self, "*")

    def __truediv__(self, other: object) -> ValueRef:
        return _binary_value(self, other, "/")

    def __rtruediv__(self, other: object) -> ValueRef:
        return _binary_value(other, self, "/")


def internal_input_value_ref(input_id: str, value_type: ValueType) -> ValueRef:
    return ValueRef(
        source=(
            input_ref(input_id, value_type)
            if isinstance(value_type, Scalar)
            else InputTableSource(input_id)
        ),
        value_type=value_type,
    )


def internal_operation_result_value_ref(
    operation_id: SymbolId | str,
    value_type: Scalar,
    *,
    origin: tuple[object, ...] = (),
    point_dependencies: tuple[PointValueDependency, ...] = (),
) -> ValueRef:
    selected_operation_id = (
        operation_id
        if isinstance(operation_id, SymbolId)
        else SymbolId(local_id=operation_id)
    )
    result_id = operation_result_id(OperationId(selected_operation_id))
    return ValueRef(
        source=ComputeResultScalarExpr(
            value_id=result_id,
            value_type=value_type,
            origin=origin,
            point_dependencies=tuple(
                (dependency.id, dependency.value_type)
                for dependency in _merge_point_dependencies(point_dependencies)
            ),
        ),
        value_type=value_type,
    )


def internal_point_value_ref(point_id: str, value_type: Scalar) -> ValueRef:
    """Create a typed value supplied by the current experiment point."""

    return ValueRef(
        source=point_col(point_id, value_type),
        value_type=value_type,
    )


def internal_parameter_lookup_value_ref(
    use: ParameterLookupUse,
    *,
    key: Mapping[str, ScalarOperand],
) -> ValueRef:
    """Create a direct parameter-cell reference retained by parameter scans."""

    captured_key = tuple(key.items())
    bound_values = tuple(
        value for _name, value in captured_key if isinstance(value, ValueRef)
    )
    _require_relation_bindings(bound_values)
    expression_key = {
        name: _scalar_expression(value) if isinstance(value, ValueRef) else value
        for name, value in captured_key
    }
    return ValueRef(
        source=parameter_lookup(use, key=expression_key),
        value_type=use.result_type,
    )


def internal_value_ref_parameter_lookup(
    value: ValueRef,
) -> tuple[ParameterLookupUse, tuple[tuple[str, ScalarOperand], ...]] | None:
    """Return the cell locator only for a direct parameter lookup."""

    source = value.source
    if not isinstance(source, ParameterLookupScalarExpr):
        return None
    literal_columns = source.use.literal_key_columns
    return source.use, tuple(
        (
            name,
            cast(
                "FrozenScalarLiteral",
                cast("LiteralScalarExpr", expression).value,
            )
            if name in literal_columns
            else ValueRef(
                source=expression,
                value_type=expression.value_type,
            ),
        )
        for name, expression in source.key.items()
    )


def internal_module_export_value_ref(
    invocation_key: InvocationKey,
    export_id: str,
    value_type: ValueType,
) -> ValueRef:
    """Create an unresolved use of one invocation's exported value.

    Module exports are interface projections in the canonical expression tree.
    Elaboration resolves them through the referenced module instance before the
    program crosses the compiler boundary.
    """

    if isinstance(value_type, Scalar):
        source: _ValueSource = ModuleExportScalarExpr(
            invocation_key=invocation_key,
            export_id=export_id,
            value_type=value_type,
        )
    else:
        source = _ModuleExportTableSource(
            invocation_key=invocation_key,
            export_id=export_id,
            value_type=value_type,
        )
    return ValueRef(source=source, value_type=value_type)


def internal_value_ref_input_id(value: ValueRef) -> str | None:
    source = value.source
    if isinstance(source, InputScalarExpr):
        return source.name
    return source.input_id if isinstance(source, InputTableSource) else None


def internal_value_ref_point_id(value: ValueRef) -> str | None:
    """Return the point coordinate id carried by a point value."""

    source = value.source
    return source.name if isinstance(source, PointColumnScalarExpr) else None


def internal_value_ref_operation_id(value: ValueRef) -> SymbolId | None:
    source = value.source
    if not isinstance(source, ComputeResultScalarExpr):
        return None
    result_id = source.value_id
    scope = result_id.scope
    if len(scope) < 2 or scope[-1] != "outputs":
        raise AssertionError("compute result value id has no canonical producer scope")
    return SymbolId(scope=scope[:-2], local_id=scope[-2])


def internal_value_ref_operation_origin(value: ValueRef) -> tuple[object, ...]:
    source = value.source
    return source.origin if isinstance(source, ComputeResultScalarExpr) else ()


def internal_value_ref_module_export(
    value: ValueRef,
) -> tuple[InvocationKey, str] | None:
    """Return the invocation and export identity for a direct export use."""

    source = value.source
    if isinstance(source, ModuleExportScalarExpr | _ModuleExportTableSource):
        return source.invocation_key, source.export_id
    return None


def internal_require_resolved_value_ref(
    value: ValueRef,
    *,
    context: str = "value",
) -> None:
    """Reject a value whose canonical source still contains a module export."""

    unresolved = _first_module_export(value)
    if unresolved is None:
        return
    _invocation_key, export_id = unresolved
    msg = (
        f"{context} contains unresolved module export {export_id!r}; "
        "module elaboration must resolve exports before lowering"
    )
    raise ValueError(msg)


def _first_module_export(
    value: ValueRef,
) -> tuple[InvocationKey, str] | None:
    direct = internal_value_ref_module_export(value)
    if direct is not None:
        return direct
    source = value.source
    if not isinstance(source, ScalarExpr):
        return None
    exports = plan_module_exports(source)
    return exports[0] if exports else None


def internal_transform_value_ref(
    value: ValueRef,
    transform_leaf: Callable[[ValueRef], ValueRef],
) -> ValueRef:
    """Transform source leaves throughout one typed canonical value.

    Scalar leaves are traversed directly in the canonical expression tree. The
    callback may return an assignable producer type; this function reapplies
    the original use contract. If it expands a leaf into another expression,
    that replacement must already be transformed; recursive export resolution
    remains owned by elaboration.
    """

    source = value.source
    if not isinstance(source, ParameterLookupScalarExpr | BinaryScalarExpr):
        return _transform_value_leaf(value, transform_leaf)
    transformed_source = _transform_scalar_leaves(
        cast("ScalarExpression", source),
        transform_leaf,
    )
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
    if isinstance(source, ModuleExportScalarExpr | _ModuleExportTableSource):
        # An export is an interface use owned by its InvocationKey, not a
        # declaration introduced by the surrounding instance scope.
        return value
    selected_source = (
        _scope_scalar_expression(
            cast("ScalarExpression", source),
            scope=scope,
            origin=origin,
        )
        if isinstance(source, ScalarExpr)
        else source
    )
    return ValueRef(
        source=selected_source,
        value_type=value.value_type,
        id=value.id.prefixed(*scope),
    )


def internal_value_ref_parameter_contracts(
    value: ValueRef,
) -> tuple[ParameterContract, ...]:
    source = value.source
    if isinstance(source, ParameterTableSource):
        return (ParameterValueContract(source.parameter_id, value.value_type),)
    if not isinstance(source, ScalarExpr):
        return ()
    contracts: list[tuple[ParameterContract, ...]] = []
    for node in scalar_nodes(source):
        if isinstance(node, ParameterScalarExpr):
            contracts.append((ParameterValueContract(node.name, node.value_type),))
        elif isinstance(node, ParameterLookupScalarExpr):
            contracts.append((node.use,))
    return merge_parameter_contracts(*contracts)


def internal_value_ref_point_dependencies(
    value: ValueRef,
) -> tuple[PointValueDependency, ...]:
    """Return point ids and types consumed by the canonical expression."""

    source = value.source
    if not isinstance(source, ScalarExpr):
        return ()
    groups: list[tuple[PointValueDependency, ...]] = []
    for node in scalar_nodes(source):
        if isinstance(node, PointColumnScalarExpr):
            groups.append((PointValueDependency(node.name, node.value_type),))
        elif isinstance(node, ComputeResultScalarExpr):
            groups.append(
                tuple(
                    PointValueDependency(point_id, value_type)
                    for point_id, value_type in node.point_dependencies
                )
            )
    return _merge_point_dependencies(*groups)


def internal_value_ref_scalar_input_ids(value: ValueRef) -> frozenset[str]:
    """Return scalar imports remaining after authored input bindings."""

    source = value.source
    if not isinstance(source, ScalarExpr):
        return frozenset()
    return frozenset(plan_input_refs(source))


def internal_value_ref_requires_execution(value: ValueRef) -> bool:
    """Return whether a value contains an opaque compute-result expression."""

    unresolved = _first_module_export(value)
    if unresolved is not None:
        _invocation_key, export_id = unresolved
        msg = f"cannot determine dependencies of unresolved module export {export_id!r}"
        raise ValueError(msg)
    source = value.source
    return isinstance(source, ScalarExpr) and plan_requires_execution(source)


def internal_lower_value_ref(
    value: ValueRef,
) -> ScalarExpr | TableSource:
    """Expose a value's canonical source at the private compiler boundary."""

    source = value.source
    unresolved = _first_module_export(value)
    if unresolved is not None:
        _invocation_key, export_id = unresolved
        msg = (
            f"cannot lower unresolved module export {export_id!r}; "
            "module elaboration must resolve exports first"
        )
        raise ValueError(msg)
    if isinstance(source, ScalarExpr):
        return source
    if isinstance(
        source,
        LiteralTableSource | ParameterTableSource | InputTableSource,
    ):
        return source
    raise AssertionError("resolved value source has an unsupported shape")


def internal_lower_scalar_value_ref(value: ValueRef) -> ScalarExpression:
    """Expose a canonical pure scalar expression at the compiler boundary."""

    if not isinstance(value.value_type, Scalar):
        msg = "scalar expression requires a scalar value"
        raise TypeError(msg)
    lowered = internal_lower_value_ref(value)
    if isinstance(lowered, ComputeResultScalarExpr):
        msg = "compute outputs must be connected as standalone values"
        raise TypeError(msg)
    if not isinstance(lowered, ScalarExpr):
        msg = "scalar expression requires a scalar value"
        raise TypeError(msg)
    return cast("ScalarExpression", lowered)


def internal_value_ref_from_expression(
    expression: ScalarExpr,
    value_type: Scalar,
) -> ValueRef:
    """Construct a typed expression edge inside the authoring implementation."""

    return ValueRef(
        source=expression,
        value_type=value_type,
    )


def internal_table_value_ref(
    source: TableSource,
    value_type: Table,
) -> ValueRef:
    """Construct a direct whole-table edge for a domain compiler input."""

    return ValueRef(
        source=source,
        value_type=value_type,
    )


def internal_literal_value_ref(
    value: object,
    value_type: ValueType,
    *,
    path: ValuePath,
) -> ValueRef:
    """Capture one closed literal as a typed edge without exposing raw IR."""

    from scopecat.program.expression_binding import input_cell

    coerced = coerce_literal(value_type, value, path=path)
    if isinstance(value_type, Table):
        return internal_table_value_ref(
            literal_table_source(cast("tuple[Row, ...]", coerced)),
            value_type,
        )
    return internal_value_ref_from_expression(
        lit(input_cell(coerced), value_type),
        value_type,
    )


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
    reachable = frozenset(plan_input_refs(source)) & inputs.keys()
    if not reachable:
        return value
    selected = {
        input_id: inputs[input_id] for input_id in inputs if input_id in reachable
    }
    _require_relation_bindings(tuple(selected.values()))
    replacements = {
        input_id: _scalar_expression(bound) for input_id, bound in selected.items()
    }
    bound_source = cast(
        "ScalarExpression",
        substitute_scalar_input_refs(source, replacements),
    )
    return ValueRef(
        source=bound_source,
        value_type=value.value_type,
        id=value.id,
    )


def internal_value_ref_unbound_input_ids(value: ValueRef) -> frozenset[str]:
    """Return lexical input ids that remain free in one typed value edge."""

    return _value_ref_unbound_input_ids(value)


def _value_ref_unbound_input_ids(value: ValueRef) -> frozenset[str]:
    source = value.source
    if not isinstance(source, ScalarExpr):
        return frozenset()
    return frozenset(plan_input_refs(source))


def _binary_value(left: object, right: object, operator: str) -> ValueRef:
    selected_operator = cast("ScalarOperator", operator)
    left_operand = _capture_scalar_operand(left)
    right_operand = _capture_scalar_operand(right)
    operands = tuple(
        operand
        for operand in (left_operand, right_operand)
        if isinstance(operand, ValueRef)
    )
    _require_relation_bindings(operands)

    left_expression = _scalar_operand_expression(left_operand)
    right_expression = _scalar_operand_expression(right_operand)
    expression = BinaryScalarExpr(
        op=selected_operator,
        left=left_expression,
        right=right_expression,
    )
    return ValueRef(
        source=expression,
        value_type=expression.value_type,
    )


def _scalar_operand_expression(operand: ScalarOperand) -> ScalarExpression:
    return (
        _scalar_expression(operand)
        if isinstance(operand, ValueRef)
        else as_scalar_expr(operand)
    )


def _capture_scalar_operand(value: object) -> ScalarOperand:
    if isinstance(value, ValueRef):
        return value
    if isinstance(value, PayloadValue):
        return value

    try:
        captured = capture_runtime_input(value)
    except TypeError as error:
        msg = "scalar operations require typed values or closed scalar literals"
        raise TypeError(msg) from error
    return cast("FrozenScalarLiteral", captured)


def _require_relation_bindings(values: tuple[ValueRef, ...]) -> None:
    if any(
        _first_module_export(value) is None
        and internal_value_ref_requires_execution(value)
        for value in values
    ):
        msg = (
            "compute outputs cannot be bound inside scalar expressions; "
            "express this calculation with ModuleContext.compute"
        )
        raise TypeError(msg)


def _merge_point_dependencies(
    *groups: tuple[PointValueDependency, ...],
) -> tuple[PointValueDependency, ...]:
    selected: dict[str, PointValueDependency] = {}
    for dependency in (item for group in groups for item in group):
        existing = selected.get(dependency.id)
        if existing is not None and existing.value_type != dependency.value_type:
            msg = (
                f"point value {dependency.id!r} is used with conflicting declared types"
            )
            raise TypeError(msg)
        selected.setdefault(dependency.id, dependency)
    return tuple(selected.values())


def _scalar_expression(value: ValueRef) -> ScalarExpression:
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
    return cast("ScalarExpression", source)


def _transform_scalar_leaves(
    expression: ScalarExpression,
    transform_leaf: Callable[[ValueRef], ValueRef],
) -> ScalarExpression:
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
    return cast("ScalarExpression", source)


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
    expression: ScalarExpression,
    *,
    scope: tuple[str, ...],
    origin: tuple[object, ...],
) -> ScalarExpression:
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


def empty_frozen_mapping() -> Mapping[str, Never]:
    """Return an empty immutable mapping usable by covariant public fields."""

    return _frozen.FrozenMapping[str, Never]()


def capture_runtime_input(value: object) -> object:
    """Validate and snapshot one closed runtime input."""

    return _capture_value(
        value,
        allow_value_ref=False,
        allow_payload=False,
        active_containers=set(),
        path="runtime input",
    )


def capture_runtime_inputs(
    values: Mapping[str, object],
) -> _frozen.FrozenMapping[str, object]:
    """Validate and snapshot a named set of closed runtime inputs."""

    return _capture_named_values(
        values,
        allow_value_ref=False,
        allow_payload=False,
        domain="runtime",
    )


def capture_module_inputs(
    values: Mapping[str, object],
) -> _frozen.FrozenMapping[str, object]:
    """Validate and snapshot module inputs while preserving typed edges."""

    return _capture_named_values(
        values,
        allow_value_ref=True,
        allow_payload=True,
        domain="module",
    )


def _capture_named_values(
    values: Mapping[str, object],
    *,
    allow_value_ref: bool,
    allow_payload: bool,
    domain: str,
) -> _frozen.FrozenMapping[str, object]:
    captured: list[tuple[str, object]] = []
    for name, value in cast("Mapping[object, object]", values).items():
        if not isinstance(name, str) or not name:
            msg = f"{domain} input names must be non-empty strings"
            raise TypeError(msg)
        captured.append(
            (
                name,
                _capture_value(
                    value,
                    allow_value_ref=allow_value_ref,
                    allow_payload=allow_payload,
                    active_containers=set(),
                    path=f"{domain} input {name!r}",
                ),
            )
        )
    return _frozen.FrozenMapping(captured)


def _capture_value(
    value: object,
    *,
    allow_value_ref: bool,
    allow_payload: bool,
    active_containers: set[int],
    path: str,
) -> object:
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            msg = f"{path} numbers must be finite"
            raise ValueError(msg)
        return value
    if isinstance(value, Quantity):
        if not math.isfinite(value.value):
            msg = f"{path} quantities must be finite"
            raise ValueError(msg)
        return value
    if isinstance(value, EntityRef):
        return value
    if isinstance(value, ValueRef) and allow_value_ref:
        return value
    if isinstance(value, PayloadValue) and allow_payload:
        return value
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        marker = _enter_container(mapping, active_containers, path=path)
        try:
            return _frozen.FrozenMapping(
                (
                    _runtime_mapping_key(name, path=path),
                    _capture_value(
                        item,
                        allow_value_ref=allow_value_ref,
                        allow_payload=allow_payload,
                        active_containers=active_containers,
                        path=f"{path}.{name}",
                    ),
                )
                for name, item in mapping.items()
            )
        finally:
            active_containers.remove(marker)
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        marker = _enter_container(sequence, active_containers, path=path)
        try:
            return tuple(
                _capture_value(
                    item,
                    allow_value_ref=allow_value_ref,
                    allow_payload=allow_payload,
                    active_containers=active_containers,
                    path=f"{path}[{index}]",
                )
                for index, item in enumerate(sequence)
            )
        finally:
            active_containers.remove(marker)
    policy = (
        "typed values or closed literal data"
        if allow_value_ref or allow_payload
        else "closed runtime data"
    )
    msg = f"{path} must be {policy}; got {type(value).__name__}"
    raise TypeError(msg)


def _enter_container(value: object, active_containers: set[int], *, path: str) -> int:
    marker = id(value)
    if marker in active_containers:
        msg = f"{path} contains a cycle"
        raise ValueError(msg)
    active_containers.add(marker)
    return marker


def _runtime_mapping_key(value: object, *, path: str) -> str:
    if isinstance(value, str):
        return value
    msg = f"{path} object keys must be strings"
    raise TypeError(msg)
