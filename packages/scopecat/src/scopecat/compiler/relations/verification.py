"""Static type and schema verification for relation plans.

The relation AST deliberately remains an easy-to-author data model.  This
module turns that model into a proof-carrying plan before compiler or runtime
code may rely on its shape.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from scopecat.compiler.relations.analysis import (
    PlanNode,
    PlanReferenceKind,
    PlanReferences,
    RelationPlanBinderError,
    RelationPlanScopeError,
    free_row_references,
    plan_references,
    verify_plan_scopes,
)
from scopecat.compiler.relations.model import (
    BinaryScalarExpr,
    ColumnScalarExpr,
    FilterRelationExpr,
    InputRelationExpr,
    InputScalarExpr,
    InputSeriesExpr,
    LiteralRowsRelationExpr,
    LiteralScalarExpr,
    ParameterLookupScalarExpr,
    ParameterLookupUse,
    ParameterScalarExpr,
    ParameterSeriesExpr,
    PointColumnScalarExpr,
    RelationEntitiesSeriesExpr,
    RelationExpr,
    RelationExpression,
    RowScopeId,
    ScalarExpr,
    ScalarExpression,
    SelectRelationExpr,
    SeriesExpr,
    SeriesExpression,
    TableRelationExpr,
    ValuesSeriesExpr,
    WithColumnsRelationExpr,
)
from scopecat.compiler.relations.operators import scalar_operator_result_type
from scopecat.kernel.units import unit_kind
from scopecat.kernel.value_type_compatibility import is_assignable, literal_scalar_type
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Quantity,
    Record,
    RecordField,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
    ValueType,
)
from scopecat.kernel.value_validation import ValueValidationError, validate_literal
from scopecat.records.parameter import Quantity as QuantityValue

type PlanPathItem = str | int
type PlanPath = tuple[PlanPathItem, ...]


def _empty_value_bindings() -> dict[str, ValueType]:
    return {}


def _empty_row_bindings() -> dict[RowScopeId, RowType]:
    return {}


@dataclass(frozen=True, slots=True)
class RowType:
    """The structural type of one row, without collection cardinality or keys."""

    columns: tuple[TableColumn, ...] = ()
    allow_extra_columns: bool = False

    def __post_init__(self) -> None:
        ids = tuple(column.id for column in self.columns)
        if len(ids) != len(set(ids)):
            msg = "row columns must have unique ids"
            raise ValueError(msg)

    @classmethod
    def from_table(cls, value_type: Table) -> RowType:
        return cls(value_type.columns, value_type.allow_extra_columns)


@dataclass(frozen=True, slots=True)
class ExternalRowRequirement:
    """The typed part of one external row that a plan can observe.

    ``column_references`` retains the exact authored paths, while ``row_type``
    retains the corresponding root-column types and open-row semantics.
    """

    row_type: RowType
    column_references: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        references = tuple(sorted(set(self.column_references)))
        if any(not reference for reference in references):
            msg = "external row column references must be non-empty"
            raise ValueError(msg)
        if not references:
            msg = "an external row requirement must observe at least one column"
            raise ValueError(msg)
        object.__setattr__(self, "column_references", references)


@dataclass(frozen=True, slots=True)
class NamedExternalRowRequirement:
    """One explicitly identified lexical row argument required by a plan."""

    row_scope_id: RowScopeId
    requirement: ExternalRowRequirement


@dataclass(frozen=True, slots=True)
class ExternalRowInterface:
    """The complete external lexical-row interface of one verified plan."""

    point: ExternalRowRequirement | None = None
    arguments: tuple[NamedExternalRowRequirement, ...] = ()

    def __post_init__(self) -> None:
        arguments = tuple(
            sorted(
                self.arguments,
                key=lambda item: item.row_scope_id.qualified_name,
            )
        )
        ids = tuple(item.row_scope_id for item in arguments)
        if len(ids) != len(set(ids)):
            msg = "external row argument ids must be unique"
            raise ValueError(msg)
        object.__setattr__(self, "arguments", arguments)


@dataclass(frozen=True, slots=True)
class RelationTypeBindings:
    """Typed imports and lexical rows available to one plan root."""

    inputs: Mapping[str, ValueType] = field(default_factory=_empty_value_bindings)
    parameters: Mapping[str, ValueType] = field(default_factory=_empty_value_bindings)
    point_row: RowType | None = None
    row_arguments: Mapping[RowScopeId, RowType] = field(
        default_factory=_empty_row_bindings
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "inputs", _frozen_mapping(self.inputs, "input"))
        object.__setattr__(
            self,
            "parameters",
            _frozen_mapping(self.parameters, "parameter"),
        )
        object.__setattr__(
            self,
            "row_arguments",
            MappingProxyType(dict(self.row_arguments)),
        )


class PlanImportNamespace(StrEnum):
    INPUT = "input"
    PARAMETER = "parameter"


@dataclass(frozen=True, slots=True)
class TypedPlanImport:
    namespace: PlanImportNamespace
    id: str
    value_type: ValueType
    lookup: ParameterLookupUse | None = None


class RelationPlanVerificationError(ValueError):
    """A deterministic static relation-plan failure."""

    def __init__(self, code: str, path: PlanPath, message: str) -> None:
        self.code = code
        self.path = path
        self.reason = message
        rendered = _format_path(path)
        super().__init__(f"{rendered}: {message}" if rendered else message)


class VerifiedRelationPlan[NodeT: PlanNode]:
    """Publicly immutable proof that a relation plan is closed and well typed.

    The plan is copied both on entry and on public access so mutation of nested
    literal containers cannot invalidate the proof after verification.
    """

    __slots__ = (
        "_bindings",
        "_certified_type",
        "_external_row_interface",
        "_free_row_references",
        "_imports",
        "_references",
        "_root",
    )

    def __init__(
        self,
        root: NodeT,
        certified_type: ValueType,
        imports: tuple[TypedPlanImport, ...],
        references: PlanReferences,
        free_references: PlanReferences,
        bindings: RelationTypeBindings,
        external_row_interface: ExternalRowInterface | None = None,
    ) -> None:
        if external_row_interface is None:
            raise AssertionError("verified relation plan row interface is missing")
        self._root = deepcopy(root)
        self._certified_type = certified_type
        self._imports = imports
        self._bindings = bindings
        self._external_row_interface = external_row_interface
        self._free_row_references = free_references
        self._references = references

    def __copy__(self) -> VerifiedRelationPlan[NodeT]:
        """Share the sealed proof; every exposed AST remains defensive."""

        return self

    def __deepcopy__(
        self,
        _memo: dict[int, object],
    ) -> VerifiedRelationPlan[NodeT]:
        """Share the sealed proof across deep copies of transient programs."""

        return self

    @property
    def root(self) -> NodeT:
        return deepcopy(self._root)

    @property
    def certified_type(self) -> ValueType:
        return self._certified_type

    @property
    def imports(self) -> tuple[TypedPlanImport, ...]:
        return self._imports

    @property
    def bindings(self) -> RelationTypeBindings:
        return self._bindings

    @property
    def external_row_interface(self) -> ExternalRowInterface:
        return self._external_row_interface

    @property
    def free_row_references(self) -> PlanReferences:
        return self._free_row_references

    @property
    def references(self) -> PlanReferences:
        return self._references


def verify_relation_plan[NodeT: PlanNode](
    root: NodeT,
    *,
    bindings: RelationTypeBindings | None = None,
    expected_type: ValueType | None = None,
) -> VerifiedRelationPlan[NodeT]:
    """Close scopes, infer every node, and certify the root against its consumer."""

    selected = bindings or RelationTypeBindings()
    try:
        verify_plan_scopes(
            root,
            active_row_scopes=selected.row_arguments,
        )
    except RelationPlanScopeError as error:
        raise RelationPlanVerificationError(
            "unbound_row_reference",
            (),
            str(error),
        ) from error
    except RelationPlanBinderError as error:
        raise RelationPlanVerificationError(
            "row_binder_collision",
            (),
            str(error),
        ) from error

    verifier = _Verifier(selected)
    inferred = verifier.infer(root, (), expected_type)
    if expected_type is not None and not is_assignable(inferred, expected_type):
        raise RelationPlanVerificationError(
            "incompatible_result_type",
            (),
            f"inferred {inferred!r}, which is not assignable to {expected_type!r}",
        )
    certified = expected_type or inferred
    free_references = free_row_references(root)
    return VerifiedRelationPlan(
        root,
        certified,
        tuple(verifier.imports.values()),
        plan_references(root),
        free_references,
        selected,
        _external_row_interface(verifier, free_references, selected),
    )


@dataclass(frozen=True, slots=True)
class _Rows:
    point: RowType | None
    arguments: Mapping[RowScopeId, RowType]

    def with_binder(
        self,
        row: RowType,
        row_scope_id: RowScopeId,
    ) -> _Rows:
        arguments = dict(self.arguments)
        arguments[row_scope_id] = row
        return _Rows(
            self.point,
            MappingProxyType(arguments),
        )


class _Verifier:
    def __init__(self, bindings: RelationTypeBindings) -> None:
        self.bindings = bindings
        self.rows = _Rows(
            bindings.point_row,
            bindings.row_arguments,
        )
        self.external_point_references: set[str] = set()
        self.imports: dict[
            tuple[PlanImportNamespace, str, ParameterLookupUse | None],
            TypedPlanImport,
        ] = {}

    def infer(
        self,
        node: PlanNode,
        path: PlanPath,
        expected: ValueType | None = None,
        *,
        rows: _Rows | None = None,
    ) -> ValueType:
        selected_rows = rows or self.rows
        match node:
            case ScalarExpr():
                scalar_expected = expected if isinstance(expected, Scalar) else None
                if expected is not None and scalar_expected is None:
                    raise self.error(
                        "wrong_shape",
                        path,
                        "expected a non-scalar value",
                    )
                result = self.scalar(node, path, scalar_expected, selected_rows)
            case SeriesExpr():
                series_expected = expected if isinstance(expected, Series) else None
                if expected is not None and series_expected is None:
                    raise self.error(
                        "wrong_shape",
                        path,
                        "expected a non-series value",
                    )
                result = self.series(node, path, series_expected, selected_rows)
            case RelationExpr():
                table_expected = expected if isinstance(expected, Table) else None
                if expected is not None and table_expected is None:
                    raise self.error(
                        "wrong_shape",
                        path,
                        "expected a non-table value",
                    )
                result = self.relation(node, path, table_expected, selected_rows)
        return result

    def scalar(
        self,
        node: ScalarExpr,
        path: PlanPath,
        expected: Scalar | None,
        rows: _Rows,
    ) -> Scalar:
        scalar = cast("ScalarExpression", node)
        match scalar:
            case LiteralScalarExpr():
                result = self.literal(scalar.value, path, expected)
            case ColumnScalarExpr():
                selected = rows.arguments.get(scalar.row_scope_id)
                result = self.row_column(selected, scalar.name, path)
            case PointColumnScalarExpr():
                name = scalar.name
                result = self.row_column(rows.point, name, path)
                self.external_point_references.add(name)
            case InputScalarExpr():
                result = self.import_type(
                    PlanImportNamespace.INPUT,
                    scalar.name,
                    Scalar,
                    path,
                )
            case ParameterScalarExpr():
                result = self.import_type(
                    PlanImportNamespace.PARAMETER,
                    scalar.name,
                    Scalar,
                    path,
                )
            case ParameterLookupScalarExpr():
                result = self.parameter_lookup(scalar, path, rows)
            case BinaryScalarExpr():
                left_node = scalar.left
                right_node = scalar.right
                if scalar.op in {"==", "!="} and _is_null_literal(left_node):
                    if _is_null_literal(right_node):
                        raise self.error(
                            "ambiguous_null",
                            path,
                            "comparing two null literals has no scalar type context",
                        )
                    right = cast(
                        "Scalar",
                        self.infer(right_node, (*path, "right"), rows=rows),
                    )
                    left = cast(
                        "Scalar",
                        self.infer(
                            left_node,
                            (*path, "left"),
                            Scalar(right.atom, nullable=True),
                            rows=rows,
                        ),
                    )
                elif scalar.op in {"==", "!="} and _is_null_literal(right_node):
                    left = cast(
                        "Scalar",
                        self.infer(left_node, (*path, "left"), rows=rows),
                    )
                    right = cast(
                        "Scalar",
                        self.infer(
                            right_node,
                            (*path, "right"),
                            Scalar(left.atom, nullable=True),
                            rows=rows,
                        ),
                    )
                else:
                    left = cast(
                        "Scalar",
                        self.infer(left_node, (*path, "left"), rows=rows),
                    )
                    right = cast(
                        "Scalar",
                        self.infer(right_node, (*path, "right"), rows=rows),
                    )
                try:
                    result = scalar_operator_result_type(
                        left,
                        right,
                        scalar.op,
                        left_is_null_literal=_is_null_literal(scalar.left),
                        right_is_null_literal=_is_null_literal(scalar.right),
                    )
                except (TypeError, ValueError) as error:
                    raise self.error(
                        "invalid_scalar_operator", path, str(error)
                    ) from error
                if scalar.op == "/" and _is_zero_literal(scalar.right):
                    raise self.error(
                        "division_by_zero",
                        (*path, "right"),
                        "division denominator is statically zero",
                    )
        self.require_expected(result, expected, path)
        return result

    def series(
        self,
        node: SeriesExpr,
        path: PlanPath,
        expected: Series | None,
        rows: _Rows,
    ) -> Series:
        series = cast("SeriesExpression", node)
        match series:
            case ValuesSeriesExpr():
                items = series.items
                if expected is not None:
                    self.validate_literal(expected, items, path)
                    result = Series(expected.item_type, len(items), len(items))
                else:
                    if not items:
                        raise self.error(
                            "ambiguous_empty_series",
                            path,
                            "an empty values series needs an expected Series type",
                        )
                    result = Series(
                        _common_scalars(
                            [
                                self.literal(item, (*path, "items", index), None)
                                for index, item in enumerate(items)
                            ],
                            path,
                        ),
                        len(items),
                        len(items),
                    )
            case InputSeriesExpr():
                result = self.import_type(
                    PlanImportNamespace.INPUT,
                    series.name,
                    Series,
                    path,
                )
            case ParameterSeriesExpr():
                result = self.import_type(
                    PlanImportNamespace.PARAMETER,
                    series.name,
                    Series,
                    path,
                )
            case RelationEntitiesSeriesExpr():
                source = cast(
                    "Table",
                    self.infer(series.source, (*path, "source"), rows=rows),
                )
                entity_types = [
                    self.row_column(
                        RowType.from_table(source),
                        name,
                        (*path, "columns", index),
                    )
                    for index, name in enumerate(series.columns)
                ]
                for index, item in enumerate(entity_types):
                    if item.nullable or not isinstance(item.atom, Entity):
                        raise self.error(
                            "non_entity_column",
                            (*path, "columns", index),
                            "relation entities requires non-null Entity columns",
                        )
                item = _common_scalars(entity_types, path)
                maximum = _multiply_optional(source.max_rows, len(entity_types))
                minimum = 1 if source.min_rows > 0 and entity_types else 0
                result = Series(item, minimum, maximum)
        self.require_expected(result, expected, path)
        return result

    def relation(
        self,
        node: RelationExpr,
        path: PlanPath,
        expected: Table | None,
        rows: _Rows,
    ) -> Table:
        relation = cast("RelationExpression", node)
        match relation:
            case LiteralRowsRelationExpr():
                literal_rows = relation.rows
                if expected is not None:
                    self.validate_literal(expected, literal_rows, path)
                    result = Table(
                        expected.columns,
                        expected.primary_key,
                        len(literal_rows),
                        len(literal_rows),
                        expected.allow_extra_columns,
                    )
                else:
                    if not literal_rows:
                        raise self.error(
                            "ambiguous_empty_table",
                            path,
                            "empty literal rows need an expected Table type",
                        )
                    result = _infer_literal_table(literal_rows, path)
            case TableRelationExpr():
                result = self.import_type(
                    PlanImportNamespace.PARAMETER,
                    relation.table_id,
                    Table,
                    path,
                )
            case InputRelationExpr():
                result = self.import_type(
                    PlanImportNamespace.INPUT,
                    relation.name,
                    Table,
                    path,
                )
            case SelectRelationExpr():
                source = cast(
                    "Table",
                    self.infer(relation.source, (*path, "source"), rows=rows),
                )
                selected_columns = tuple(
                    TableColumn(
                        name,
                        self.row_column(
                            RowType.from_table(source),
                            name,
                            (*path, "select_columns", index),
                        ),
                    )
                    for index, name in enumerate(relation.select_columns)
                )
                _require_unique_column_ids(selected_columns, path)
                selected_ids = {column.id for column in selected_columns}
                primary_key = (
                    source.primary_key
                    if source.primary_key and set(source.primary_key) <= selected_ids
                    else ()
                )
                result = Table(
                    selected_columns,
                    primary_key,
                    source.min_rows,
                    source.max_rows,
                )
            case FilterRelationExpr():
                source = cast(
                    "Table",
                    self.infer(relation.source, (*path, "source"), rows=rows),
                )
                row = RowType.from_table(source)
                condition = cast(
                    "Scalar",
                    self.infer(
                        relation.condition,
                        (*path, "condition"),
                        rows=rows.with_binder(row, relation.row_scope_id),
                    ),
                )
                self.require_bool(condition, (*path, "condition"))
                result = Table(
                    source.columns,
                    source.primary_key,
                    0,
                    source.max_rows,
                    source.allow_extra_columns,
                )
            case WithColumnsRelationExpr():
                source = cast(
                    "Table",
                    self.infer(relation.source, (*path, "source"), rows=rows),
                )
                columns = list(source.columns)
                overwritten: set[str] = set()
                for name, expression in relation.new_columns.items():
                    current = RowType(tuple(columns), source.allow_extra_columns)
                    value_type = cast(
                        "Scalar",
                        self.infer(
                            expression,
                            (*path, "new_columns", name),
                            rows=rows.with_binder(current, relation.row_scope_id),
                        ),
                    )
                    if any(column.id == name for column in columns):
                        overwritten.add(name)
                        columns = [column for column in columns if column.id != name]
                    columns.append(TableColumn(name, value_type))
                primary_key = (
                    source.primary_key
                    if not overwritten.intersection(source.primary_key)
                    else ()
                )
                result = Table(
                    tuple(columns),
                    primary_key,
                    source.min_rows,
                    source.max_rows,
                    source.allow_extra_columns,
                )
        self.require_expected(result, expected, path)
        return result

    def parameter_lookup(
        self,
        node: ParameterLookupScalarExpr,
        path: PlanPath,
        rows: _Rows,
    ) -> Scalar:
        use = node.use
        selected_key_types = dict(use.key_input_types)
        for name, expression in node.key.items():
            self.infer(
                expression,
                (*path, "key", name),
                selected_key_types[name],
                rows=rows,
            )
        import_key = (PlanImportNamespace.PARAMETER, use.table_id, use)
        self.imports.setdefault(
            import_key,
            TypedPlanImport(
                PlanImportNamespace.PARAMETER,
                use.table_id,
                use.result_type,
                lookup=use,
            ),
        )
        return use.result_type

    def import_type[ExpectedT: ValueType](
        self,
        namespace: PlanImportNamespace,
        import_id: str,
        expected_class: type[ExpectedT],
        path: PlanPath,
    ) -> ExpectedT:
        available = (
            self.bindings.inputs
            if namespace is PlanImportNamespace.INPUT
            else self.bindings.parameters
        )
        try:
            value_type = available[import_id]
        except KeyError as error:
            raise self.error(
                f"unknown_{namespace.value}",
                path,
                f"unknown {namespace.value} {import_id!r}",
            ) from error
        if not isinstance(value_type, expected_class):
            raise self.error(
                "import_shape_mismatch",
                path,
                f"{namespace.value} {import_id!r} has type {value_type!r}",
            )
        key = (namespace, import_id, None)
        self.imports.setdefault(key, TypedPlanImport(namespace, import_id, value_type))
        return value_type

    def row_column(
        self,
        row: RowType | None,
        name: str,
        path: PlanPath,
    ) -> Scalar:
        if row is None:
            raise self.error(
                "missing_row_type",
                path,
                f"column {name!r} has no typed row binding",
            )
        columns = {column.id: column for column in row.columns}
        exact = columns.get(name)
        if exact is not None:
            if not exact.required:
                raise self.error(
                    "optional_column_access",
                    path,
                    f"column {name!r} is not guaranteed to be present",
                )
            return exact.value_type
        parts = name.split(".")
        first = columns.get(parts[0])
        if first is None:
            raise self.error(
                "unknown_column",
                path,
                f"unknown column {parts[0]!r}",
            )
        if not first.required:
            raise self.error(
                "optional_column_access",
                path,
                f"column {parts[0]!r} is not guaranteed to be present",
            )
        current: ValueType = first.value_type
        for part in parts[1:]:
            if (
                not isinstance(current, Scalar)
                or current.nullable
                or not isinstance(current.atom, Record)
            ):
                raise self.error(
                    "invalid_column_path",
                    path,
                    f"{part!r} traverses a nullable or non-record value",
                )
            fields = {item.id: item for item in current.atom.fields}
            selected = fields.get(part)
            if selected is None:
                raise self.error(
                    "unknown_column",
                    path,
                    f"unknown record field {part!r}",
                )
            if not selected.required:
                raise self.error(
                    "optional_column_access",
                    path,
                    f"record field {part!r} is not guaranteed to be present",
                )
            current = selected.value_type
        if not isinstance(current, Scalar):
            raise self.error(
                "non_scalar_column",
                path,
                f"column path {name!r} does not select a scalar",
            )
        return current

    def literal(
        self,
        value: object,
        path: PlanPath,
        expected: Scalar | None,
    ) -> Scalar:
        if expected is not None:
            self.validate_literal(expected, value, path)
            return expected
        if value is None:
            raise self.error(
                "ambiguous_null",
                path,
                "null literal needs an expected nullable Scalar type",
            )
        if isinstance(value, dict):
            mapping = cast("Mapping[str, object]", value)
            fields = tuple(
                RecordField(
                    name,
                    self.literal(item, (*path, name), None),
                )
                for name, item in mapping.items()
            )
            return Scalar(Record(fields))
        return literal_scalar_type(value)

    def validate_literal(
        self,
        expected: ValueType,
        value: object,
        path: PlanPath,
    ) -> None:
        try:
            validate_literal(expected, value, path=path or ("value",))
        except ValueValidationError as error:
            raise self.error("invalid_literal", path, error.reason) from error

    def require_expected(
        self,
        actual: ValueType,
        expected: ValueType | None,
        path: PlanPath,
    ) -> None:
        if expected is not None and not is_assignable(actual, expected):
            raise self.error(
                "incompatible_result_type",
                path,
                f"inferred {actual!r}, which is not assignable to {expected!r}",
            )

    def require_bool(self, value_type: Scalar, path: PlanPath) -> None:
        if value_type.nullable or not isinstance(value_type.atom, Bool):
            raise self.error(
                "non_boolean_condition",
                path,
                "condition must be a non-null Bool scalar",
            )

    @staticmethod
    def error(
        code: str,
        path: PlanPath,
        message: str,
    ) -> RelationPlanVerificationError:
        return RelationPlanVerificationError(code, path, message)


def _infer_literal_table(rows: Sequence[Mapping[str, object]], path: PlanPath) -> Table:
    values: dict[str, list[Scalar]] = {}
    counts: dict[str, int] = {}
    order: list[str] = []
    verifier = _LiteralVerifier()
    for row_index, row in enumerate(rows):
        for name, value in row.items():
            if name not in values:
                values[name] = []
                counts[name] = 0
                order.append(name)
            values[name].append(
                verifier.literal(value, (*path, "rows", row_index, name))
            )
            counts[name] += 1
    columns = tuple(
        TableColumn(
            name,
            _common_scalars(values[name], (*path, "columns", name)),
            required=counts[name] == len(rows),
        )
        for name in order
    )
    return Table(columns, (), len(rows), len(rows))


class _LiteralVerifier:
    def literal(self, value: object, path: PlanPath) -> Scalar:
        if value is None:
            raise RelationPlanVerificationError(
                "ambiguous_null",
                path,
                "null literal needs an expected nullable Scalar type",
            )
        if isinstance(value, dict):
            mapping = cast("Mapping[str, object]", value)
            return Scalar(
                Record(
                    tuple(
                        RecordField(name, self.literal(item, (*path, name)))
                        for name, item in mapping.items()
                    )
                )
            )
        return literal_scalar_type(value)


def _common_scalars(values: Sequence[Scalar], path: PlanPath) -> Scalar:
    if not values:
        raise RelationPlanVerificationError(
            "ambiguous_empty_series",
            path,
            "cannot infer a scalar type from no values",
        )
    selected = values[0]
    for value in values[1:]:
        selected = _join_scalar_types(selected, value, path)
    return selected


def _join_scalar_types(left: Scalar, right: Scalar, path: PlanPath) -> Scalar:
    nullable = left.nullable or right.nullable
    bare_left = Scalar(left.atom)
    bare_right = Scalar(right.atom)
    if is_assignable(bare_left, bare_right):
        return Scalar(right.atom, nullable)
    if is_assignable(bare_right, bare_left):
        return Scalar(left.atom, nullable)
    if isinstance(left.atom, Int | Float) and isinstance(right.atom, Int | Float):
        integer_atoms = tuple(
            atom for atom in (left.atom, right.atom) if isinstance(atom, Int)
        )
        if any(isinstance(atom, Float) for atom in (left.atom, right.atom)) and any(
            not _int_type_is_float_representable(atom) for atom in integer_atoms
        ):
            raise RelationPlanVerificationError(
                "incompatible_branch_types",
                path,
                "unbounded or non-representable Int cannot be widened to Float",
            )
        minima = [
            value
            for value in (left.atom.minimum, right.atom.minimum)
            if value is not None
        ]
        maxima = [
            value
            for value in (left.atom.maximum, right.atom.maximum)
            if value is not None
        ]
        minimum = min(minima) if len(minima) == 2 else None
        maximum = max(maxima) if len(maxima) == 2 else None
        if isinstance(left.atom, Int) and isinstance(right.atom, Int):
            return Scalar(
                Int(
                    cast("int | None", minimum),
                    cast("int | None", maximum),
                ),
                nullable,
            )
        finite = (not isinstance(left.atom, Float) or left.atom.finite) and (
            not isinstance(right.atom, Float) or right.atom.finite
        )
        return Scalar(Float(minimum, maximum, finite=finite), nullable)
    if isinstance(left.atom, String) and isinstance(right.atom, String):
        maximum = (
            None
            if left.atom.max_length is None or right.atom.max_length is None
            else max(left.atom.max_length, right.atom.max_length)
        )
        return Scalar(
            String(min(left.atom.min_length, right.atom.min_length), maximum),
            nullable,
        )
    if isinstance(left.atom, Quantity) and isinstance(right.atom, Quantity):
        left_dimension = left.atom.dimension
        right_dimension = right.atom.dimension
        if left_dimension is None and left.atom.unit is not None:
            left_dimension = unit_kind(left.atom.unit)
        if right_dimension is None and right.atom.unit is not None:
            right_dimension = unit_kind(right.atom.unit)
        if left_dimension == right_dimension and left_dimension is not None:
            return Scalar(
                Quantity(
                    dimension=left_dimension,
                    finite=left.atom.finite and right.atom.finite,
                ),
                nullable,
            )
    if isinstance(left.atom, Entity) and isinstance(right.atom, Entity):
        kind = (
            left.atom.entity_kind
            if left.atom.entity_kind == right.atom.entity_kind
            else None
        )
        return Scalar(Entity(kind), nullable)
    if (
        isinstance(left.atom, Payload)
        and isinstance(right.atom, Payload)
        and left.atom.schema_id == right.atom.schema_id
    ):
        return Scalar(Payload(left.atom.schema_id), nullable)
    raise RelationPlanVerificationError(
        "incompatible_branch_types",
        path,
        f"no common scalar type for {left!r} and {right!r}",
    )


def _int_type_is_float_representable(value_type: Int) -> bool:
    if value_type.minimum is None or value_type.maximum is None:
        return False
    try:
        return math.isfinite(float(value_type.minimum)) and math.isfinite(
            float(value_type.maximum)
        )
    except OverflowError:
        return False


def _require_unique_column_ids(
    columns: Sequence[TableColumn],
    path: PlanPath,
) -> None:
    ids = [column.id for column in columns]
    duplicates = sorted({column_id for column_id in ids if ids.count(column_id) > 1})
    if duplicates:
        raise RelationPlanVerificationError(
            "duplicate_columns",
            path,
            "duplicate output columns: " + ", ".join(duplicates),
        )


def _frozen_mapping(
    values: Mapping[str, ValueType],
    label: str,
) -> Mapping[str, ValueType]:
    copied = dict(values)
    empty = [value_id for value_id in copied if not value_id]
    if empty:
        msg = f"{label} ids must be non-empty"
        raise ValueError(msg)
    return MappingProxyType(copied)


def _external_row_interface(
    verifier: _Verifier,
    free_references: PlanReferences,
    bindings: RelationTypeBindings,
) -> ExternalRowInterface:
    arguments: dict[RowScopeId, set[str]] = {}
    for reference in free_references:
        if reference.kind is PlanReferenceKind.ROW_COLUMN:
            row_scope_id = reference.row_scope_id
            if row_scope_id is None:
                raise AssertionError(
                    "row-column reference is missing its nominal scope"
                )
            arguments.setdefault(row_scope_id, set()).add(reference.id)

    named = tuple(
        NamedExternalRowRequirement(
            row_scope_id,
            _required(
                _external_row_requirement(
                    bindings.row_arguments.get(row_scope_id),
                    references,
                )
            ),
        )
        for row_scope_id, references in arguments.items()
    )
    return ExternalRowInterface(
        point=_external_row_requirement(
            bindings.point_row,
            verifier.external_point_references,
        ),
        arguments=named,
    )


def _external_row_requirement(
    row_type: RowType | None,
    references: set[str],
) -> ExternalRowRequirement | None:
    if not references:
        return None
    bound = row_type or RowType()
    selected_ids = {_row_column_root_id(bound, reference) for reference in references}
    required_type = RowType(
        tuple(column for column in bound.columns if column.id in selected_ids),
        bound.allow_extra_columns,
    )
    return ExternalRowRequirement(
        row_type=required_type,
        column_references=tuple(references),
    )


def _row_column_root_id(row: RowType | None, name: str) -> str:
    if row is None:
        raise AssertionError("verified row reference has no row type")
    column_ids = {column.id for column in row.columns}
    if name in column_ids:
        return name
    root = name.split(".", maxsplit=1)[0]
    if root not in column_ids:
        raise AssertionError(f"verified row reference {name!r} has no root column")
    return root


def _is_null_literal(node: ScalarExpr) -> bool:
    return isinstance(node, LiteralScalarExpr) and node.value is None


def _is_zero_literal(node: ScalarExpr) -> bool:
    if not isinstance(node, LiteralScalarExpr):
        return False
    value = node.value
    if isinstance(value, QuantityValue):
        return value.value == 0
    return isinstance(value, int | float) and not isinstance(value, bool) and value == 0


def _multiply_optional(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return left * right


def _required[ValueT](value: ValueT | None) -> ValueT:
    if value is None:
        raise AssertionError("validated relation node is missing a required field")
    return value


def _format_path(path: PlanPath) -> str:
    if not path:
        return ""
    rendered = "root"
    for item in path:
        rendered += f"[{item}]" if isinstance(item, int) else f".{item}"
    return rendered
