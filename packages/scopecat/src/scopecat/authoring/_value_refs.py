"""Typed value edges used while composing authoring modules.

The relation expression classes still provide the executable expression tree.  A
``ValueRef`` adds the part that those trees deliberately do not carry: the
complete semantic ``ValueType`` and the identity of the input or compute node
that produced the value.  Module composition keeps these references intact and
only lowers them back to relation/compute references at the compiler boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast, override
from uuid import UUID, uuid4

from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.compiler.relations.analysis import (
    PlanReferenceKind,
    free_row_references,
    plan_references,
    prefix_plan_row_scopes,
    verify_plan_scopes,
)
from scopecat.compiler.relations.model import (
    BinaryScalarExpr,
    ParameterLookupUse,
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    ScalarExpression,
    SeriesExpr,
    as_scalar_expr,
    col,
    input_ref,
    input_series,
    input_table,
    lit,
    parameter_lookup,
    point_col,
)
from scopecat.compiler.relations.operators import (
    ScalarOperator,
    scalar_operator_result_type,
)
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import (
    OperationId,
    operation_result_id,
)
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.symbols import SymbolId
from scopecat.kernel.value_type_compatibility import (
    describe_value_type,
)
from scopecat.kernel.value_type_compatibility import (
    literal_scalar_type as _literal_scalar_type,
)
from scopecat.kernel.value_types import (
    Entity,
    Scalar,
    Series,
    Table,
    TableColumn,
    ValueType,
)
from scopecat.kernel.value_validation import (
    ValuePath,
    coerce_literal,
    format_value_path,
)
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import Quantity

if TYPE_CHECKING:
    from scopecat.authoring._module_ir import InvocationKey

type _ValueExpression = ScalarExpr | SeriesExpr | RelationExpr
type _InputBindingLayers = tuple[tuple[tuple[str, ValueRef], ...], ...]

type FrozenScalarLiteral = (
    Quantity | EntityRef | PayloadValue | str | int | float | bool | None
)
type ScalarOperationOperand = ValueRef | FrozenScalarLiteral


@dataclass(frozen=True, slots=True)
class _ParameterLookupDescriptor:
    use: ParameterLookupUse
    key: tuple[tuple[str, ScalarOperationOperand], ...]


@dataclass(frozen=True, slots=True)
class ValueDeclarationKey:
    """Nominal identity of one transient authoring value declaration."""

    value: UUID

    @classmethod
    def fresh(cls) -> ValueDeclarationKey:
        return cls(uuid4())


@dataclass(frozen=True, slots=True)
class ScalarValueOperation:
    """Backend-neutral scalar operation retained until graph lowering."""

    operator: ScalarOperator
    left: ScalarOperationOperand
    right: ScalarOperationOperand


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
    expression: _ValueExpression
    input_binding_layers: _InputBindingLayers = ()


@dataclass(frozen=True, slots=True)
class _ScalarOperationValueSource:
    operation: ScalarValueOperation


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
    | _ScalarOperationValueSource
)


@dataclass(frozen=True, slots=True)
class PointValueDependency:
    """One point value consumed by a typed authoring value graph."""

    id: str
    value_type: Scalar


@dataclass(frozen=True, slots=True, init=False, eq=False, repr=False)
class TableRow:
    """Typed row scope supplied by table callbacks.

    Row values only exist while an authoring callback is being evaluated, which
    keeps column references tied to the table schema that introduced their scope.
    """

    columns: Mapping[str, TableColumn]
    scope_id: RowScopeId
    parameter_contracts: tuple[ParameterContract, ...]
    point_dependencies: tuple[PointValueDependency, ...]

    def __init__(self, value: ValueRef, *, scope_id: RowScopeId) -> None:
        table_type = value.value_type
        if not isinstance(table_type, Table):
            msg = "row scope requires a table value"
            raise TypeError(msg)
        object.__setattr__(
            self,
            "columns",
            {column.id: column for column in table_type.columns},
        )
        object.__setattr__(self, "scope_id", scope_id)
        object.__setattr__(
            self,
            "parameter_contracts",
            internal_value_ref_parameter_contracts(value),
        )
        object.__setattr__(
            self,
            "point_dependencies",
            internal_value_ref_point_dependencies(value),
        )

    def __copy__(self) -> TableRow:
        return self

    def __deepcopy__(self, memo: dict[int, object]) -> TableRow:
        del memo
        return self

    @override
    def __repr__(self) -> str:
        return (
            f"{type(self).__qualname__}("
            f"columns={self.columns!r}, scope_id={self.scope_id!r})"
        )

    def __getitem__(self, column_id: str) -> ValueRef:
        column = self.columns.get(column_id)
        if column is None:
            msg = f"table row has no column {column_id!r}"
            raise KeyError(msg)
        return internal_value_ref_from_expression(
            col(column_id, row_scope_id=self.scope_id),
            column.value_type,
            parameter_contracts=self.parameter_contracts,
            point_dependencies=self.point_dependencies,
        )


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

    def eq(self, other: object) -> ValueRef:
        return _comparison_value(self, other, "==")

    def ne(self, other: object) -> ValueRef:
        return _comparison_value(self, other, "!=")

    def lt(self, other: object) -> ValueRef:
        return _comparison_value(self, other, "<")

    def le(self, other: object) -> ValueRef:
        return _comparison_value(self, other, "<=")

    def gt(self, other: object) -> ValueRef:
        return _comparison_value(self, other, ">")

    def ge(self, other: object) -> ValueRef:
        return _comparison_value(self, other, ">=")

    def and_(self, other: object) -> ValueRef:
        """Combine two non-nullable typed boolean values."""

        return _logical_value(self, other, "and")

    def or_(self, other: object) -> ValueRef:
        """Combine two non-nullable typed boolean values."""

        return _logical_value(self, other, "or")

    def select(self, *column_ids: str) -> ValueRef:
        """Return a typed table projection."""

        table_type = self.value_type
        if not isinstance(table_type, Table):
            msg = "select requires a table value"
            raise TypeError(msg)
        columns = {column.id: column for column in table_type.columns}
        missing = [column_id for column_id in column_ids if column_id not in columns]
        if missing:
            msg = "table value has no columns: " + ", ".join(missing)
            raise KeyError(msg)
        expression = internal_lower_table_value_ref(self)
        selected_ids = set(column_ids)
        primary_key = (
            table_type.primary_key
            if set(table_type.primary_key) <= selected_ids
            else ()
        )
        return internal_value_ref_from_expression(
            expression.select(*column_ids),
            Table(
                columns=tuple(columns[column_id] for column_id in column_ids),
                primary_key=primary_key,
                min_rows=table_type.min_rows,
                max_rows=table_type.max_rows,
                allow_extra_columns=False,
            ),
            parameter_contracts=self.parameter_contracts,
            point_dependencies=self.point_dependencies,
        )

    def with_columns(
        self,
        build: Callable[[TableRow], Mapping[str, ValueRef]],
    ) -> ValueRef:
        """Add or replace columns inside a schema-bound row callback."""

        table_type = self.value_type
        if not isinstance(table_type, Table):
            msg = "with_columns requires a table value"
            raise TypeError(msg)
        declaration_key = ValueDeclarationKey.fresh()
        row = TableRow(
            self,
            scope_id=RowScopeId(SymbolId(local_id=f"row_{declaration_key.value.hex}")),
        )
        built = cast(
            "object",
            build(row),
        )
        if not isinstance(built, Mapping):
            msg = "with_columns callback must return a mapping of typed values"
            raise TypeError(msg)
        columns = cast("Mapping[object, object]", built)
        expressions: dict[str, ScalarExpr] = {}
        column_types: dict[str, Scalar] = {}
        for column_id, value in columns.items():
            if not isinstance(column_id, str) or not column_id:
                msg = "with_columns callback keys must be non-empty strings"
                raise TypeError(msg)
            if not isinstance(value, ValueRef):
                msg = f"table column {column_id!r} must be a typed value"
                raise TypeError(msg)
            if not isinstance(value.value_type, Scalar):
                msg = f"table column {column_id!r} must be scalar-shaped"
                raise TypeError(msg)
            expressions[column_id] = internal_lower_scalar_value_ref(value)
            column_types[column_id] = value.value_type
        existing = {column.id: column for column in table_type.columns}
        updated = tuple(
            TableColumn(
                column.id,
                column_types.get(column.id, column.value_type),
                required=column.id in column_types or column.required,
            )
            for column in table_type.columns
        )
        added = tuple(
            TableColumn(column_id, value_type)
            for column_id, value_type in column_types.items()
            if column_id not in existing
        )
        primary_key = (
            ()
            if set(table_type.primary_key) & set(column_types)
            else table_type.primary_key
        )
        expression = internal_lower_table_value_ref(self).with_columns(
            row_scope_id=row.scope_id,
            **expressions,
        )
        verify_plan_scopes(expression)
        return internal_value_ref_from_expression(
            expression,
            Table(
                columns=(*updated, *added),
                primary_key=primary_key,
                min_rows=table_type.min_rows,
                max_rows=table_type.max_rows,
                allow_extra_columns=table_type.allow_extra_columns,
            ),
            parameter_contracts=merge_parameter_contracts(
                self.parameter_contracts,
                *(
                    internal_value_ref_parameter_contracts(value)
                    for value in columns.values()
                    if isinstance(value, ValueRef)
                ),
            ),
            point_dependencies=_merge_point_dependencies(
                self.point_dependencies,
                *(
                    internal_value_ref_point_dependencies(value)
                    for value in columns.values()
                    if isinstance(value, ValueRef)
                ),
            ),
            declaration_key=declaration_key,
        )

    def entities(self, *column_ids: str) -> ValueRef:
        """Return a typed, stably deduplicated entity series from table columns."""

        table_type = self.value_type
        if not isinstance(table_type, Table):
            msg = "entities requires a table value"
            raise TypeError(msg)
        if not column_ids:
            msg = "entities requires at least one column"
            raise ValueError(msg)
        columns = {column.id: column for column in table_type.columns}
        selected: list[Entity] = []
        for column_id in column_ids:
            column = columns.get(column_id)
            if column is None:
                msg = f"table value has no column {column_id!r}"
                raise KeyError(msg)
            if not isinstance(column.value_type.atom, Entity):
                msg = f"table column {column_id!r} is not entity-typed"
                raise TypeError(msg)
            selected.append(column.value_type.atom)
        entity_kinds = {entity.entity_kind for entity in selected}
        entity_kind = entity_kinds.pop() if len(entity_kinds) == 1 else None
        return internal_value_ref_from_expression(
            internal_lower_table_value_ref(self).entities(*column_ids),
            Series(Scalar(Entity(entity_kind=entity_kind))),
            parameter_contracts=self.parameter_contracts,
            point_dependencies=self.point_dependencies,
        )


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
    key: Mapping[str, ScalarOperationOperand],
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
                internal_value_ref_parameter_contracts(value)
                for _name, value in captured_key
                if isinstance(value, ValueRef)
            ),
        ),
        point_dependencies=_merge_point_dependencies(
            *(
                internal_value_ref_point_dependencies(value)
                for _name, value in captured_key
                if isinstance(value, ValueRef)
            ),
        ),
        parameter_lookup_descriptor=_ParameterLookupDescriptor(use, captured_key),
    )


def internal_value_ref_parameter_lookup(
    value: ValueRef,
) -> tuple[ParameterLookupUse, tuple[tuple[str, ScalarOperationOperand], ...]] | None:
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


def internal_value_ref_scalar_operation(
    value: ValueRef,
) -> ScalarValueOperation | None:
    """Return the semantic scalar operation defined by this value, if any."""

    source = value.source
    if not isinstance(source, _ScalarOperationValueSource):
        return None
    return source.operation


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
    operation = internal_value_ref_scalar_operation(value)
    if operation is not None:
        for operand in _scalar_operation_value_operands(operation):
            selected = _first_module_export(operand, seen=nested_seen)
            if selected is not None:
                return selected
        return None
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
    if not isinstance(source, _ExpressionValueSource | _ScalarOperationValueSource):
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
    if isinstance(source, _ScalarOperationValueSource):
        operation = source.operation
        left = _transform_scalar_operation_operand(
            operation.left,
            transform_leaf=transform_leaf,
            active=nested_active,
        )
        right = _transform_scalar_operation_operand(
            operation.right,
            transform_leaf=transform_leaf,
            active=nested_active,
        )
        if left is operation.left and right is operation.right:
            return value
        return _rebuild_scalar_operation(
            value,
            ScalarValueOperation(
                operator=operation.operator,
                left=left,
                right=right,
            ),
        )

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
    return ValueRef(
        source=_ExpressionValueSource(
            expression=source.expression,
            input_binding_layers=transformed_layers,
        ),
        value_type=value.value_type,
        declaration_key=value.declaration_key,
        declaration_scope=value.declaration_scope,
        parameter_contracts=merge_parameter_contracts(
            internal_value_ref_parameter_contracts(value),
            *(
                internal_value_ref_parameter_contracts(bound)
                for bound in transformed_values
            ),
        ),
        point_dependencies=_merge_point_dependencies(
            internal_value_ref_point_dependencies(value),
            *(
                internal_value_ref_point_dependencies(bound)
                for bound in transformed_values
            ),
        ),
    )


def _transform_scalar_operation_operand(
    operand: ScalarOperationOperand,
    *,
    transform_leaf: Callable[[ValueRef], ValueRef],
    active: frozenset[_ValueDeclarationIdentity],
) -> ScalarOperationOperand:
    if not isinstance(operand, ValueRef):
        return operand
    return _transform_value_ref(
        operand,
        transform_leaf=transform_leaf,
        active=active,
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
            parameter_contracts=internal_value_ref_parameter_contracts(value),
            point_dependencies=internal_value_ref_point_dependencies(value),
        )
    if isinstance(source, _ScalarOperationValueSource):
        operation = source.operation
        return ValueRef(
            source=_ScalarOperationValueSource(
                operation=ScalarValueOperation(
                    operator=operation.operator,
                    left=_scope_scalar_operation_operand(
                        operation.left,
                        *scope,
                        origin=origin,
                    ),
                    right=_scope_scalar_operation_operand(
                        operation.right,
                        *scope,
                        origin=origin,
                    ),
                ),
            ),
            value_type=value.value_type,
            declaration_key=value.declaration_key,
            declaration_scope=declaration_scope,
        )
    if isinstance(source, _ExpressionValueSource):
        expression = prefix_plan_row_scopes(
            source.expression,
            *scope,
        )
        layers = source.input_binding_layers
        return ValueRef(
            source=_ExpressionValueSource(
                expression=expression,
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
            parameter_contracts=internal_value_ref_parameter_contracts(value),
            point_dependencies=internal_value_ref_point_dependencies(value),
        )
    return ValueRef(
        source=source,
        value_type=value.value_type,
        declaration_key=value.declaration_key,
        declaration_scope=declaration_scope,
        parameter_contracts=internal_value_ref_parameter_contracts(value),
        point_dependencies=internal_value_ref_point_dependencies(value),
    )


def _scope_scalar_operation_operand(
    operand: ScalarOperationOperand,
    *scope: str,
    origin: tuple[object, ...],
) -> ScalarOperationOperand:
    if not isinstance(operand, ValueRef):
        return operand
    return internal_scope_value_ref(operand, *scope, origin=origin)


def internal_value_ref_parameter_contracts(
    value: ValueRef,
) -> tuple[ParameterContract, ...]:
    operation = internal_value_ref_scalar_operation(value)
    if operation is not None:
        return merge_parameter_contracts(
            *(
                internal_value_ref_parameter_contracts(operand)
                for operand in _scalar_operation_value_operands(operation)
            )
        )
    return value.parameter_contracts


def internal_value_ref_point_dependencies(
    value: ValueRef,
) -> tuple[PointValueDependency, ...]:
    """Return point ids and types consumed anywhere in a typed value graph."""

    operation = internal_value_ref_scalar_operation(value)
    if operation is not None:
        return _merge_point_dependencies(
            *(
                internal_value_ref_point_dependencies(operand)
                for operand in _scalar_operation_value_operands(operation)
            )
        )
    return value.point_dependencies


def internal_value_ref_scalar_input_ids(value: ValueRef) -> frozenset[str]:
    """Return scalar imports remaining after authored input bindings."""

    lowered = internal_lower_value_ref(value)
    if isinstance(lowered, ComputeResultRef):
        return frozenset()
    return frozenset(plan_references(lowered).ids(PlanReferenceKind.INPUT_SCALAR))


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
    if isinstance(source, _ScalarOperationValueSource):
        return any(
            _value_ref_requires_execution(operand, seen=nested_seen)
            for operand in _scalar_operation_value_operands(source.operation)
        )
    return any(
        _value_ref_requires_execution(bound, seen=nested_seen)
        for layer in source.input_binding_layers
        for _input_id, bound in layer
    )


def internal_value_ref_is_row_dependent(value: ValueRef) -> bool:
    """Return whether a value is lexically bound by a row scope."""

    return _value_ref_is_row_dependent(value, seen=frozenset())


def _value_ref_is_row_dependent(
    value: ValueRef,
    *,
    seen: frozenset[_ValueDeclarationIdentity],
) -> bool:
    marker = internal_value_ref_declaration_identity(value)
    if marker in seen:
        return False
    nested_seen = seen | {marker}
    source = value.source
    if isinstance(source, _ModuleExportSource):
        raise ValueError(
            "cannot determine row dependencies of unresolved module export "
            f"{source.export_id!r}"
        )
    if isinstance(source, _ScalarOperationValueSource):
        return any(
            _value_ref_is_row_dependent(operand, seen=nested_seen)
            for operand in _scalar_operation_value_operands(source.operation)
        )
    if isinstance(source, _ComputeValueSource | _PointValueSource | _InputValueSource):
        return False
    return bool(free_row_references(source.expression).references) or any(
        _value_ref_is_row_dependent(bound, seen=nested_seen)
        for layer in source.input_binding_layers
        for _input_id, bound in layer
    )


def internal_lower_value_ref(value: ValueRef) -> _ValueExpression | ComputeResultRef:
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
    if isinstance(source, _ScalarOperationValueSource):
        operation = source.operation
        return BinaryScalarExpr(
            op=operation.operator,
            left=_lower_scalar_operation_operand(operation.left),
            right=_lower_scalar_operation_operand(operation.right),
        )
    if isinstance(source, _ExpressionValueSource):
        expression = source.expression
        layers = source.input_binding_layers
        if not layers:
            return expression
        from scopecat.compiler.relations.input_binding import (
            substitute_value_input_refs,
        )

        for layer in layers:
            expression = substitute_value_input_refs(
                expression,
                _LoweredValueRefInputs(dict(layer)),
            )
        return expression
    if isinstance(source, _PointValueSource):
        return point_col(source.id)
    source_id = source.id
    if isinstance(value.value_type, Scalar):
        return input_ref(source_id)
    if isinstance(value.value_type, Series):
        return input_series(source_id)
    return input_table(source_id)


def _lower_scalar_operation_operand(
    operand: ScalarOperationOperand,
) -> ScalarExpression:
    if not isinstance(operand, ValueRef):
        return as_scalar_expr(operand)
    lowered = internal_lower_value_ref(operand)
    if isinstance(lowered, ComputeResultRef):
        msg = (
            "externally dependent scalar operations require semantic graph lowering; "
            "they cannot be lowered as plan expressions"
        )
        raise TypeError(msg)
    if not isinstance(lowered, ScalarExpr):
        msg = "scalar operation operands must be scalar-shaped"
        raise TypeError(msg)
    return cast("ScalarExpression", lowered)


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


def internal_lower_table_value_ref(value: ValueRef) -> RelationExpr:
    """Lower a typed table edge at the private compiler boundary."""

    if not isinstance(value.value_type, Table):
        msg = "table expression requires a table value"
        raise TypeError(msg)
    lowered = internal_lower_value_ref(value)
    if not isinstance(lowered, RelationExpr):
        msg = "compute outputs must be connected as standalone values"
        raise TypeError(msg)
    return lowered


def internal_value_ref_from_expression(
    expression: _ValueExpression,
    value_type: ValueType,
    *,
    declaration_key: ValueDeclarationKey | None = None,
    parameter_contracts: tuple[ParameterContract, ...] = (),
    point_dependencies: tuple[PointValueDependency, ...] = (),
) -> ValueRef:
    """Construct a typed expression edge inside the authoring implementation."""

    _require_expression_shape(expression, value_type)
    return ValueRef(
        source=_ExpressionValueSource(expression=expression),
        value_type=value_type,
        declaration_key=declaration_key or ValueDeclarationKey.fresh(),
        parameter_contracts=parameter_contracts,
        point_dependencies=point_dependencies,
    )


def internal_literal_value_ref(
    value: object,
    value_type: ValueType,
    *,
    path: ValuePath,
) -> ValueRef:
    """Capture one closed literal as a typed edge without exposing raw IR."""

    from scopecat.compiler.relations.input_binding import (
        input_cell,
        series_input_value,
        table_input_value,
    )

    coerced = coerce_literal(value_type, value, path=path)
    input_name = format_value_path(path)
    expression = (
        lit(input_cell(coerced))
        if isinstance(value_type, Scalar)
        else series_input_value(input_name, coerced)
        if isinstance(value_type, Series)
        else table_input_value(input_name, coerced)
    )
    return internal_value_ref_from_expression(expression, value_type)


def internal_bind_value_ref_inputs(
    value: ValueRef,
    inputs: Mapping[str, ValueRef],
) -> ValueRef:
    """Attach one typed module-input environment without lowering the edge."""

    source = value.source
    if isinstance(source, _InputValueSource):
        selected = inputs.get(source.id)
        return value if selected is None else selected
    if isinstance(source, _ScalarOperationValueSource):
        if not inputs:
            return value
        operation = source.operation
        left = _bind_scalar_operation_operand(operation.left, inputs)
        right = _bind_scalar_operation_operand(operation.right, inputs)
        if left is operation.left and right is operation.right:
            return value
        return _rebuild_scalar_operation(
            value,
            ScalarValueOperation(
                operator=operation.operator,
                left=left,
                right=right,
            ),
        )
    if not isinstance(source, _ExpressionValueSource) or not inputs:
        return value
    layer, _unbound_input_ids = _reachable_input_bindings(
        _value_ref_unbound_input_ids(value),
        inputs,
    )
    if not layer:
        return value
    bound_values = tuple(selected for _input_id, selected in layer)
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
            internal_value_ref_parameter_contracts(value),
            *(
                internal_value_ref_parameter_contracts(selected)
                for selected in bound_values
            ),
        ),
        point_dependencies=_merge_point_dependencies(
            internal_value_ref_point_dependencies(value),
            *(
                internal_value_ref_point_dependencies(selected)
                for selected in bound_values
            ),
        ),
    )


def _bind_scalar_operation_operand(
    operand: ScalarOperationOperand,
    inputs: Mapping[str, ValueRef],
) -> ScalarOperationOperand:
    if not isinstance(operand, ValueRef):
        return operand
    return internal_bind_value_ref_inputs(operand, inputs)


def internal_value_ref_unbound_input_ids(value: ValueRef) -> frozenset[str]:
    """Return lexical input ids that remain free in one typed value edge."""

    return _value_ref_unbound_input_ids(value)


def _value_ref_unbound_input_ids(value: ValueRef) -> frozenset[str]:
    source = value.source
    if isinstance(source, _InputValueSource):
        return frozenset((source.id,))
    if isinstance(source, _ScalarOperationValueSource):
        return frozenset(
            input_id
            for operand in _scalar_operation_value_operands(source.operation)
            for input_id in _value_ref_unbound_input_ids(operand)
        )
    if not isinstance(source, _ExpressionValueSource):
        return frozenset()

    from scopecat.compiler.relations.input_binding import value_input_refs

    input_ids = frozenset(value_input_refs(source.expression))
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
    return _scalar_operation_value(
        operator=cast("ScalarOperator", operator),
        left=left,
        right=right,
        value_type=scalar_operator_result_type(
            left_type,
            right_type,
            cast("ScalarOperator", operator),
        ),
    )


def _comparison_value(left: object, right: object, operator: str) -> ValueRef:
    left_type = _scalar_operand_type(left)
    right_type = _scalar_operand_type(right)
    result_type = scalar_operator_result_type(
        left_type,
        right_type,
        cast("ScalarOperator", operator),
        left_is_null_literal=_is_null_literal(left),
        right_is_null_literal=_is_null_literal(right),
    )
    return _scalar_operation_value(
        operator=cast("ScalarOperator", operator),
        left=left,
        right=right,
        value_type=result_type,
    )


def _logical_value(left: object, right: object, operator: str) -> ValueRef:
    left_type = _scalar_operand_type(left)
    right_type = _scalar_operand_type(right)
    result_type = scalar_operator_result_type(
        left_type,
        right_type,
        cast("ScalarOperator", operator),
    )
    return _scalar_operation_value(
        operator=cast("ScalarOperator", operator),
        left=left,
        right=right,
        value_type=result_type,
    )


def _scalar_operation_value(
    *,
    operator: ScalarOperator,
    left: object,
    right: object,
    value_type: Scalar,
) -> ValueRef:
    return ValueRef(
        source=_ScalarOperationValueSource(
            operation=ScalarValueOperation(
                operator=operator,
                left=_capture_scalar_operation_operand(left),
                right=_capture_scalar_operation_operand(right),
            ),
        ),
        value_type=value_type,
    )


def _capture_scalar_operation_operand(value: object) -> ScalarOperationOperand:
    if isinstance(value, ValueRef):
        return value
    if isinstance(value, PayloadValue):
        return value
    from scopecat.authoring._frozen_values import capture_runtime_input

    try:
        captured = capture_runtime_input(value)
    except TypeError as error:
        msg = "scalar operations require typed values or closed scalar literals"
        raise TypeError(msg) from error
    return cast("FrozenScalarLiteral", captured)


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


def _is_null_literal(value: object) -> bool:
    return value is None


def _require_expression_shape(
    expression: _ValueExpression, value_type: ValueType
) -> None:
    if (
        (isinstance(expression, ScalarExpr) and isinstance(value_type, Scalar))
        or (isinstance(expression, SeriesExpr) and isinstance(value_type, Series))
        or (isinstance(expression, RelationExpr) and isinstance(value_type, Table))
    ):
        return
    msg = f"expression shape is incompatible with {describe_value_type(value_type)}"
    raise TypeError(msg)


def _rebuild_scalar_operation(
    value: ValueRef,
    operation: ScalarValueOperation,
) -> ValueRef:
    return ValueRef(
        source=_ScalarOperationValueSource(operation=operation),
        value_type=value.value_type,
        declaration_key=value.declaration_key,
        declaration_scope=value.declaration_scope,
    )


def _scalar_operation_value_operands(
    operation: ScalarValueOperation,
) -> tuple[ValueRef, ...]:
    return tuple(
        operand
        for operand in (operation.left, operation.right)
        if isinstance(operand, ValueRef)
    )
