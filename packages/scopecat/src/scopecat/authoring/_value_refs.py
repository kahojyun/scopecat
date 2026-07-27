"""Typed value edges used while composing authoring modules."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Never, cast, override
from uuid import UUID, uuid4

import scopecat.kernel.frozen as _frozen
from scopecat.authoring._identities import InvocationKey
from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.graph.relations.analysis import plan_input_refs
from scopecat.graph.relations.model import (
    BinaryScalarExpr,
    ParameterLookupUse,
    Row,
    ScalarExpr,
    ScalarExpression,
    as_scalar_expr,
    input_ref,
    lit,
    parameter_lookup,
    point_col,
)
from scopecat.graph.relations.operators import (
    ScalarOperator,
    scalar_operator_result_type,
)
from scopecat.graph.table_values import (
    InputTableSource,
    LiteralTableSource,
    ParameterTableSource,
    TableSource,
    literal_table_source,
)
from scopecat.graph.values import (
    ComputeResultRef,
    OperationId,
    operation_result_id,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_type_compatibility import (
    literal_scalar_type as _literal_scalar_type,
)
from scopecat.kernel.value_types import Scalar, Table, ValueType
from scopecat.kernel.value_validation import (
    ValuePath,
    coerce_literal,
)

type _InputBindingLayers = tuple[tuple[tuple[str, ValueRef], ...], ...]

type FrozenScalarLiteral = (
    Quantity | EntityRef | PayloadValue | str | int | float | bool | None
)
type ScalarOperand = ValueRef | FrozenScalarLiteral


@dataclass(frozen=True, slots=True)
class _ParameterLookupDescriptor:
    use: ParameterLookupUse
    key: tuple[tuple[str, ScalarOperand], ...]


@dataclass(frozen=True, slots=True)
class ValueDeclarationKey:
    """Nominal identity of one transient authoring value declaration."""

    value: UUID

    @classmethod
    def fresh(cls) -> ValueDeclarationKey:
        return cls(uuid4())


@dataclass(frozen=True, slots=True)
class _InputValueSource:
    id: str


@dataclass(frozen=True, slots=True)
class _ComputeValueSource:
    operation_id: SymbolId
    origin: tuple[object, ...] = ()


@dataclass(frozen=True, slots=True)
class _PointValueSource:
    id: str


@dataclass(frozen=True, slots=True)
class _ExpressionValueSource:
    expression: ScalarExpr
    input_binding_layers: _InputBindingLayers = ()


type _ValueDeclarationIdentity = tuple[ValueDeclarationKey, tuple[str, ...]]


class _LoweredValueRefInputs(Mapping[str, object]):
    """Lazily lower one authored input layer at the relation boundary."""

    def __init__(self, values: Mapping[str, ValueRef]) -> None:
        self._values = values

    @override
    def __getitem__(self, key: str) -> object:
        return internal_lower_value_ref(self._values[key])

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    @override
    def __len__(self) -> int:
        return len(self._values)


@dataclass(frozen=True, slots=True)
class _ModuleExportSource:
    """One unresolved projection from a particular module invocation."""

    invocation_key: InvocationKey
    export_id: str


type _ValueSource = (
    _InputValueSource
    | _ComputeValueSource
    | _PointValueSource
    | _ExpressionValueSource
    | _ModuleExportSource
    | TableSource
)


@dataclass(frozen=True, slots=True)
class PointValueDependency:
    """One point value consumed by a typed authoring value graph."""

    id: str
    value_type: Scalar


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class ValueRef:
    """Opaque first-class typed edge in the public authoring value graph.

    Values are created by DSL factories such as :func:`scopecat.input` and
    :func:`scopecat.parameter`.  Their source expression and provenance are
    compiler-facing semantic state.
    """

    source: _ValueSource
    value_type: ValueType
    declaration_key: ValueDeclarationKey = field(
        default_factory=ValueDeclarationKey.fresh
    )
    declaration_scope: tuple[str, ...] = ()
    parameter_contracts: tuple[ParameterContract, ...] = ()
    point_dependencies: tuple[PointValueDependency, ...] = ()
    parameter_lookup_descriptor: _ParameterLookupDescriptor | None = field(
        default=None,
        compare=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "point_dependencies",
            _merge_point_dependencies(self.point_dependencies),
        )

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
        return isinstance(other, ValueRef) and (
            self.declaration_key,
            self.declaration_scope,
        ) == (
            other.declaration_key,
            other.declaration_scope,
        )

    @override
    def __hash__(self) -> int:
        return hash((self.declaration_key, self.declaration_scope))

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
        source=_InputValueSource(id=input_id),
        value_type=value_type,
    )


def internal_operation_result_value_ref(
    operation_id: SymbolId | str,
    value_type: ValueType,
    *,
    origin: tuple[object, ...] = (),
    point_dependencies: tuple[PointValueDependency, ...] = (),
) -> ValueRef:
    selected_operation_id = (
        operation_id
        if isinstance(operation_id, SymbolId)
        else SymbolId(local_id=operation_id)
    )
    return ValueRef(
        source=_ComputeValueSource(
            operation_id=selected_operation_id,
            origin=origin,
        ),
        value_type=value_type,
        point_dependencies=_merge_point_dependencies(point_dependencies),
    )


def internal_point_value_ref(point_id: str, value_type: Scalar) -> ValueRef:
    """Create a typed value supplied by the current experiment point."""

    point_dependencies = (PointValueDependency(id=point_id, value_type=value_type),)
    return ValueRef(
        source=_PointValueSource(id=point_id),
        value_type=value_type,
        point_dependencies=point_dependencies,
    )


def internal_parameter_lookup_value_ref(
    use: ParameterLookupUse,
    *,
    key: Mapping[str, ScalarOperand],
) -> ValueRef:
    """Create a direct parameter-cell reference retained by parameter scans."""

    captured_key = tuple(key.items())
    expression_key = {
        name: (
            internal_lower_scalar_value_ref(value)
            if isinstance(value, ValueRef)
            else value
        )
        for name, value in captured_key
    }
    return ValueRef(
        source=_ExpressionValueSource(
            expression=parameter_lookup(use, key=expression_key),
        ),
        value_type=use.result_type,
        parameter_contracts=merge_parameter_contracts(
            (use,),
            *(
                value.parameter_contracts
                for _name, value in captured_key
                if isinstance(value, ValueRef)
            ),
        ),
        point_dependencies=_merge_point_dependencies(
            *(
                value.point_dependencies
                for _name, value in captured_key
                if isinstance(value, ValueRef)
            ),
        ),
        parameter_lookup_descriptor=_ParameterLookupDescriptor(use, captured_key),
    )


def internal_value_ref_parameter_lookup(
    value: ValueRef,
) -> tuple[ParameterLookupUse, tuple[tuple[str, ScalarOperand], ...]] | None:
    """Return the cell locator only for a direct parameter lookup."""

    descriptor = value.parameter_lookup_descriptor
    if descriptor is None:
        return None
    return descriptor.use, descriptor.key


def internal_module_export_value_ref(
    invocation_key: InvocationKey,
    export_id: str,
    value_type: ValueType,
) -> ValueRef:
    """Create an unresolved use of one invocation's exported value.

    Module exports are interface projections rather than copied value graphs.
    Elaboration must resolve this edge through the referenced module instance
    before any value is lowered to relation or compiler expressions.
    """

    return ValueRef(
        source=_ModuleExportSource(
            invocation_key=invocation_key,
            export_id=export_id,
        ),
        value_type=value_type,
    )


def internal_value_ref_declaration_identity(
    value: ValueRef,
) -> _ValueDeclarationIdentity:
    """Return the nominal key paired with its structural declaration scope."""

    return (
        value.declaration_key,
        value.declaration_scope,
    )


def internal_value_ref_input_id(value: ValueRef) -> str | None:
    source = value.source
    return source.id if isinstance(source, _InputValueSource) else None


def internal_value_ref_point_id(value: ValueRef) -> str | None:
    """Return the point coordinate id carried by a point value."""

    source = value.source
    return source.id if isinstance(source, _PointValueSource) else None


def internal_value_ref_operation_id(value: ValueRef) -> SymbolId | None:
    source = value.source
    return source.operation_id if isinstance(source, _ComputeValueSource) else None


def internal_value_ref_operation_origin(value: ValueRef) -> tuple[object, ...]:
    source = value.source
    return source.origin if isinstance(source, _ComputeValueSource) else ()


def internal_value_ref_module_export(
    value: ValueRef,
) -> tuple[InvocationKey, str] | None:
    """Return the invocation and export identity for a direct export use."""

    source = value.source
    if not isinstance(source, _ModuleExportSource):
        return None
    return source.invocation_key, source.export_id


def internal_require_resolved_value_ref(
    value: ValueRef,
    *,
    context: str = "value",
) -> None:
    """Reject a value graph that still contains a module-interface edge."""

    unresolved = _first_module_export(value, seen=frozenset())
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
    *,
    seen: frozenset[_ValueDeclarationIdentity],
) -> tuple[InvocationKey, str] | None:
    direct = internal_value_ref_module_export(value)
    if direct is not None:
        return direct
    marker = internal_value_ref_declaration_identity(value)
    if marker in seen:
        return None
    nested_seen = seen | {marker}
    source = value.source
    if not isinstance(source, _ExpressionValueSource):
        return None
    for layer in source.input_binding_layers:
        for _input_id, bound in layer:
            selected = _first_module_export(bound, seen=nested_seen)
            if selected is not None:
                return selected
    return None


def internal_transform_value_ref(
    value: ValueRef,
    transform_leaf: Callable[[ValueRef], ValueRef],
) -> ValueRef:
    """Transform source leaves throughout one typed value edge.

    Expression syntax remains unchanged, while values captured by its deferred
    input-binding layers are traversed recursively.  The callback must preserve
    the exact semantic value type.  If it expands a leaf into another graph,
    that replacement must already be transformed; this keeps recursive export
    resolution and cycle reporting under the elaboration pass that owns the
    module-instance graph.
    """

    return _transform_value_ref(
        value,
        transform_leaf=transform_leaf,
        active=frozenset(),
    )


def _transform_value_ref(
    value: ValueRef,
    *,
    transform_leaf: Callable[[ValueRef], ValueRef],
    active: frozenset[_ValueDeclarationIdentity],
) -> ValueRef:
    source = value.source
    if not isinstance(source, _ExpressionValueSource):
        transformed = transform_leaf(value)
        if transformed.value_type != value.value_type:
            msg = "value reference transform must preserve the exact value type"
            raise TypeError(msg)
        return transformed

    marker = internal_value_ref_declaration_identity(value)
    if marker in active:
        msg = "cyclic value reference graph"
        raise ValueError(msg)
    nested_active = active | {marker}

    layers = source.input_binding_layers
    transformed_layers = tuple(
        tuple(
            (
                input_id,
                _transform_value_ref(
                    bound,
                    transform_leaf=transform_leaf,
                    active=nested_active,
                ),
            )
            for input_id, bound in layer
        )
        for layer in layers
    )
    if all(
        transformed is original
        for original_layer, transformed_layer in zip(
            layers,
            transformed_layers,
            strict=True,
        )
        for (_input_id, original), (_transformed_id, transformed) in zip(
            original_layer,
            transformed_layer,
            strict=True,
        )
    ):
        return value

    transformed_values = tuple(
        bound for layer in transformed_layers for _input_id, bound in layer
    )
    _require_relation_bindings(transformed_values)
    return ValueRef(
        source=_ExpressionValueSource(
            expression=source.expression,
            input_binding_layers=transformed_layers,
        ),
        value_type=value.value_type,
        declaration_key=value.declaration_key,
        declaration_scope=value.declaration_scope,
        parameter_contracts=merge_parameter_contracts(
            value.parameter_contracts,
            *(bound.parameter_contracts for bound in transformed_values),
        ),
        point_dependencies=_merge_point_dependencies(
            value.point_dependencies,
            *(bound.point_dependencies for bound in transformed_values),
        ),
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
    if isinstance(source, _ModuleExportSource):
        # An export is an interface use owned by its InvocationKey, not a
        # declaration introduced by the surrounding instance scope.
        return value
    declaration_scope = (
        *scope,
        *value.declaration_scope,
    )
    if isinstance(source, _ComputeValueSource):
        return ValueRef(
            source=_ComputeValueSource(
                operation_id=source.operation_id.prefixed(*scope),
                origin=(*origin, *source.origin),
            ),
            value_type=value.value_type,
            declaration_key=value.declaration_key,
            declaration_scope=declaration_scope,
            parameter_contracts=value.parameter_contracts,
            point_dependencies=value.point_dependencies,
        )
    if isinstance(source, _ExpressionValueSource):
        layers = source.input_binding_layers
        return ValueRef(
            source=_ExpressionValueSource(
                expression=source.expression,
                input_binding_layers=tuple(
                    tuple(
                        (
                            input_id,
                            internal_scope_value_ref(
                                bound,
                                *scope,
                                origin=origin,
                            ),
                        )
                        for input_id, bound in layer
                    )
                    for layer in layers
                ),
            ),
            value_type=value.value_type,
            declaration_key=value.declaration_key,
            declaration_scope=declaration_scope,
            parameter_contracts=value.parameter_contracts,
            point_dependencies=value.point_dependencies,
        )
    return ValueRef(
        source=source,
        value_type=value.value_type,
        declaration_key=value.declaration_key,
        declaration_scope=declaration_scope,
        parameter_contracts=value.parameter_contracts,
        point_dependencies=value.point_dependencies,
    )


def internal_value_ref_parameter_contracts(
    value: ValueRef,
) -> tuple[ParameterContract, ...]:
    return value.parameter_contracts


def internal_value_ref_point_dependencies(
    value: ValueRef,
) -> tuple[PointValueDependency, ...]:
    """Return point ids and types consumed anywhere in a typed value graph."""

    return value.point_dependencies


def internal_value_ref_scalar_input_ids(value: ValueRef) -> frozenset[str]:
    """Return scalar imports remaining after authored input bindings."""

    lowered = internal_lower_value_ref(value)
    if not isinstance(lowered, ScalarExpr):
        return frozenset()
    return frozenset(plan_input_refs(lowered))


def internal_value_ref_requires_execution(value: ValueRef) -> bool:
    """Return whether a value graph contains an opaque compute result."""

    return _value_ref_requires_execution(value, seen=frozenset())


def _value_ref_requires_execution(
    value: ValueRef,
    *,
    seen: frozenset[_ValueDeclarationIdentity],
) -> bool:
    marker = internal_value_ref_declaration_identity(value)
    if marker in seen:
        return False
    nested_seen = seen | {marker}
    source = value.source
    if isinstance(source, _ComputeValueSource):
        return True
    if isinstance(source, _PointValueSource | _InputValueSource):
        return False
    if isinstance(source, _ModuleExportSource):
        msg = (
            "cannot determine dependencies of unresolved module export "
            f"{source.export_id!r}"
        )
        raise ValueError(msg)
    if not isinstance(source, _ExpressionValueSource):
        return False
    return any(
        _value_ref_requires_execution(bound, seen=nested_seen)
        for layer in source.input_binding_layers
        for _input_id, bound in layer
    )


def internal_lower_value_ref(
    value: ValueRef,
) -> ScalarExpr | TableSource | ComputeResultRef:
    """Lower a typed edge at the private compiler boundary."""

    source = value.source
    if isinstance(source, _ComputeValueSource):
        operation_id = OperationId(source.operation_id)
        return ComputeResultRef(value_id=operation_result_id(operation_id))
    if isinstance(source, _ModuleExportSource):
        msg = (
            f"cannot lower unresolved module export {source.export_id!r}; "
            "module elaboration must resolve exports first"
        )
        raise ValueError(msg)
    if isinstance(source, _ExpressionValueSource):
        expression = source.expression
        layers = source.input_binding_layers
        if not layers:
            return expression
        from scopecat.graph.relations.input_binding import (
            substitute_scalar_input_refs,
        )

        for layer in layers:
            expression = substitute_scalar_input_refs(
                expression,
                _LoweredValueRefInputs(dict(layer)),
            )
        return expression
    if isinstance(
        source,
        LiteralTableSource | ParameterTableSource | InputTableSource,
    ):
        return source
    if isinstance(source, _PointValueSource):
        return point_col(source.id)
    source_id = source.id
    return (
        input_ref(source_id)
        if isinstance(value.value_type, Scalar)
        else InputTableSource(source_id)
    )


def internal_lower_scalar_value_ref(value: ValueRef) -> ScalarExpression:
    """Lower a typed scalar edge at the private compiler boundary."""

    if not isinstance(value.value_type, Scalar):
        msg = "scalar expression requires a scalar value"
        raise TypeError(msg)
    lowered = internal_lower_value_ref(value)
    if not isinstance(lowered, ScalarExpr):
        msg = "compute outputs must be connected as standalone values"
        raise TypeError(msg)
    return cast("ScalarExpression", lowered)


def internal_value_ref_from_expression(
    expression: ScalarExpr,
    value_type: Scalar,
    *,
    declaration_key: ValueDeclarationKey | None = None,
    parameter_contracts: tuple[ParameterContract, ...] = (),
    point_dependencies: tuple[PointValueDependency, ...] = (),
) -> ValueRef:
    """Construct a typed expression edge inside the authoring implementation."""

    return ValueRef(
        source=_ExpressionValueSource(expression=expression),
        value_type=value_type,
        declaration_key=declaration_key or ValueDeclarationKey.fresh(),
        parameter_contracts=parameter_contracts,
        point_dependencies=point_dependencies,
    )


def internal_table_value_ref(
    source: TableSource,
    value_type: Table,
    *,
    parameter_contracts: tuple[ParameterContract, ...] = (),
) -> ValueRef:
    """Construct a direct whole-table edge for a domain compiler input."""

    return ValueRef(
        source=source,
        value_type=value_type,
        parameter_contracts=parameter_contracts,
    )


def internal_literal_value_ref(
    value: object,
    value_type: ValueType,
    *,
    path: ValuePath,
) -> ValueRef:
    """Capture one closed literal as a typed edge without exposing raw IR."""

    from scopecat.graph.relations.input_binding import input_cell

    coerced = coerce_literal(value_type, value, path=path)
    if isinstance(value_type, Table):
        return internal_table_value_ref(
            literal_table_source(cast("tuple[Row, ...]", coerced)),
            value_type,
        )
    return internal_value_ref_from_expression(
        lit(input_cell(coerced)),
        value_type,
    )


def internal_bind_value_ref_inputs(
    value: ValueRef,
    inputs: Mapping[str, ValueRef],
) -> ValueRef:
    """Attach one typed module-input environment without lowering the edge."""

    source = value.source
    if isinstance(source, _InputValueSource):
        selected = inputs.get(source.id)
        return value if selected is None else selected
    if not isinstance(source, _ExpressionValueSource) or not inputs:
        return value
    layer, _unbound_input_ids = _reachable_input_bindings(
        _value_ref_unbound_input_ids(value),
        inputs,
    )
    if not layer:
        return value
    bound_values = tuple(selected for _input_id, selected in layer)
    _require_relation_bindings(bound_values)
    existing_layers = source.input_binding_layers
    return ValueRef(
        source=_ExpressionValueSource(
            expression=source.expression,
            input_binding_layers=(*existing_layers, layer),
        ),
        value_type=value.value_type,
        declaration_key=value.declaration_key,
        declaration_scope=value.declaration_scope,
        parameter_contracts=merge_parameter_contracts(
            value.parameter_contracts,
            *(selected.parameter_contracts for selected in bound_values),
        ),
        point_dependencies=_merge_point_dependencies(
            value.point_dependencies,
            *(selected.point_dependencies for selected in bound_values),
        ),
    )


def internal_value_ref_unbound_input_ids(value: ValueRef) -> frozenset[str]:
    """Return lexical input ids that remain free in one typed value edge."""

    return _value_ref_unbound_input_ids(value)


def _value_ref_unbound_input_ids(value: ValueRef) -> frozenset[str]:
    source = value.source
    if isinstance(source, _InputValueSource):
        return frozenset((source.id,))
    if not isinstance(source, _ExpressionValueSource):
        return frozenset()

    from scopecat.graph.relations.input_binding import scalar_input_refs

    input_ids = frozenset(scalar_input_refs(source.expression))
    layers = source.input_binding_layers
    for layer in layers:
        _reachable, input_ids = _reachable_input_bindings(input_ids, dict(layer))
    return input_ids


def _reachable_input_bindings(
    input_ids: frozenset[str],
    inputs: Mapping[str, ValueRef],
) -> tuple[tuple[tuple[str, ValueRef], ...], frozenset[str]]:
    """Select bindings reachable from the expression's free input ids."""

    reachable = input_ids & inputs.keys()
    selected = tuple(
        (input_id, value) for input_id, value in inputs.items() if input_id in reachable
    )
    unbound = set(input_ids - reachable)
    unbound.update(
        nested_input_id
        for _input_id, value in selected
        for nested_input_id in _value_ref_unbound_input_ids(value)
    )
    return (
        selected,
        frozenset(unbound),
    )


def _binary_value(left: object, right: object, operator: str) -> ValueRef:
    left_type = _scalar_operand_type(left)
    right_type = _scalar_operand_type(right)
    selected_operator = cast("ScalarOperator", operator)
    left_operand = _capture_scalar_operand(left)
    right_operand = _capture_scalar_operand(right)
    operands = tuple(
        operand
        for operand in (left_operand, right_operand)
        if isinstance(operand, ValueRef)
    )
    _require_relation_bindings(operands)

    declaration_key = ValueDeclarationKey.fresh()
    left_expression, left_binding = _deferred_scalar_operand(
        left_operand,
        declaration_key=declaration_key,
        side="left",
    )
    right_expression, right_binding = _deferred_scalar_operand(
        right_operand,
        declaration_key=declaration_key,
        side="right",
    )
    bindings = tuple(
        binding for binding in (left_binding, right_binding) if binding is not None
    )
    return ValueRef(
        source=_ExpressionValueSource(
            expression=BinaryScalarExpr(
                op=selected_operator,
                left=left_expression,
                right=right_expression,
            ),
            input_binding_layers=(bindings,),
        ),
        value_type=scalar_operator_result_type(
            left_type,
            right_type,
            selected_operator,
        ),
        declaration_key=declaration_key,
        parameter_contracts=merge_parameter_contracts(
            *(operand.parameter_contracts for operand in operands)
        ),
        point_dependencies=_merge_point_dependencies(
            *(operand.point_dependencies for operand in operands)
        ),
    )


def _deferred_scalar_operand(
    operand: ScalarOperand,
    *,
    declaration_key: ValueDeclarationKey,
    side: str,
) -> tuple[ScalarExpression, tuple[str, ValueRef] | None]:
    if not isinstance(operand, ValueRef):
        return as_scalar_expr(operand), None
    input_id = f"__value_operand_{declaration_key.value.hex}_{side}"
    return input_ref(input_id), (input_id, operand)


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
        _first_module_export(value, seen=frozenset()) is None
        and internal_value_ref_requires_execution(value)
        for value in values
    ):
        msg = (
            "compute outputs cannot be bound inside scalar expressions; "
            "express this calculation with sc.compute"
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


def _scalar_operand_type(value: object) -> Scalar:
    if isinstance(value, ValueRef):
        if not isinstance(value.value_type, Scalar):
            msg = "scalar operation requires scalar-shaped values"
            raise TypeError(msg)
        return value.value_type
    if isinstance(value, ScalarExpr):
        msg = "scalar operations require typed values or closed scalar literals"
        raise TypeError(msg)
    return _literal_scalar_type(value)


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
