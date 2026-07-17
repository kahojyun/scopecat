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
from typing import TYPE_CHECKING, Literal, cast, override
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
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
    col,
    input_ref,
    input_series,
    input_table,
    point_col,
)
from scopecat.compiler.relations.operators import (
    ScalarOperator,
    require_sortable_scalar,
    scalar_operator_result_type,
)
from scopecat.compiler.semantic.availability import (
    ValueAvailability,
    ValueRate,
    ValueStage,
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
    Bool,
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
type _ValueRefSource = Literal[
    "input",
    "compute",
    "point",
    "expression",
    "module_export",
    "scalar_operation",
]

type FrozenScalarLiteral = (
    Quantity | EntityRef | PayloadValue | str | int | float | bool | None
)
type ScalarOperationOperand = ValueRef | FrozenScalarLiteral


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

    def __post_init__(self) -> None:
        if not self.export_id:
            msg = "module export id must be non-empty"
            raise ValueError(msg)


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
    free_point_dependencies: tuple[PointValueDependency, ...]

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
        object.__setattr__(
            self,
            "free_point_dependencies",
            internal_value_ref_free_point_dependencies(value),
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
            free_point_dependencies=self.free_point_dependencies,
        )


_EMPTY_BOUND_POINT_INPUT_IDS: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True, eq=False, repr=False)
class ValueRef:
    """Opaque first-class typed edge in the public authoring value graph.

    Values are created by DSL factories such as :func:`scopecat.input` and
    :func:`scopecat.parameter`.  Their source expression and provenance are
    compiler-facing semantic state.
    """

    source_kind: _ValueRefSource
    source_id: str | SymbolId | _ModuleExportSource | ScalarValueOperation | None
    value_type: ValueType
    declaration_key: ValueDeclarationKey = field(
        default_factory=ValueDeclarationKey.fresh
    )
    declaration_scope: tuple[str, ...] = ()
    expression: _ValueExpression | None = None
    operation_origin: tuple[object, ...] = ()
    input_binding_layers: tuple[tuple[tuple[str, ValueRef], ...], ...] = ()
    parameter_contracts: tuple[ParameterContract, ...] = ()
    point_dependencies: tuple[PointValueDependency, ...] = ()
    free_point_dependencies: tuple[PointValueDependency, ...] = ()
    bound_point_input_ids: frozenset[str] = _EMPTY_BOUND_POINT_INPUT_IDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "point_dependencies",
            _merge_point_dependencies(self.point_dependencies),
        )
        object.__setattr__(
            self,
            "free_point_dependencies",
            _merge_point_dependencies(self.free_point_dependencies),
        )
        object.__setattr__(
            self,
            "bound_point_input_ids",
            frozenset(self.bound_point_input_ids),
        )
        self._validate()

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

    def _validate(self) -> None:
        if any(not item for item in self.declaration_scope):
            msg = "value declaration scope components must be non-empty"
            raise ValueError(msg)
        if self.source_kind in {"input", "compute", "point"}:
            if not self.source_id:
                msg = f"{self.source_kind} value reference requires a source id"
                raise ValueError(msg)
            if self.expression is not None:
                msg = f"{self.source_kind} value reference cannot contain an expression"
                raise ValueError(msg)
            if self.input_binding_layers:
                msg = f"{self.source_kind} value reference cannot bind inputs"
                raise ValueError(msg)
            if self.source_kind != "compute" and self.operation_origin:
                msg = f"{self.source_kind} value reference cannot own a compute"
                raise ValueError(msg)
            return
        if self.source_kind == "module_export":
            if not isinstance(self.source_id, _ModuleExportSource):
                msg = "module export value reference requires an export source"
                raise ValueError(msg)
            if self.expression is not None:
                msg = "module export value reference cannot contain an expression"
                raise ValueError(msg)
            if self.input_binding_layers:
                msg = "module export value reference cannot bind inputs"
                raise ValueError(msg)
            if self.operation_origin:
                msg = "module export value reference cannot own a compute"
                raise ValueError(msg)
            return
        if self.source_kind == "scalar_operation":
            if not isinstance(self.source_id, ScalarValueOperation):
                msg = "scalar operation value reference requires an operation"
                raise ValueError(msg)
            if not isinstance(self.value_type, Scalar):
                msg = "scalar operation value reference must be scalar-shaped"
                raise TypeError(msg)
            if self.expression is not None:
                msg = "scalar operation value reference cannot contain an expression"
                raise ValueError(msg)
            if self.input_binding_layers:
                msg = "scalar operation value reference cannot bind expression inputs"
                raise ValueError(msg)
            if self.operation_origin:
                msg = "scalar operation value reference cannot own a compute"
                raise ValueError(msg)
            if self.parameter_contracts or self.point_dependencies:
                msg = "scalar operation provenance must be derived from its operands"
                raise ValueError(msg)
            return
        if (
            self.source_id is not None
            or self.expression is None
            or self.operation_origin
        ):
            msg = "expression value reference requires an expression only"
            raise ValueError(msg)
        _require_expression_shape(self.expression, self.value_type)

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

    def column(self, column_id: str) -> ValueRef:
        """Return a typed series projection from a table expression."""

        table_type = self.value_type
        if not isinstance(table_type, Table):
            msg = "column projection requires a table value"
            raise TypeError(msg)
        columns = {column.id: column for column in table_type.columns}
        column = columns.get(column_id)
        if column is None:
            msg = f"table value has no column {column_id!r}"
            raise KeyError(msg)
        expression = internal_lower_table_value_ref(self)
        return internal_value_ref_from_expression(
            expression.column(column_id),
            Series(column.value_type),
            parameter_contracts=self.parameter_contracts,
            point_dependencies=self.point_dependencies,
            free_point_dependencies=internal_value_ref_free_point_dependencies(self),
            bound_point_input_ids=internal_value_ref_bound_point_input_ids(self),
        )

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
            free_point_dependencies=internal_value_ref_free_point_dependencies(self),
            bound_point_input_ids=internal_value_ref_bound_point_input_ids(self),
        )

    def filter(self, predicate: Callable[[TableRow], ValueRef]) -> ValueRef:
        """Filter rows using a schema-bound typed predicate callback."""

        table_type = _require_table_type(self, operation="filter")
        declaration_key = ValueDeclarationKey.fresh()
        row = TableRow(
            self,
            scope_id=RowScopeId(SymbolId(local_id=f"row_{declaration_key.value.hex}")),
        )
        condition = cast(
            "object",
            predicate(row),
        )
        if not isinstance(condition, ValueRef):
            msg = "filter callback must return a typed value"
            raise TypeError(msg)
        condition_type = condition.value_type
        if not isinstance(condition_type, Scalar) or not isinstance(
            condition_type.atom, Bool
        ):
            msg = "filter callback must return a bool scalar"
            raise TypeError(msg)
        expression = internal_lower_table_value_ref(self).filter(
            internal_lower_scalar_value_ref(condition),
            row_scope_id=row.scope_id,
        )
        verify_plan_scopes(expression)
        return internal_value_ref_from_expression(
            expression,
            Table(
                columns=table_type.columns,
                primary_key=table_type.primary_key,
                min_rows=0,
                max_rows=table_type.max_rows,
                allow_extra_columns=table_type.allow_extra_columns,
            ),
            parameter_contracts=merge_parameter_contracts(
                self.parameter_contracts,
                internal_value_ref_parameter_contracts(condition),
            ),
            point_dependencies=_merge_point_dependencies(
                self.point_dependencies,
                internal_value_ref_point_dependencies(condition),
            ),
            free_point_dependencies=_merge_point_dependencies(
                internal_value_ref_free_point_dependencies(self),
                internal_value_ref_free_point_dependencies(condition),
            ),
            bound_point_input_ids=frozenset(
                {
                    *internal_value_ref_bound_point_input_ids(self),
                    *internal_value_ref_bound_point_input_ids(condition),
                }
            ),
            declaration_key=declaration_key,
        )

    def join(
        self,
        other: ValueRef,
        *,
        on: Mapping[str, str],
    ) -> ValueRef:
        """Join two typed tables by explicit left-to-right column ids."""

        left_type = _require_table_type(self, operation="join")
        right_type = _require_table_type(other, operation="join")
        left_columns = {column.id: column for column in left_type.columns}
        right_columns = {column.id: column for column in right_type.columns}
        selected_on = cast("Mapping[object, object]", on)
        if not selected_on:
            msg = "join requires at least one key column"
            raise ValueError(msg)
        normalized_on: dict[str, str] = {}
        for left_id, right_id in selected_on.items():
            if not isinstance(left_id, str) or not left_id:
                msg = "join left column ids must be non-empty strings"
                raise TypeError(msg)
            if not isinstance(right_id, str) or not right_id:
                msg = "join right column ids must be non-empty strings"
                raise TypeError(msg)
            if left_id not in left_columns:
                msg = f"left table has no join column {left_id!r}"
                raise KeyError(msg)
            if right_id not in right_columns:
                msg = f"right table has no join column {right_id!r}"
                raise KeyError(msg)
            if right_id in normalized_on.values():
                msg = f"join right column {right_id!r} is mapped more than once"
                raise ValueError(msg)
            left_column = left_columns[left_id]
            right_column = right_columns[right_id]
            _require_join_key_column(left_column, side="left")
            _require_join_key_column(right_column, side="right")
            scalar_operator_result_type(
                left_column.value_type,
                right_column.value_type,
                "==",
            )
            normalized_on[left_id] = right_id
        allowed_shared = {
            left_id
            for left_id, right_id in normalized_on.items()
            if left_id == right_id
        }
        _require_no_column_conflicts(
            left_type,
            right_type,
            operation="join",
            allowed_shared=allowed_shared,
        )
        return internal_value_ref_from_expression(
            internal_lower_table_value_ref(self).join(
                internal_lower_table_value_ref(other),
                on=normalized_on,
            ),
            _combined_table_type(left_type, right_type, minimum=0),
            parameter_contracts=merge_parameter_contracts(
                self.parameter_contracts,
                other.parameter_contracts,
            ),
            point_dependencies=_merge_point_dependencies(
                self.point_dependencies,
                other.point_dependencies,
            ),
            free_point_dependencies=_merge_point_dependencies(
                internal_value_ref_free_point_dependencies(self),
                internal_value_ref_free_point_dependencies(other),
            ),
            bound_point_input_ids=frozenset(
                {
                    *internal_value_ref_bound_point_input_ids(self),
                    *internal_value_ref_bound_point_input_ids(other),
                }
            ),
        )

    def cross(self, other: ValueRef) -> ValueRef:
        """Take the typed Cartesian product of two tables."""

        left_type = _require_table_type(self, operation="cross")
        right_type = _require_table_type(other, operation="cross")
        _require_no_column_conflicts(
            left_type,
            right_type,
            operation="cross",
        )
        return internal_value_ref_from_expression(
            internal_lower_table_value_ref(self).cross(
                internal_lower_table_value_ref(other)
            ),
            _combined_table_type(
                left_type,
                right_type,
                minimum=left_type.min_rows * right_type.min_rows,
            ),
            parameter_contracts=merge_parameter_contracts(
                self.parameter_contracts,
                other.parameter_contracts,
            ),
            point_dependencies=_merge_point_dependencies(
                self.point_dependencies,
                other.point_dependencies,
            ),
            free_point_dependencies=_merge_point_dependencies(
                internal_value_ref_free_point_dependencies(self),
                internal_value_ref_free_point_dependencies(other),
            ),
            bound_point_input_ids=frozenset(
                {
                    *internal_value_ref_bound_point_input_ids(self),
                    *internal_value_ref_bound_point_input_ids(other),
                }
            ),
        )

    def sort(self, *column_ids: str) -> ValueRef:
        """Sort a typed table by one or more declared columns."""

        table_type = _require_table_type(self, operation="sort")
        if not column_ids:
            msg = "sort requires at least one column"
            raise ValueError(msg)
        columns = {column.id: column for column in table_type.columns}
        missing = [column_id for column_id in column_ids if column_id not in columns]
        if missing:
            msg = "table value has no columns: " + ", ".join(missing)
            raise KeyError(msg)
        for column_id in column_ids:
            column = columns[column_id]
            if not column.required:
                msg = f"sort column {column_id!r} must be required"
                raise TypeError(msg)
            require_sortable_scalar(column.value_type, column_id=column_id)
        return internal_value_ref_from_expression(
            internal_lower_table_value_ref(self).sort(*column_ids),
            table_type,
            parameter_contracts=self.parameter_contracts,
            point_dependencies=self.point_dependencies,
            free_point_dependencies=internal_value_ref_free_point_dependencies(self),
            bound_point_input_ids=internal_value_ref_bound_point_input_ids(self),
        )

    def limit(self, count: int) -> ValueRef:
        """Limit a typed table while retaining its column schema."""

        table_type = _require_table_type(self, operation="limit")
        if isinstance(count, bool):
            msg = "table limit must be an integer"
            raise TypeError(msg)
        if count < 0:
            msg = "table limit must be non-negative"
            raise ValueError(msg)
        maximum = (
            count if table_type.max_rows is None else min(count, table_type.max_rows)
        )
        return internal_value_ref_from_expression(
            internal_lower_table_value_ref(self).limit(count),
            Table(
                columns=table_type.columns,
                primary_key=table_type.primary_key,
                min_rows=min(count, table_type.min_rows),
                max_rows=maximum,
                allow_extra_columns=table_type.allow_extra_columns,
            ),
            parameter_contracts=self.parameter_contracts,
            point_dependencies=self.point_dependencies,
            free_point_dependencies=internal_value_ref_free_point_dependencies(self),
            bound_point_input_ids=internal_value_ref_bound_point_input_ids(self),
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
            free_point_dependencies=_merge_point_dependencies(
                internal_value_ref_free_point_dependencies(self),
                *(
                    internal_value_ref_free_point_dependencies(value)
                    for value in columns.values()
                    if isinstance(value, ValueRef)
                ),
            ),
            bound_point_input_ids=frozenset(
                {
                    *internal_value_ref_bound_point_input_ids(self),
                    *(
                        input_id
                        for value in columns.values()
                        if isinstance(value, ValueRef)
                        for input_id in internal_value_ref_bound_point_input_ids(value)
                    ),
                }
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
            free_point_dependencies=internal_value_ref_free_point_dependencies(self),
            bound_point_input_ids=internal_value_ref_bound_point_input_ids(self),
        )


def _require_table_type(value: ValueRef, *, operation: str) -> Table:
    value_type = value.value_type
    if not isinstance(value_type, Table):
        msg = f"{operation} requires table values"
        raise TypeError(msg)
    return value_type


def _require_join_key_column(column: TableColumn, *, side: str) -> None:
    if not column.required or column.value_type.nullable:
        msg = f"{side} join column {column.id!r} must be required and non-nullable"
        raise TypeError(msg)


def _require_no_column_conflicts(
    left: Table,
    right: Table,
    *,
    operation: str,
    allowed_shared: set[str] | None = None,
) -> None:
    shared = {column.id for column in left.columns} & {
        column.id for column in right.columns
    }
    conflicts = sorted(shared - (allowed_shared or set()))
    if conflicts:
        msg = f"{operation} has conflicting columns: {', '.join(conflicts)}"
        raise ValueError(msg)


def _combined_table_type(
    left: Table,
    right: Table,
    *,
    minimum: int,
) -> Table:
    left_ids = {column.id for column in left.columns}
    columns = (
        *left.columns,
        *(column for column in right.columns if column.id not in left_ids),
    )
    primary_key = (
        tuple(dict.fromkeys((*left.primary_key, *right.primary_key)))
        if left.primary_key and right.primary_key
        else ()
    )
    maximum = (
        None
        if left.max_rows is None or right.max_rows is None
        else left.max_rows * right.max_rows
    )
    return Table(
        columns=columns,
        primary_key=primary_key,
        min_rows=minimum,
        max_rows=maximum,
        allow_extra_columns=(left.allow_extra_columns or right.allow_extra_columns),
    )


def internal_input_value_ref(input_id: str, value_type: ValueType) -> ValueRef:
    return ValueRef(
        source_kind="input",
        source_id=input_id,
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
        source_kind="compute",
        source_id=selected_operation_id,
        value_type=value_type,
        operation_origin=origin,
        point_dependencies=_merge_point_dependencies(point_dependencies),
        free_point_dependencies=_merge_point_dependencies(point_dependencies),
    )


def internal_point_value_ref(point_id: str, value_type: Scalar) -> ValueRef:
    """Create a typed value supplied by the current experiment point."""

    point_dependencies = (PointValueDependency(id=point_id, value_type=value_type),)
    return ValueRef(
        source_kind="point",
        source_id=point_id,
        value_type=value_type,
        point_dependencies=point_dependencies,
        free_point_dependencies=point_dependencies,
    )


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
        source_kind="module_export",
        source_id=_ModuleExportSource(
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

    if value.source_kind != "scalar_operation":
        return None
    return _required_scalar_operation(value)


def internal_value_ref_input_id(value: ValueRef) -> str | None:
    if value.source_kind != "input":
        return None
    return cast("str | None", value.source_id)


def internal_value_ref_point_id(value: ValueRef) -> str | None:
    """Return the point coordinate id carried by a point value."""

    if value.source_kind != "point":
        return None
    return cast("str | None", value.source_id)


def internal_value_ref_operation_id(value: ValueRef) -> SymbolId | None:
    if value.source_kind != "compute":
        return None
    return cast("SymbolId", value.source_id)


def internal_value_ref_module_export(
    value: ValueRef,
) -> tuple[InvocationKey, str] | None:
    """Return the invocation and export identity for a direct export use."""

    if value.source_kind != "module_export":
        return None
    source = _required_module_export_source(value)
    return source.invocation_key, source.export_id


def internal_value_ref_has_module_export(value: ValueRef) -> bool:
    """Return whether an export use occurs anywhere in a typed value edge."""

    return _first_module_export(value, seen=frozenset()) is not None


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
    if value.source_kind != "expression":
        return None
    for layer in _value_ref_input_binding_layers(value):
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
    source_kind = value.source_kind
    if source_kind not in {"expression", "scalar_operation"}:
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
    if source_kind == "scalar_operation":
        operation = _required_scalar_operation(value)
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

    layers = _value_ref_input_binding_layers(value)
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
    expression = cast(
        "_ValueExpression",
        value.expression,
    )
    return ValueRef(
        source_kind="expression",
        source_id=None,
        value_type=value.value_type,
        declaration_key=value.declaration_key,
        declaration_scope=value.declaration_scope,
        expression=expression,
        input_binding_layers=transformed_layers,
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
        free_point_dependencies=_merge_point_dependencies(
            internal_value_ref_free_point_dependencies(value),
            *(
                internal_value_ref_free_point_dependencies(bound)
                for bound in transformed_values
            ),
        ),
        bound_point_input_ids=frozenset(
            {
                *internal_value_ref_bound_point_input_ids(value),
                *(
                    input_id
                    for bound in transformed_values
                    for input_id in internal_value_ref_bound_point_input_ids(bound)
                ),
            }
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
    source_kind = value.source_kind
    if source_kind == "module_export":
        # An export is an interface use owned by its InvocationKey, not a
        # declaration introduced by the surrounding instance scope.
        return value
    declaration_scope = (
        *scope,
        *value.declaration_scope,
    )
    if source_kind == "compute":
        return ValueRef(
            source_kind="compute",
            source_id=_required_operation_id(value).prefixed(*scope),
            value_type=value.value_type,
            declaration_key=value.declaration_key,
            declaration_scope=declaration_scope,
            operation_origin=(
                *origin,
                *value.operation_origin,
            ),
            parameter_contracts=internal_value_ref_parameter_contracts(value),
            point_dependencies=internal_value_ref_point_dependencies(value),
            free_point_dependencies=internal_value_ref_free_point_dependencies(value),
            bound_point_input_ids=internal_value_ref_bound_point_input_ids(value),
        )
    if source_kind == "scalar_operation":
        operation = _required_scalar_operation(value)
        return ValueRef(
            source_kind="scalar_operation",
            source_id=ScalarValueOperation(
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
            value_type=value.value_type,
            declaration_key=value.declaration_key,
            declaration_scope=declaration_scope,
        )
    if source_kind == "expression":
        expression = prefix_plan_row_scopes(
            _required_value_expression(value),
            *scope,
        )
        layers = _value_ref_input_binding_layers(value)
        return ValueRef(
            source_kind="expression",
            source_id=None,
            value_type=value.value_type,
            declaration_key=value.declaration_key,
            declaration_scope=declaration_scope,
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
            parameter_contracts=internal_value_ref_parameter_contracts(value),
            point_dependencies=internal_value_ref_point_dependencies(value),
            free_point_dependencies=internal_value_ref_free_point_dependencies(value),
            bound_point_input_ids=internal_value_ref_bound_point_input_ids(value),
        )
    return ValueRef(
        source_kind=source_kind,
        source_id=_value_ref_source_id(value),
        value_type=value.value_type,
        declaration_key=value.declaration_key,
        declaration_scope=declaration_scope,
        parameter_contracts=internal_value_ref_parameter_contracts(value),
        point_dependencies=internal_value_ref_point_dependencies(value),
        free_point_dependencies=internal_value_ref_free_point_dependencies(value),
        bound_point_input_ids=internal_value_ref_bound_point_input_ids(value),
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


def internal_value_ref_free_point_dependencies(
    value: ValueRef,
) -> tuple[PointValueDependency, ...]:
    """Return point requirements not closed by a point-domain binder."""

    operation = internal_value_ref_scalar_operation(value)
    if operation is not None:
        return _merge_point_dependencies(
            *(
                internal_value_ref_free_point_dependencies(operand)
                for operand in _scalar_operation_value_operands(operation)
            )
        )
    return value.free_point_dependencies


def internal_value_ref_bound_point_input_ids(value: ValueRef) -> frozenset[str]:
    """Return scalar input ids closed by point-domain binders in this value."""

    operation = internal_value_ref_scalar_operation(value)
    if operation is not None:
        return frozenset(
            input_id
            for operand in _scalar_operation_value_operands(operation)
            for input_id in internal_value_ref_bound_point_input_ids(operand)
        )
    return value.bound_point_input_ids


def internal_value_ref_free_point_input_ids(value: ValueRef) -> frozenset[str]:
    """Return scalar imports that would become external point references."""

    lowered = internal_lower_value_ref(value)
    if isinstance(lowered, ComputeResultRef):
        return frozenset()
    input_ids = frozenset(plan_references(lowered).ids(PlanReferenceKind.INPUT_SCALAR))
    return input_ids - internal_value_ref_bound_point_input_ids(value)


def internal_value_ref_availability(value: ValueRef) -> ValueAvailability:
    """Return the stage and rate of a complete, possibly bound value graph."""

    return _value_ref_availability(value, seen=frozenset())


def _value_ref_availability(
    value: ValueRef,
    *,
    seen: frozenset[_ValueDeclarationIdentity],
) -> ValueAvailability:
    marker = internal_value_ref_declaration_identity(value)
    if marker in seen:
        return ValueAvailability(ValueStage.PLAN, ValueRate.RUN)
    nested_seen = seen | {marker}
    source_kind = value.source_kind
    if source_kind == "compute":
        return ValueAvailability(ValueStage.EXECUTE, ValueRate.POINT)
    if source_kind == "point":
        return ValueAvailability(ValueStage.PLAN, ValueRate.POINT)
    if source_kind == "input":
        return ValueAvailability(ValueStage.PLAN, ValueRate.RUN)
    if source_kind == "module_export":
        _invocation_key, export_id = _required_module_export_identity(value)
        msg = f"cannot determine availability of unresolved module export {export_id!r}"
        raise ValueError(msg)
    if source_kind == "scalar_operation":
        return ValueAvailability.combined(
            *(
                _value_ref_availability(operand, seen=nested_seen)
                for operand in _scalar_operation_value_operands(
                    _required_scalar_operation(value)
                )
            )
        )

    expression = (
        _required_value_expression(value) if source_kind == "expression" else None
    )
    row_dependent = expression is not None and bool(
        free_row_references(expression).references
    )
    availability = ValueAvailability(
        ValueStage.PLAN,
        (
            ValueRate.ROW
            if row_dependent
            else ValueRate.POINT
            if internal_value_ref_point_dependencies(value)
            else ValueRate.RUN
        ),
    )
    layers = value.input_binding_layers
    return ValueAvailability.combined(
        availability,
        *(
            _value_ref_availability(bound, seen=nested_seen)
            for layer in layers
            for _input_id, bound in layer
        ),
    )


def internal_lower_value_ref(value: ValueRef) -> _ValueExpression | ComputeResultRef:
    """Lower a typed edge at the private compiler boundary."""

    source_kind = value.source_kind
    if source_kind == "compute":
        operation_id = OperationId(_required_operation_id(value))
        return ComputeResultRef(value_id=operation_result_id(operation_id, "result"))
    if source_kind == "module_export":
        _invocation_key, export_id = _required_module_export_identity(value)
        msg = (
            f"cannot lower unresolved module export {export_id!r}; "
            "module elaboration must resolve exports first"
        )
        raise ValueError(msg)
    if source_kind == "scalar_operation":
        operation = _required_scalar_operation(value)
        return ScalarExpr(
            kind="binary",
            op=operation.operator,
            left=_lower_scalar_operation_operand(operation.left),
            right=_lower_scalar_operation_operand(operation.right),
        )
    if source_kind == "expression":
        expression = cast(
            "_ValueExpression",
            value.expression,
        )
        layers = value.input_binding_layers
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
    source_id = _required_string_source_id(value)
    if source_kind == "point":
        return point_col(source_id)
    if isinstance(value.value_type, Scalar):
        return input_ref(source_id)
    if isinstance(value.value_type, Series):
        return input_series(source_id)
    return input_table(source_id)


def _lower_scalar_operation_operand(
    operand: ScalarOperationOperand,
) -> ScalarExpr:
    if not isinstance(operand, ValueRef):
        return as_scalar_expr(operand)
    lowered = internal_lower_value_ref(operand)
    if isinstance(lowered, ComputeResultRef):
        msg = (
            "execute-stage scalar operations require semantic graph lowering; "
            "they cannot be lowered as plan expressions"
        )
        raise TypeError(msg)
    if not isinstance(lowered, ScalarExpr):
        msg = "scalar operation operands must be scalar-shaped"
        raise TypeError(msg)
    return lowered


def internal_lower_scalar_value_ref(value: ValueRef) -> ScalarExpr:
    """Lower a typed scalar edge at the private compiler boundary."""

    if not isinstance(value.value_type, Scalar):
        msg = "scalar expression requires a scalar value"
        raise TypeError(msg)
    lowered = internal_lower_value_ref(value)
    if not isinstance(lowered, ScalarExpr):
        msg = "compute outputs must be connected as standalone values"
        raise TypeError(msg)
    return lowered


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
    free_point_dependencies: tuple[PointValueDependency, ...] | None = None,
    bound_point_input_ids: frozenset[str] = _EMPTY_BOUND_POINT_INPUT_IDS,
) -> ValueRef:
    """Construct a typed expression edge inside the authoring implementation."""

    return ValueRef(
        source_kind="expression",
        source_id=None,
        value_type=value_type,
        declaration_key=declaration_key or ValueDeclarationKey.fresh(),
        expression=expression,
        parameter_contracts=parameter_contracts,
        point_dependencies=point_dependencies,
        free_point_dependencies=(
            point_dependencies
            if free_point_dependencies is None
            else free_point_dependencies
        ),
        bound_point_input_ids=bound_point_input_ids,
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
        literal_scalar,
        series_input_value,
        table_input_value,
    )

    coerced = coerce_literal(value_type, value, path=path)
    input_name = format_value_path(path)
    expression = (
        literal_scalar(input_cell(coerced))
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

    source_kind = value.source_kind
    if source_kind == "input":
        input_id = _required_string_source_id(value)
        selected = inputs.get(input_id)
        return value if selected is None else selected
    if source_kind == "scalar_operation":
        if not inputs:
            return value
        operation = _required_scalar_operation(value)
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
    if source_kind != "expression" or not inputs:
        return value
    layer, _unbound_input_ids = _reachable_input_bindings(
        _value_ref_unbound_input_ids(value),
        inputs,
    )
    if not layer:
        return value
    bound_values = tuple(selected for _input_id, selected in layer)
    expression = cast(
        "_ValueExpression",
        value.expression,
    )
    existing_layers = value.input_binding_layers
    return ValueRef(
        source_kind="expression",
        source_id=None,
        value_type=value.value_type,
        declaration_key=value.declaration_key,
        declaration_scope=value.declaration_scope,
        expression=expression,
        input_binding_layers=(*existing_layers, layer),
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
        free_point_dependencies=_merge_point_dependencies(
            internal_value_ref_free_point_dependencies(value),
            *(
                internal_value_ref_free_point_dependencies(selected)
                for selected in bound_values
            ),
        ),
        bound_point_input_ids=frozenset(
            {
                *internal_value_ref_bound_point_input_ids(value),
                *(
                    input_id
                    for selected in bound_values
                    for input_id in internal_value_ref_bound_point_input_ids(selected)
                ),
            }
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
    source_kind = value.source_kind
    if source_kind == "input":
        return frozenset((_required_string_source_id(value),))
    if source_kind == "scalar_operation":
        return frozenset(
            input_id
            for operand in _scalar_operation_value_operands(
                _required_scalar_operation(value)
            )
            for input_id in _value_ref_unbound_input_ids(operand)
        )
    if source_kind != "expression":
        return frozenset()

    from scopecat.compiler.relations.input_binding import value_input_refs

    expression = cast(
        "_ValueExpression",
        value.expression,
    )
    input_ids = frozenset(value_input_refs(expression))
    layers = value.input_binding_layers
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
        source_kind="scalar_operation",
        source_id=ScalarValueOperation(
            operator=operator,
            left=_capture_scalar_operation_operand(left),
            right=_capture_scalar_operation_operand(right),
        ),
        value_type=value_type,
    )


def _capture_scalar_operation_operand(value: object) -> ScalarOperationOperand:
    if isinstance(value, ValueRef):
        return value
    if isinstance(value, PayloadValue):
        return value.model_copy()
    from scopecat.authoring._frozen_values import freeze_runtime_input

    try:
        captured = freeze_runtime_input(value)
    except AssertionError as error:
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
        source_kind="scalar_operation",
        source_id=operation,
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


def _value_ref_source_id(
    value_ref: ValueRef,
) -> str | SymbolId | _ModuleExportSource | ScalarValueOperation | None:
    return value_ref.source_id


def _required_value_expression(value_ref: ValueRef) -> _ValueExpression:
    expression = value_ref.expression
    if expression is None:
        msg = "value reference expression is required"
        raise ValueError(msg)
    return expression


def _required_string_source_id(value_ref: ValueRef) -> str:
    source_id = _value_ref_source_id(value_ref)
    if not isinstance(source_id, str):
        msg = "value reference string source id is required"
        raise ValueError(msg)
    return source_id


def _required_operation_id(value_ref: ValueRef) -> SymbolId:
    source_id = _value_ref_source_id(value_ref)
    if not isinstance(source_id, SymbolId):
        msg = "compute value reference operation id is required"
        raise ValueError(msg)
    return source_id


def _required_module_export_source(value_ref: ValueRef) -> _ModuleExportSource:
    source_id = _value_ref_source_id(value_ref)
    if not isinstance(source_id, _ModuleExportSource):
        msg = "value reference module export source is required"
        raise ValueError(msg)
    return source_id


def _required_scalar_operation(value_ref: ValueRef) -> ScalarValueOperation:
    source_id = _value_ref_source_id(value_ref)
    if not isinstance(source_id, ScalarValueOperation):
        msg = "value reference scalar operation is required"
        raise ValueError(msg)
    return source_id


def _required_module_export_identity(
    value_ref: ValueRef,
) -> tuple[InvocationKey, str]:
    source = _required_module_export_source(value_ref)
    return source.invocation_key, source.export_id


def _value_ref_input_binding_layers(
    value_ref: ValueRef,
) -> tuple[tuple[tuple[str, ValueRef], ...], ...]:
    return value_ref.input_binding_layers
