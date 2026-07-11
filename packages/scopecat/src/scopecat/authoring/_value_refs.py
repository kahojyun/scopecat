"""Typed value edges used while composing authoring modules.

The relation expression classes still provide the executable expression tree.  A
``ValueRef`` adds the part that those trees deliberately do not carry: the
complete semantic ``ValueType`` and the identity of the input or compute node
that produced the value.  Module composition keeps these references intact and
only lowers them back to relation/compute references at the compiler boundary.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Literal, cast

from scopecat._compiler.ids import NodeId
from scopecat._compute_result import ComputeResultRef
from scopecat._relations import (
    RelationExpr,
    ScalarExpr,
    SeriesExpr,
    as_scalar_expr,
    col,
    input_ref,
    input_series,
    input_table,
)
from scopecat._scalar_operators import (
    ScalarOperator,
    require_sortable_scalar,
    scalar_operator_result_type,
)
from scopecat.authoring._parameter_contracts import (
    ParameterContract,
    merge_parameter_contracts,
)
from scopecat.authoring._value_type_compatibility import (
    describe_value_type as describe_value_type,
)
from scopecat.authoring._value_type_compatibility import (
    is_assignable as is_assignable,
)
from scopecat.authoring._value_type_compatibility import (
    literal_scalar_type as _literal_scalar_type,
)
from scopecat.authoring._value_type_compatibility import (
    require_assignable as require_assignable,
)
from scopecat.value_types import (
    Bool,
    Entity,
    Scalar,
    Series,
    Table,
    TableColumn,
    ValueType,
)

type _ValueExpression = ScalarExpr | SeriesExpr | RelationExpr
type _ValueRefSource = Literal["input", "compute", "point", "expression"]


@dataclass(frozen=True, slots=True)
class PointValueDependency:
    """One point value consumed by a typed authoring value graph."""

    id: str
    value_type: Scalar


@dataclass(frozen=True, slots=True, init=False)
class TableRow:
    """Typed row scope supplied by table callbacks.

    Row values deliberately have no public factory.  They only exist while an
    authoring callback is being evaluated, which keeps column references tied
    to the table schema that introduced their scope.
    """

    _columns: Mapping[str, TableColumn]
    _parameter_contracts: tuple[ParameterContract, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    _point_dependencies: tuple[PointValueDependency, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )

    def __init__(self) -> None:
        msg = "TableRow is a callback scope and cannot be constructed directly"
        raise TypeError(msg)

    def __getitem__(self, column_id: str) -> ValueRef:
        column = self._columns.get(column_id)
        if column is None:
            msg = f"table row has no column {column_id!r}"
            raise KeyError(msg)
        return internal_value_ref_from_expression(
            col(column_id),
            column.value_type,
            parameter_contracts=self._parameter_contracts,
            point_dependencies=self._point_dependencies,
        )

    @classmethod
    def _from_value(cls, value: ValueRef) -> TableRow:
        table_type = value.value_type
        if not isinstance(table_type, Table):
            msg = "row scope requires a table value"
            raise TypeError(msg)
        row = object.__new__(cls)
        object.__setattr__(
            row,
            "_columns",
            {column.id: column for column in table_type.columns},
        )
        object.__setattr__(
            row,
            "_parameter_contracts",
            internal_value_ref_parameter_contracts(value),
        )
        object.__setattr__(
            row,
            "_point_dependencies",
            internal_value_ref_point_dependencies(value),
        )
        return row


@dataclass(frozen=True, slots=True, init=False)
class ValueRef:
    """Opaque first-class typed edge in the public authoring value graph.

    Values are created by DSL factories such as :func:`scopecat.input` and
    :func:`scopecat.parameter`.  Their source expression and provenance are
    deliberately private compiler details.
    """

    _source_kind: _ValueRefSource = field(repr=False)
    _source_id: str | NodeId | None = field(repr=False)
    _value_type: ValueType = field(repr=False)
    _expression: _ValueExpression | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _input_binding_layers: tuple[tuple[tuple[str, ValueRef], ...], ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    _parameter_contracts: tuple[ParameterContract, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )
    _point_dependencies: tuple[PointValueDependency, ...] = field(
        default=(),
        repr=False,
        compare=False,
    )

    def __init__(self) -> None:
        msg = "ValueRef is an opaque handle; create values with scopecat DSL factories"
        raise TypeError(msg)

    @classmethod
    def _create(
        cls,
        *,
        source_kind: _ValueRefSource,
        source_id: str | NodeId | None,
        value_type: ValueType,
        expression: _ValueExpression | None = None,
        input_binding_layers: tuple[tuple[tuple[str, ValueRef], ...], ...] = (),
        parameter_contracts: tuple[ParameterContract, ...] = (),
        point_dependencies: tuple[PointValueDependency, ...] = (),
    ) -> ValueRef:
        value = object.__new__(cls)
        object.__setattr__(value, "_source_kind", source_kind)
        object.__setattr__(value, "_source_id", source_id)
        object.__setattr__(value, "_value_type", value_type)
        object.__setattr__(value, "_expression", expression)
        object.__setattr__(value, "_input_binding_layers", input_binding_layers)
        object.__setattr__(value, "_parameter_contracts", parameter_contracts)
        object.__setattr__(
            value,
            "_point_dependencies",
            _merge_point_dependencies(point_dependencies),
        )
        value._validate()
        return value

    def _validate(self) -> None:
        if self._source_kind in {"input", "compute", "point"}:
            if not self._source_id:
                msg = f"{self._source_kind} value reference requires a source id"
                raise ValueError(msg)
            if self._expression is not None:
                msg = (
                    f"{self._source_kind} value reference cannot contain an expression"
                )
                raise ValueError(msg)
            if self._input_binding_layers:
                msg = f"{self._source_kind} value reference cannot bind inputs"
                raise ValueError(msg)
            return
        if self._source_id is not None or self._expression is None:
            msg = "expression value reference requires an expression only"
            raise ValueError(msg)
        _require_expression_shape(self._expression, self._value_type)

    @property
    def value_type(self) -> ValueType:
        """The complete semantic type carried by this value edge."""

        return self._value_type

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
            parameter_contracts=self._parameter_contracts,
            point_dependencies=self._point_dependencies,
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
            parameter_contracts=self._parameter_contracts,
            point_dependencies=self._point_dependencies,
        )

    def filter(self, predicate: Callable[[TableRow], ValueRef]) -> ValueRef:
        """Filter rows using a schema-bound typed predicate callback."""

        table_type = _require_table_type(self, operation="filter")
        condition = cast(
            "object",
            predicate(
                TableRow._from_value(  # pyright: ignore[reportPrivateUsage]
                    self
                )
            ),
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
        return internal_value_ref_from_expression(
            internal_lower_table_value_ref(self).filter(
                internal_lower_scalar_value_ref(condition)
            ),
            Table(
                columns=table_type.columns,
                primary_key=table_type.primary_key,
                min_rows=0,
                max_rows=table_type.max_rows,
                allow_extra_columns=table_type.allow_extra_columns,
            ),
            parameter_contracts=merge_parameter_contracts(
                self._parameter_contracts,
                internal_value_ref_parameter_contracts(condition),
            ),
            point_dependencies=_merge_point_dependencies(
                self._point_dependencies,
                internal_value_ref_point_dependencies(condition),
            ),
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
                self._parameter_contracts,
                other._parameter_contracts,
            ),
            point_dependencies=_merge_point_dependencies(
                self._point_dependencies,
                other._point_dependencies,
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
                self._parameter_contracts,
                other._parameter_contracts,
            ),
            point_dependencies=_merge_point_dependencies(
                self._point_dependencies,
                other._point_dependencies,
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
            parameter_contracts=self._parameter_contracts,
            point_dependencies=self._point_dependencies,
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
            parameter_contracts=self._parameter_contracts,
            point_dependencies=self._point_dependencies,
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
        built = cast(
            "object",
            build(
                TableRow._from_value(  # pyright: ignore[reportPrivateUsage]
                    self
                )
            ),
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
                required=column.required,
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
        return internal_value_ref_from_expression(
            internal_lower_table_value_ref(self).with_columns(**expressions),
            Table(
                columns=(*updated, *added),
                primary_key=primary_key,
                min_rows=table_type.min_rows,
                max_rows=table_type.max_rows,
                allow_extra_columns=table_type.allow_extra_columns,
            ),
            parameter_contracts=merge_parameter_contracts(
                self._parameter_contracts,
                *(
                    internal_value_ref_parameter_contracts(value)
                    for value in columns.values()
                    if isinstance(value, ValueRef)
                ),
            ),
            point_dependencies=_merge_point_dependencies(
                self._point_dependencies,
                *(
                    internal_value_ref_point_dependencies(value)
                    for value in columns.values()
                    if isinstance(value, ValueRef)
                ),
            ),
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
            parameter_contracts=self._parameter_contracts,
            point_dependencies=self._point_dependencies,
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
    return ValueRef._create(  # pyright: ignore[reportPrivateUsage]
        source_kind="input",
        source_id=input_id,
        value_type=value_type,
    )


def internal_compute_value_ref(
    node_id: NodeId | str,
    value_type: ValueType,
    *,
    point_dependencies: tuple[PointValueDependency, ...] = (),
) -> ValueRef:
    selected_node_id = (
        node_id if isinstance(node_id, NodeId) else NodeId(local_id=node_id)
    )
    return ValueRef._create(  # pyright: ignore[reportPrivateUsage]
        source_kind="compute",
        source_id=selected_node_id,
        value_type=value_type,
        point_dependencies=_merge_point_dependencies(point_dependencies),
    )


def internal_point_value_ref(point_id: str, value_type: Scalar) -> ValueRef:
    """Create a typed value supplied by the current experiment point."""

    return ValueRef._create(  # pyright: ignore[reportPrivateUsage]
        source_kind="point",
        source_id=point_id,
        value_type=value_type,
        point_dependencies=(PointValueDependency(id=point_id, value_type=value_type),),
    )


def internal_value_ref_source_kind(value: ValueRef) -> _ValueRefSource:
    return cast(
        "_ValueRefSource",
        object.__getattribute__(value, "_source_kind"),
    )


def internal_value_ref_input_id(value: ValueRef) -> str | None:
    if internal_value_ref_source_kind(value) != "input":
        return None
    return cast("str | None", object.__getattribute__(value, "_source_id"))


def internal_value_ref_point_id(value: ValueRef) -> str | None:
    """Return the point coordinate id carried by a point value."""

    if internal_value_ref_source_kind(value) != "point":
        return None
    return cast("str | None", object.__getattribute__(value, "_source_id"))


def internal_value_ref_compute_node_id(value: ValueRef) -> NodeId | None:
    if internal_value_ref_source_kind(value) != "compute":
        return None
    return cast("NodeId", object.__getattribute__(value, "_source_id"))


def internal_scope_compute_value_ref(value: ValueRef, *scope: str) -> ValueRef:
    """Prefix compute symbols owned by one expanded module instance."""

    if not scope:
        return value
    source_kind = internal_value_ref_source_kind(value)
    if source_kind == "compute":
        return ValueRef._create(  # pyright: ignore[reportPrivateUsage]
            source_kind="compute",
            source_id=_required_compute_node_id(value).prefixed(*scope),
            value_type=value.value_type,
            parameter_contracts=internal_value_ref_parameter_contracts(value),
            point_dependencies=internal_value_ref_point_dependencies(value),
        )
    if source_kind != "expression":
        return value
    expression = cast(
        "_ValueExpression",
        object.__getattribute__(value, "_expression"),
    )
    layers = cast(
        "tuple[tuple[tuple[str, ValueRef], ...], ...]",
        object.__getattribute__(value, "_input_binding_layers"),
    )
    if not layers:
        return value
    return ValueRef._create(  # pyright: ignore[reportPrivateUsage]
        source_kind="expression",
        source_id=None,
        value_type=value.value_type,
        expression=expression,
        input_binding_layers=tuple(
            tuple(
                (input_id, internal_scope_compute_value_ref(bound, *scope))
                for input_id, bound in layer
            )
            for layer in layers
        ),
        parameter_contracts=internal_value_ref_parameter_contracts(value),
        point_dependencies=internal_value_ref_point_dependencies(value),
    )


def internal_value_ref_parameter_contracts(
    value: ValueRef,
) -> tuple[ParameterContract, ...]:
    return cast(
        "tuple[ParameterContract, ...]",
        object.__getattribute__(value, "_parameter_contracts"),
    )


def internal_value_ref_point_dependencies(
    value: ValueRef,
) -> tuple[PointValueDependency, ...]:
    """Return point ids and types consumed anywhere in a typed value graph."""

    return cast(
        "tuple[PointValueDependency, ...]",
        object.__getattribute__(value, "_point_dependencies"),
    )


def internal_lower_value_ref(value: ValueRef) -> _ValueExpression | ComputeResultRef:
    """Lower a typed edge at the private compiler boundary."""

    source_kind = internal_value_ref_source_kind(value)
    if source_kind == "compute":
        return ComputeResultRef(node_id=_required_compute_node_id(value))
    if source_kind == "expression":
        expression = cast(
            "_ValueExpression",
            object.__getattribute__(value, "_expression"),
        )
        layers = cast(
            "tuple[tuple[tuple[str, ValueRef], ...], ...]",
            object.__getattribute__(value, "_input_binding_layers"),
        )
        if not layers:
            return expression
        from scopecat.authoring._value_binding import substitute_value_input_refs

        for layer in layers:
            expression = substitute_value_input_refs(expression, dict(layer))
        return expression
    source_id = _required_string_source_id(value)
    if source_kind == "point":
        return col(source_id)
    if isinstance(value.value_type, Scalar):
        return input_ref(source_id)
    if isinstance(value.value_type, Series):
        return input_series(source_id)
    return input_table(source_id)


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
    parameter_contracts: tuple[ParameterContract, ...] = (),
    point_dependencies: tuple[PointValueDependency, ...] = (),
) -> ValueRef:
    """Construct a typed expression edge inside the authoring implementation."""

    return ValueRef._create(  # pyright: ignore[reportPrivateUsage]
        source_kind="expression",
        source_id=None,
        value_type=value_type,
        expression=expression,
        parameter_contracts=parameter_contracts,
        point_dependencies=point_dependencies,
    )


def internal_literal_value_ref(
    value: object,
    value_type: ValueType,
    *,
    path: str,
) -> ValueRef:
    """Capture one closed literal as a typed edge without exposing raw IR."""

    from scopecat.authoring._value_binding import (
        input_cell,
        literal_scalar,
        series_input_value,
        table_input_value,
    )
    from scopecat.value_validation import coerce_literal

    coerced = coerce_literal(value_type, value, path=path)
    expression = (
        literal_scalar(input_cell(coerced))
        if isinstance(value_type, Scalar)
        else series_input_value(path, coerced)
        if isinstance(value_type, Series)
        else table_input_value(path, coerced)
    )
    return internal_value_ref_from_expression(expression, value_type)


def internal_bind_value_ref_inputs(
    value: ValueRef,
    inputs: Mapping[str, ValueRef],
) -> ValueRef:
    """Attach one typed module-input environment without lowering the edge."""

    source_kind = internal_value_ref_source_kind(value)
    if source_kind == "input":
        input_id = _required_string_source_id(value)
        selected = inputs.get(input_id)
        return value if selected is None else selected
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
        object.__getattribute__(value, "_expression"),
    )
    existing_layers = cast(
        "tuple[tuple[tuple[str, ValueRef], ...], ...]",
        object.__getattribute__(value, "_input_binding_layers"),
    )
    return ValueRef._create(  # pyright: ignore[reportPrivateUsage]
        source_kind="expression",
        source_id=None,
        value_type=value.value_type,
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
    )


def _value_ref_unbound_input_ids(value: ValueRef) -> frozenset[str]:
    source_kind = internal_value_ref_source_kind(value)
    if source_kind == "input":
        return frozenset((_required_string_source_id(value),))
    if source_kind != "expression":
        return frozenset()

    from scopecat.authoring._value_binding import value_input_refs

    expression = cast(
        "_ValueExpression",
        object.__getattribute__(value, "_expression"),
    )
    input_ids = frozenset(value_input_refs(expression))
    layers = cast(
        "tuple[tuple[tuple[str, ValueRef], ...], ...]",
        object.__getattribute__(value, "_input_binding_layers"),
    )
    for layer in layers:
        _reachable, input_ids = _reachable_input_bindings(input_ids, dict(layer))
    return input_ids


def _reachable_input_bindings(
    input_ids: frozenset[str],
    inputs: Mapping[str, ValueRef],
) -> tuple[tuple[tuple[str, ValueRef], ...], frozenset[str]]:
    """Select bindings reachable from the expression's free input ids."""

    pending = list(input_ids)
    reachable: set[str] = set()
    unbound: set[str] = set()
    while pending:
        input_id = pending.pop()
        if input_id in reachable or input_id in unbound:
            continue
        selected = inputs.get(input_id)
        if selected is None:
            unbound.add(input_id)
            continue
        if (
            internal_value_ref_source_kind(selected) == "input"
            and internal_value_ref_input_id(selected) == input_id
        ):
            unbound.add(input_id)
            continue
        reachable.add(input_id)
        pending.extend(_value_ref_unbound_input_ids(selected))
    return (
        tuple(
            (input_id, selected)
            for input_id, selected in inputs.items()
            if input_id in reachable
        ),
        frozenset(unbound),
    )


def _binary_value(left: object, right: object, operator: str) -> ValueRef:
    left_type = _scalar_operand_type(left)
    right_type = _scalar_operand_type(right)
    expression = ScalarExpr(
        kind="binary",
        op=cast("Literal['+', '-', '*', '/']", operator),
        left=_scalar_operand_expression(left),
        right=_scalar_operand_expression(right),
    )
    return internal_value_ref_from_expression(
        expression,
        scalar_operator_result_type(
            left_type,
            right_type,
            cast("ScalarOperator", operator),
        ),
        parameter_contracts=_operand_parameter_contracts(left, right),
        point_dependencies=_operand_point_dependencies(left, right),
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
    expression = ScalarExpr(
        kind="binary",
        op=cast("Literal['==', '!=', '<', '<=', '>', '>=']", operator),
        left=_scalar_operand_expression(left),
        right=_scalar_operand_expression(right),
    )
    return internal_value_ref_from_expression(
        expression,
        result_type,
        parameter_contracts=_operand_parameter_contracts(left, right),
        point_dependencies=_operand_point_dependencies(left, right),
    )


def _logical_value(left: object, right: object, operator: str) -> ValueRef:
    left_type = _scalar_operand_type(left)
    right_type = _scalar_operand_type(right)
    result_type = scalar_operator_result_type(
        left_type,
        right_type,
        cast("ScalarOperator", operator),
    )
    expression = ScalarExpr(
        kind="binary",
        op=cast("Literal['and', 'or']", operator),
        left=_scalar_operand_expression(left),
        right=_scalar_operand_expression(right),
    )
    return internal_value_ref_from_expression(
        expression,
        result_type,
        parameter_contracts=_operand_parameter_contracts(left, right),
        point_dependencies=_operand_point_dependencies(left, right),
    )


def _operand_parameter_contracts(
    *values: object,
) -> tuple[ParameterContract, ...]:
    return merge_parameter_contracts(
        *(
            internal_value_ref_parameter_contracts(value)
            for value in values
            if isinstance(value, ValueRef)
        )
    )


def _operand_point_dependencies(
    *values: object,
) -> tuple[PointValueDependency, ...]:
    return _merge_point_dependencies(
        *(
            internal_value_ref_point_dependencies(value)
            for value in values
            if isinstance(value, ValueRef)
        )
    )


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


def _scalar_operand_expression(value: object) -> ScalarExpr:
    if isinstance(value, ValueRef):
        return internal_lower_scalar_value_ref(value)
    from scopecat.authoring._frozen_values import freeze_runtime_input
    from scopecat.models.value import PayloadValue

    if isinstance(value, PayloadValue):
        return as_scalar_expr(value.model_copy())
    try:
        captured = freeze_runtime_input(value)
    except AssertionError as error:
        msg = "scalar operations require typed values or closed scalar literals"
        raise TypeError(msg) from error
    return as_scalar_expr(captured)


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


def _required_string_source_id(value_ref: ValueRef) -> str:
    source_id = cast(
        "str | NodeId | None",
        object.__getattribute__(value_ref, "_source_id"),
    )
    if not isinstance(source_id, str):
        msg = "value reference string source id is required"
        raise ValueError(msg)
    return source_id


def _required_compute_node_id(value_ref: ValueRef) -> NodeId:
    source_id = cast(
        "str | NodeId | None",
        object.__getattribute__(value_ref, "_source_id"),
    )
    if not isinstance(source_id, NodeId):
        msg = "compute value reference node id is required"
        raise ValueError(msg)
    return source_id


__all__ = [
    "TableRow",
    "ValueRef",
]
