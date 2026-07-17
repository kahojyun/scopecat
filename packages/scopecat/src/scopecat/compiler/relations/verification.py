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
    PlanOperation,
    PlanReferenceKind,
    PlanReferences,
    RelationPlanBinderError,
    RelationPlanScopeError,
    free_row_references,
    plan_references,
    relation_operation,
    verify_plan_scopes,
)
from scopecat.compiler.relations.model import (
    GridColumn,
    LiteralScalarExpr,
    ParameterLookupScalarExpr,
    RelationExpr,
    RelationExpression,
    RowScopeId,
    ScalarExpr,
    ScalarExpression,
    SeriesExpr,
    SeriesExpression,
)
from scopecat.compiler.relations.operators import (
    require_sortable_scalar,
    scalar_operator_result_type,
)
from scopecat.kernel.units import compatible_units, unit_kind
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
    retains the corresponding root-column types and open-row semantics.  A
    full-row requirement means the operation observes row shape beyond named
    column reads, as ``point_cross`` does while merging its point environment.
    """

    row_type: RowType
    column_references: tuple[str, ...] = ()
    requires_full_row: bool = False

    def __post_init__(self) -> None:
        references = tuple(sorted(set(self.column_references)))
        if any(not reference for reference in references):
            msg = "external row column references must be non-empty"
            raise ValueError(msg)
        if not references and not self.requires_full_row:
            msg = "an external row requirement must observe columns or the full row"
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
    current: ExternalRowRequirement | None = None
    outer: ExternalRowRequirement | None = None
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
class ParameterLookupSignature:
    """One typed lookup use without pretending to be a full table schema.

    ``key_input_types`` describe the expressions supplied by the plan, not the
    catalog table's canonical key schema.  ``result_type`` is a guaranteed,
    present result-column contract; catalog validation establishes that
    guarantee before authoring elaboration.
    """

    table_id: str
    key_input_types: tuple[tuple[str, Scalar], ...]
    column_id: str
    result_type: Scalar

    def __post_init__(self) -> None:
        if not self.table_id or not self.column_id:
            msg = "parameter lookup table and result column ids must be non-empty"
            raise ValueError(msg)
        key_ids = tuple(key for key, _value_type in self.key_input_types)
        if any(not key for key in key_ids) or len(key_ids) != len(set(key_ids)):
            msg = "parameter lookup key column ids must be non-empty and unique"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "key_input_types",
            tuple(sorted(self.key_input_types, key=lambda item: item[0])),
        )


@dataclass(frozen=True, slots=True)
class RelationTypeBindings:
    """Typed imports and lexical rows available to one plan root."""

    inputs: Mapping[str, ValueType] = field(default_factory=_empty_value_bindings)
    parameters: Mapping[str, ValueType] = field(default_factory=_empty_value_bindings)
    parameter_lookups: tuple[ParameterLookupSignature, ...] = ()
    point_row: RowType | None = None
    current_row: RowType | None = None
    outer_row: RowType | None = None
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
        lookups: list[ParameterLookupSignature] = []
        result_types: dict[tuple[str, tuple[str, ...], str], Scalar] = {}
        for signature in tuple(self.parameter_lookups):
            identity = (
                signature.table_id,
                tuple(key for key, _value_type in signature.key_input_types),
                signature.column_id,
            )
            previous_result = result_types.get(identity)
            if previous_result is not None and previous_result != signature.result_type:
                msg = (
                    "parameter lookup result signatures conflict for "
                    f"{signature.table_id!r}.{signature.column_id!r}"
                )
                raise ValueError(msg)
            result_types.setdefault(identity, signature.result_type)
            if signature not in lookups:
                lookups.append(signature)
        object.__setattr__(self, "parameter_lookups", tuple(lookups))


class PlanImportNamespace(StrEnum):
    INPUT = "input"
    PARAMETER = "parameter"


class RelationRuntimeObligationKind(StrEnum):
    """Stable identities for checks deferred to plan materialization."""

    DIVISION_RIGHT_NONZERO = "division_right_nonzero"
    NO_EXTRA_COLUMN_COLLISION = "no_extra_column_collision"
    PARAMETER_LOOKUP_EXACTLY_ONE = "parameter_lookup_exactly_one"
    RANGE_PROGRESS = "range_progress"
    RANGE_STEP_NONZERO = "range_step_nonzero"
    SCALAR_RESULT_FINITE = "scalar_result_finite"
    SERIES_VALUES_FINITE = "series_values_finite"
    ZIP_EQUAL_LENGTH = "zip_equal_length"


@dataclass(frozen=True, slots=True)
class TypedPlanImport:
    namespace: PlanImportNamespace
    id: str
    value_type: ValueType
    lookup: ParameterLookupSignature | None = None


@dataclass(frozen=True, slots=True)
class PlanTypeFact:
    """The inferred type of one operation occurrence at a stable AST path."""

    path: PlanPath
    operation: PlanOperation
    value_type: ValueType


@dataclass(frozen=True, slots=True)
class RuntimeObligation:
    """A checked condition that remains data-dependent at materialization time."""

    code: RelationRuntimeObligationKind
    path: PlanPath
    message: str


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
        "_facts",
        "_free_row_references",
        "_imports",
        "_references",
        "_root",
        "_runtime_obligations",
    )

    def __init__(
        self,
        root: NodeT,
        certified_type: ValueType,
        facts: tuple[PlanTypeFact, ...],
        imports: tuple[TypedPlanImport, ...],
        references: PlanReferences,
        runtime_obligations: tuple[RuntimeObligation, ...],
        bindings: RelationTypeBindings,
        external_row_interface: ExternalRowInterface | None = None,
    ) -> None:
        if external_row_interface is None:
            raise AssertionError("verified relation plan row interface is missing")
        self._root = deepcopy(root)
        self._certified_type = certified_type
        self._facts = facts
        self._imports = imports
        self._bindings = bindings
        self._external_row_interface = external_row_interface
        self._free_row_references = free_row_references(root)
        self._references = references
        self._runtime_obligations = runtime_obligations

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
    def facts(self) -> tuple[PlanTypeFact, ...]:
        return self._facts

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

    @property
    def runtime_obligations(self) -> tuple[RuntimeObligation, ...]:
        return self._runtime_obligations


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
            current_row_available=selected.current_row is not None,
            outer_row_available=selected.outer_row is not None,
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
        tuple(verifier.facts),
        tuple(verifier.imports.values()),
        plan_references(root),
        tuple(verifier.obligations),
        selected,
        _external_row_interface(verifier, free_references, selected),
    )


@dataclass(frozen=True, slots=True)
class _Rows:
    point: RowType | None
    current: RowType | None
    outer: RowType | None
    arguments: Mapping[RowScopeId, RowType]
    local_point_columns: frozenset[str] = frozenset()

    def with_current(
        self,
        row: RowType,
        row_scope_id: RowScopeId | None = None,
    ) -> _Rows:
        arguments = dict(self.arguments)
        if row_scope_id is not None:
            arguments[row_scope_id] = row
        return _Rows(
            self.point,
            row,
            self.outer,
            MappingProxyType(arguments),
            self.local_point_columns,
        )


_EMPTY_COLUMN_IDS: frozenset[str] = frozenset()


class _Verifier:
    def __init__(self, bindings: RelationTypeBindings) -> None:
        self.bindings = bindings
        self.rows = _Rows(
            bindings.point_row,
            bindings.current_row,
            bindings.outer_row,
            bindings.row_arguments,
        )
        self.facts: list[PlanTypeFact] = []
        self.obligations: list[RuntimeObligation] = []
        self.external_point_references: set[str] = set()
        self.requires_full_external_point_row = False
        self.imports: dict[
            tuple[PlanImportNamespace, str, ParameterLookupSignature | None],
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
        if isinstance(node, ScalarExpr):
            scalar_expected = expected if isinstance(expected, Scalar) else None
            if expected is not None and scalar_expected is None:
                raise self.error("wrong_shape", path, "expected a non-scalar value")
            result = self.scalar(node, path, scalar_expected, selected_rows)
        elif isinstance(node, SeriesExpr):
            series_expected = expected if isinstance(expected, Series) else None
            if expected is not None and series_expected is None:
                raise self.error("wrong_shape", path, "expected a non-series value")
            result = self.series(node, path, series_expected, selected_rows)
        else:
            table_expected = expected if isinstance(expected, Table) else None
            if expected is not None and table_expected is None:
                raise self.error("wrong_shape", path, "expected a non-table value")
            result = self.relation(node, path, table_expected, selected_rows)
        self.facts.append(PlanTypeFact(path, relation_operation(node), result))
        return result

    def scalar(
        self,
        node: ScalarExpr,
        path: PlanPath,
        expected: Scalar | None,
        rows: _Rows,
    ) -> Scalar:
        scalar = cast("ScalarExpression", node)
        if scalar.kind == "literal":
            result = self.literal(scalar.value, path, expected)
        elif scalar.kind == "column":
            selected = (
                rows.arguments.get(scalar.row_scope_id)
                if scalar.row_scope_id is not None
                else rows.current
            )
            result = self.row_column(selected, scalar.name, path)
        elif scalar.kind == "outer_column":
            result = self.row_column(rows.outer, scalar.name, path)
        elif scalar.kind == "point_column":
            name = scalar.name
            result = self.row_column(rows.point, name, path)
            if _row_column_root_id(rows.point, name) not in rows.local_point_columns:
                self.external_point_references.add(name)
        elif scalar.kind == "input":
            result = self.import_type(
                PlanImportNamespace.INPUT,
                scalar.name,
                Scalar,
                path,
            )
        elif scalar.kind == "param_scalar":
            result = self.import_type(
                PlanImportNamespace.PARAMETER,
                scalar.name,
                Scalar,
                path,
            )
        elif scalar.kind == "param_lookup":
            result = self.parameter_lookup(scalar, path, rows)
        elif scalar.kind == "binary":
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
                raise self.error("invalid_scalar_operator", path, str(error)) from error
            if scalar.op == "/":
                if _is_zero_literal(scalar.right):
                    raise self.error(
                        "division_by_zero",
                        (*path, "right"),
                        "division denominator is statically zero",
                    )
                if not _literal_is_provably_nonzero(scalar.right):
                    self.obligation(
                        RelationRuntimeObligationKind.DIVISION_RIGHT_NONZERO,
                        (*path, "right"),
                        "division denominator must be non-zero",
                    )
            if scalar.op in {"+", "-", "*", "/"} and isinstance(
                result.atom,
                Float | Quantity,
            ):
                self.obligation(
                    RelationRuntimeObligationKind.SCALAR_RESULT_FINITE,
                    path,
                    "floating-point arithmetic must produce a finite result",
                )
        elif scalar.kind == "case":
            value_nodes: list[tuple[ScalarExpr, PlanPath]] = []
            for index, branch in enumerate(scalar.cases):
                condition = cast(
                    "Scalar",
                    self.infer(
                        branch.condition,
                        (*path, "cases", index, "condition"),
                        rows=rows,
                    ),
                )
                self.require_bool(condition, (*path, "cases", index, "condition"))
                value_nodes.append((branch.value, (*path, "cases", index, "value")))
            value_nodes.append((scalar.fallback, (*path, "fallback")))
            if expected is not None:
                values = [
                    cast(
                        "Scalar",
                        self.infer(value, value_path, expected, rows=rows),
                    )
                    for value, value_path in value_nodes
                ]
                result = expected
            else:
                seed_index = next(
                    (
                        index
                        for index, (value, _) in enumerate(value_nodes)
                        if not _is_null_literal(value)
                    ),
                    None,
                )
                if seed_index is None:
                    raise self.error(
                        "ambiguous_null",
                        path,
                        "a case containing only null values needs an expected type",
                    )
                seed_node, seed_path = value_nodes[seed_index]
                seed = cast(
                    "Scalar",
                    self.infer(seed_node, seed_path, rows=rows),
                )
                values = [seed]
                nullable_seed = Scalar(seed.atom, nullable=True)
                for index, (value, value_path) in enumerate(value_nodes):
                    if index == seed_index:
                        continue
                    values.append(
                        cast(
                            "Scalar",
                            self.infer(
                                value,
                                value_path,
                                nullable_seed if _is_null_literal(value) else None,
                                rows=rows,
                            ),
                        )
                    )
                result = _common_scalars(values, path)
        else:
            raise self.error(
                "unsupported_operation",
                path,
                f"scalar expression {scalar!r}",
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
        if series.kind == "values":
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
        elif series.kind == "linspace" or series.kind == "range":
            start = cast(
                "Scalar",
                self.infer(series.start, (*path, "start"), rows=rows),
            )
            stop = cast(
                "Scalar",
                self.infer(series.stop, (*path, "stop"), rows=rows),
            )
            operands = [start, stop]
            if series.kind == "range":
                step = cast(
                    "Scalar",
                    self.infer(series.step, (*path, "step"), rows=rows),
                )
                operands.append(step)
                if _is_zero_literal(series.step):
                    raise self.error(
                        "range_step_zero",
                        (*path, "step"),
                        "range step is statically zero",
                    )
                if not _literal_is_provably_nonzero(series.step):
                    self.obligation(
                        RelationRuntimeObligationKind.RANGE_STEP_NONZERO,
                        (*path, "step"),
                        "range step must be non-zero",
                    )
            item = _numeric_series_item(operands, path, unit=series.unit)
            if series.kind == "linspace":
                result = Series(item, series.count, series.count)
                self.obligation(
                    RelationRuntimeObligationKind.SERIES_VALUES_FINITE,
                    path,
                    "linspace materialization must produce only finite values",
                )
            else:
                result = Series(item)
                self.obligation(
                    RelationRuntimeObligationKind.RANGE_PROGRESS,
                    path,
                    "range step must advance every materialized value",
                )
        elif series.kind == "input":
            result = self.import_type(
                PlanImportNamespace.INPUT,
                series.name,
                Series,
                path,
            )
        elif series.kind == "param_series":
            result = self.import_type(
                PlanImportNamespace.PARAMETER,
                series.name,
                Series,
                path,
            )
        elif series.kind == "relation_column":
            source = cast(
                "Table",
                self.infer(series.source, (*path, "source"), rows=rows),
            )
            item = self.row_column(
                RowType.from_table(source),
                series.column,
                (*path, "column"),
            )
            result = Series(item, source.min_rows, source.max_rows)
        elif series.kind == "relation_entities":
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
        else:
            raise self.error(
                "unsupported_operation",
                path,
                f"series expression {series!r}",
            )
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
        if relation.kind == "literal_rows":
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
        elif relation.kind == "table":
            result = self.import_type(
                PlanImportNamespace.PARAMETER,
                relation.table_id,
                Table,
                path,
            )
        elif relation.kind == "input":
            result = self.import_type(
                PlanImportNamespace.INPUT,
                relation.name,
                Table,
                path,
            )
        elif relation.kind == "grid":
            result = self.grid(relation.columns, path, rows, expected)
        elif relation.kind == "select":
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
        elif relation.kind == "filter":
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
                    rows=rows.with_current(row, relation.row_scope_id),
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
        elif relation.kind == "join":
            on = relation.on
            allowed_shared = {
                left_name
                for left_name, right_name in on.items()
                if left_name == right_name
            }
            left = cast(
                "Table",
                self.infer(
                    relation.left,
                    (*path, "left"),
                    self.relation_expected(relation.left, expected),
                    rows=rows,
                ),
            )
            right = cast(
                "Table",
                self.infer(
                    relation.right,
                    (*path, "right"),
                    self.relation_expected(
                        relation.right,
                        expected,
                        excluded_column_ids=allowed_shared,
                    ),
                    rows=rows,
                ),
            )
            for left_name, right_name in on.items():
                left_key = self.row_column(
                    RowType.from_table(left), left_name, (*path, "on", left_name)
                )
                right_key = self.row_column(
                    RowType.from_table(right), right_name, (*path, "on", left_name)
                )
                if left_key.nullable or right_key.nullable:
                    raise self.error(
                        "nullable_join_key",
                        (*path, "on", left_name),
                        "join keys must be non-null scalars",
                    )
                try:
                    scalar_operator_result_type(left_key, right_key, "==")
                except TypeError as error:
                    raise self.error(
                        "incompatible_join_key",
                        (*path, "on", left_name),
                        str(error),
                    ) from error
            result = self.merge_tables(
                left,
                right,
                path,
                operation="join",
                allowed_shared=allowed_shared,
                minimum=0,
                maximum=_multiply_optional(left.max_rows, right.max_rows),
            )
        elif (
            relation.kind == "cross"
            or relation.kind == "lateral_cross"
            or relation.kind == "point_cross"
        ):
            left = cast(
                "Table",
                self.infer(
                    relation.left,
                    (*path, "left"),
                    self.relation_expected(relation.left, expected),
                    rows=rows,
                ),
            )
            right_rows = rows
            if relation.kind == "lateral_cross":
                left_row = RowType.from_table(left)
                right_rows = _Rows(
                    rows.point,
                    left_row,
                    left_row,
                    rows.arguments,
                    rows.local_point_columns,
                )
            elif relation.kind == "point_cross":
                external_point = self.bindings.point_row
                self.requires_full_external_point_row |= (
                    left.max_rows != 0 and external_point is not None
                )
                point = self.merge_rows(
                    rows.point or RowType(),
                    RowType.from_table(left),
                    (*path, "point"),
                    operation="point_cross",
                    rows_can_coexist=left.max_rows != 0,
                )
                right_rows = _Rows(
                    point,
                    rows.current,
                    rows.outer,
                    rows.arguments,
                    rows.local_point_columns
                    | frozenset(column.id for column in left.columns),
                )
            right = cast(
                "Table",
                self.infer(
                    relation.right,
                    (*path, "right"),
                    self.relation_expected(relation.right, expected),
                    rows=right_rows,
                ),
            )
            result = self.merge_tables(
                left,
                right,
                path,
                operation=relation.kind,
                minimum=left.min_rows * right.min_rows,
                maximum=_multiply_optional(left.max_rows, right.max_rows),
            )
        elif relation.kind == "zip":
            sources = [
                cast(
                    "Table",
                    self.infer(source, (*path, "sources", index), rows=rows),
                )
                for index, source in enumerate(relation.sources)
            ]
            minimum = max(source.min_rows for source in sources)
            maxima = [source.max_rows for source in sources]
            finite_maxima = [maximum for maximum in maxima if maximum is not None]
            maximum = min(finite_maxima) if finite_maxima else None
            if maximum is not None and minimum > maximum:
                raise self.error(
                    "zip_cardinality_mismatch",
                    path,
                    "zip source cardinality ranges do not overlap",
                )
            exact = {
                source.min_rows
                for source in sources
                if source.max_rows == source.min_rows
            }
            all_exact = all(source.min_rows == source.max_rows for source in sources)
            if all_exact and len(exact) > 1:
                raise self.error(
                    "zip_cardinality_mismatch",
                    path,
                    "zip sources have unequal fixed lengths",
                )
            if not all_exact:
                self.obligation(
                    RelationRuntimeObligationKind.ZIP_EQUAL_LENGTH,
                    path,
                    "zip sources must materialize with equal lengths",
                )
            result = Table((), (), minimum, maximum)
            for index, source in enumerate(sources):
                result = self.merge_tables(
                    result,
                    source,
                    (*path, "sources", index),
                    operation="zip",
                    minimum=minimum,
                    maximum=maximum,
                )
        elif relation.kind == "with_columns":
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
                        rows=rows.with_current(current, relation.row_scope_id),
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
        elif relation.kind == "sort":
            source = cast(
                "Table",
                self.infer(relation.source, (*path, "source"), rows=rows),
            )
            for index, name in enumerate(relation.sort_columns):
                value_type = self.row_column(
                    RowType.from_table(source),
                    name,
                    (*path, "sort_columns", index),
                )
                try:
                    require_sortable_scalar(value_type, column_id=name)
                except TypeError as error:
                    raise self.error(
                        "unsortable_column",
                        (*path, "sort_columns", index),
                        str(error),
                    ) from error
            result = source
        elif relation.kind == "limit":
            source = cast(
                "Table",
                self.infer(relation.source, (*path, "source"), rows=rows),
            )
            count = relation.limit_count
            result = Table(
                source.columns,
                source.primary_key,
                min(source.min_rows, count),
                _min_optional(source.max_rows, count),
                source.allow_extra_columns,
            )
        else:
            raise self.error(
                "unsupported_operation", path, f"relation {relation.kind!r}"
            )
        self.require_expected(result, expected, path)
        return result

    def grid(
        self,
        columns: Mapping[str, GridColumn],
        path: PlanPath,
        rows: _Rows,
        expected: Table | None,
    ) -> Table:
        output: list[TableColumn] = []
        minimum = 1
        maximum: int | None = 1
        expected_columns = (
            {column.id: column for column in expected.columns}
            if expected is not None
            else {}
        )
        for name, column in columns.items():
            column_path = (*path, "columns", name)
            expected_item = (
                selected.value_type
                if (selected := expected_columns.get(name)) is not None
                else None
            )
            if column.kind == "scalar":
                item = cast(
                    "Scalar",
                    self.infer(
                        column.scalar,
                        (*column_path, "scalar"),
                        expected_item,
                        rows=rows,
                    ),
                )
                lower, upper = 1, 1
            elif column.kind == "series":
                series = cast(
                    "Series",
                    self.infer(
                        column.series,
                        (*column_path, "series"),
                        (Series(expected_item) if expected_item is not None else None),
                        rows=rows,
                    ),
                )
                item = series.item_type
                lower, upper = series.min_length, series.max_length
            elif column.kind == "relation":
                relation_expected = (
                    _table_from_record(expected_item.atom)
                    if expected_item is not None
                    and isinstance(expected_item.atom, Record)
                    else None
                )
                relation = cast(
                    "Table",
                    self.infer(
                        column.relation,
                        (*column_path, "relation"),
                        relation_expected,
                        rows=rows,
                    ),
                )
                item = Scalar(_record_from_row(RowType.from_table(relation)))
                lower, upper = relation.min_rows, relation.max_rows
            else:
                values = column.values
                if expected_item is not None:
                    self.validate_literal(
                        Series(expected_item, len(values), len(values)),
                        values,
                        (*column_path, "values"),
                    )
                    item = expected_item
                elif not values:
                    raise self.error(
                        "ambiguous_empty_series",
                        (*column_path, "values"),
                        "an empty grid values column needs contextual typing",
                    )
                else:
                    item = _common_scalars(
                        [
                            self.literal(
                                value,
                                (*column_path, "values", index),
                                None,
                            )
                            for index, value in enumerate(values)
                        ],
                        column_path,
                    )
                lower = upper = len(values)
            output.append(TableColumn(name, item))
            minimum *= lower
            maximum = _multiply_optional(maximum, upper)
        return Table(tuple(output), (), minimum, maximum)

    def parameter_lookup(
        self,
        node: ParameterLookupScalarExpr,
        path: PlanPath,
        rows: _Rows,
    ) -> Scalar:
        table_id = node.table_id
        key_ids = frozenset(node.key)
        signatures = tuple(
            item
            for item in self.bindings.parameter_lookups
            if item.table_id == table_id
            and item.column_id == node.column
            and frozenset(key for key, _value_type in item.key_input_types) == key_ids
        )
        if signatures:
            if len(signatures) == 1:
                signature = signatures[0]
                selected_key_types = dict(signature.key_input_types)
                for name, expression in node.key.items():
                    self.infer(
                        expression,
                        (*path, "key", name),
                        selected_key_types[name],
                        rows=rows,
                    )
            else:
                signature = self._select_parameter_lookup_signature(
                    node,
                    path,
                    rows,
                    signatures,
                )
            import_key = (PlanImportNamespace.PARAMETER, table_id, signature)
            imported = TypedPlanImport(
                PlanImportNamespace.PARAMETER,
                table_id,
                signature.result_type,
                lookup=signature,
            )
            self.imports.setdefault(import_key, imported)
            result = signature.result_type
            self.obligation(
                RelationRuntimeObligationKind.PARAMETER_LOOKUP_EXACTLY_ONE,
                path,
                "parameter lookup key must match exactly one row",
            )
            return result

        table_type = self.import_type(
            PlanImportNamespace.PARAMETER,
            table_id,
            Table,
            path,
        )
        row = RowType.from_table(table_type)
        for name, expression in node.key.items():
            key_type = self.row_column(row, name, (*path, "key", name))
            self.infer(
                expression,
                (*path, "key", name),
                key_type,
                rows=rows,
            )
        result = self.row_column(row, node.column, (*path, "column"))
        self.obligation(
            RelationRuntimeObligationKind.PARAMETER_LOOKUP_EXACTLY_ONE,
            path,
            "parameter lookup key must match exactly one row",
        )
        return result

    def _select_parameter_lookup_signature(
        self,
        node: ParameterLookupScalarExpr,
        path: PlanPath,
        rows: _Rows,
        signatures: tuple[ParameterLookupSignature, ...],
    ) -> ParameterLookupSignature:
        table_id = node.table_id
        null_keys = {
            name
            for name, expression in node.key.items()
            if _is_null_literal(expression)
        }
        actual_key_types = {
            name: cast(
                "Scalar",
                self.infer(expression, (*path, "key", name), rows=rows),
            )
            for name, expression in node.key.items()
            if name not in null_keys
        }
        signature = next(
            (
                item
                for item in signatures
                if all(
                    expected_type.nullable
                    if name in null_keys
                    else is_assignable(actual_key_types[name], expected_type)
                    for name, expected_type in item.key_input_types
                )
            ),
            None,
        )
        if signature is None:
            raise self.error(
                "parameter_lookup_key_type_mismatch",
                path,
                f"parameter lookup {table_id!r} key types do not match "
                "any declared lookup use",
            )
        selected_key_types = dict(signature.key_input_types)
        for name in null_keys:
            self.infer(
                node.key[name],
                (*path, "key", name),
                selected_key_types[name],
                rows=rows,
            )
        return signature

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

    def merge_tables(
        self,
        left: Table,
        right: Table,
        path: PlanPath,
        *,
        operation: str,
        minimum: int,
        maximum: int | None,
        allowed_shared: set[str] | None = None,
    ) -> Table:
        row = self.merge_rows(
            RowType.from_table(left),
            RowType.from_table(right),
            path,
            operation=operation,
            allowed_shared=allowed_shared,
            rows_can_coexist=left.max_rows != 0 and right.max_rows != 0,
        )
        if operation == "zip":
            primary_key = left.primary_key or right.primary_key
        elif left.primary_key and right.primary_key:
            primary_key = tuple(dict.fromkeys((*left.primary_key, *right.primary_key)))
        else:
            primary_key = ()
        return Table(
            row.columns,
            primary_key,
            minimum,
            maximum,
            row.allow_extra_columns,
        )

    def relation_expected(
        self,
        node: RelationExpr,
        expected: Table | None,
        *,
        excluded_column_ids: set[str] | frozenset[str] = _EMPTY_COLUMN_IDS,
    ) -> Table | None:
        """Project a consumer row contract onto one compositional child."""

        if expected is None:
            return None
        column_ids = _relation_output_column_ids(node, self.bindings)
        if column_ids is None:
            return None
        selected = tuple(
            column
            for column in expected.columns
            if column.id in column_ids and column.id not in excluded_column_ids
        )
        if not selected:
            return None
        selected_ids = {column.id for column in selected}
        primary_key = (
            expected.primary_key
            if expected.primary_key and set(expected.primary_key) <= selected_ids
            else ()
        )
        return Table(
            columns=selected,
            primary_key=primary_key,
            allow_extra_columns=_relation_may_have_extra_columns(
                node,
                self.bindings,
            ),
        )

    def merge_rows(
        self,
        left: RowType,
        right: RowType,
        path: PlanPath,
        *,
        operation: str,
        allowed_shared: set[str] | None = None,
        rows_can_coexist: bool = True,
    ) -> RowType:
        allowed = allowed_shared or set()
        left_by_id = {column.id: column for column in left.columns}
        right_by_id = {column.id: column for column in right.columns}
        overlap = set(left_by_id).intersection(right_by_id)
        forbidden = sorted(overlap - allowed)
        if forbidden:
            raise self.error(
                "duplicate_columns",
                path,
                f"{operation} contains duplicate columns: {', '.join(forbidden)}",
            )
        left_column_ids = set(left_by_id)
        right_column_ids = set(right_by_id)
        dynamic_collision_possible = (
            left.allow_extra_columns
            and (right.allow_extra_columns or bool(right_column_ids - left_column_ids))
        ) or (right.allow_extra_columns and bool(left_column_ids - right_column_ids))
        if rows_can_coexist and dynamic_collision_possible:
            self.obligation(
                RelationRuntimeObligationKind.NO_EXTRA_COLUMN_COLLISION,
                path,
                f"{operation} open rows must not materialize duplicate columns",
            )
        columns = left.columns + tuple(
            column for column in right.columns if column.id not in allowed
        )
        return RowType(
            columns,
            left.allow_extra_columns or right.allow_extra_columns,
        )

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

    def obligation(
        self,
        code: RelationRuntimeObligationKind,
        path: PlanPath,
        message: str,
    ) -> None:
        obligation = RuntimeObligation(code, path, message)
        if obligation not in self.obligations:
            self.obligations.append(obligation)

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


def _numeric_series_item(
    values: Sequence[Scalar],
    path: PlanPath,
    *,
    unit: str | None,
) -> Scalar:
    if any(value.nullable for value in values):
        raise RelationPlanVerificationError(
            "invalid_series_bound",
            path,
            "series bounds must be non-null numeric scalars",
        )
    atoms = [value.atom for value in values]
    if any(isinstance(atom, Float | Quantity) and not atom.finite for atom in atoms):
        raise RelationPlanVerificationError(
            "invalid_series_bound",
            path,
            "series bounds must guarantee finite values",
        )
    if any(
        isinstance(atom, Int) and not _int_type_is_float_representable(atom)
        for atom in atoms
    ):
        raise RelationPlanVerificationError(
            "invalid_series_bound",
            path,
            "integer series bounds must have finite float-representable bounds",
        )
    if unit is not None:
        try:
            output_atom = Quantity(unit=unit)
        except ValueError as error:
            raise RelationPlanVerificationError(
                "invalid_series_unit",
                path,
                str(error),
            ) from error
        for atom in atoms:
            if isinstance(atom, Int | Float):
                continue
            if not isinstance(atom, Quantity) or not _quantity_accepts_unit(atom, unit):
                raise RelationPlanVerificationError(
                    "invalid_series_bound",
                    path,
                    "explicit-unit series bounds must be numbers or quantities "
                    f"compatible with {unit!r}",
                )
        return Scalar(output_atom)
    if all(isinstance(atom, Int | Float) for atom in atoms):
        return Scalar(Float())
    if all(isinstance(atom, Quantity) for atom in atoms):
        common = _common_scalars(values, path)
        if isinstance(common.atom, Quantity):
            return Scalar(
                Quantity(dimension=common.atom.dimension, unit=common.atom.unit)
            )
    raise RelationPlanVerificationError(
        "invalid_series_bound",
        path,
        "series bounds must all be numbers or compatible quantities",
    )


def _quantity_accepts_unit(value_type: Quantity, unit: str) -> bool:
    if value_type.unit is not None:
        return compatible_units(value_type.unit, unit)
    if value_type.dimension is not None:
        return value_type.dimension == unit_kind(unit)
    return False


def _int_type_is_float_representable(value_type: Int) -> bool:
    if value_type.minimum is None or value_type.maximum is None:
        return False
    try:
        return math.isfinite(float(value_type.minimum)) and math.isfinite(
            float(value_type.maximum)
        )
    except OverflowError:
        return False


def _record_from_row(row: RowType) -> Record:
    return Record(
        tuple(
            RecordField(column.id, column.value_type, column.required)
            for column in row.columns
        ),
        allow_extra_fields=row.allow_extra_columns,
    )


def _table_from_record(record: Record) -> Table | None:
    if any(not isinstance(field.value_type, Scalar) for field in record.fields):
        return None
    return Table(
        tuple(
            TableColumn(
                field.id,
                cast("Scalar", field.value_type),
                field.required,
            )
            for field in record.fields
        ),
        allow_extra_columns=record.allow_extra_fields,
    )


def _relation_output_column_ids(
    node: RelationExpr,
    bindings: RelationTypeBindings,
) -> frozenset[str] | None:
    """Resolve structural output ids without performing value-type inference."""

    relation = cast("RelationExpression", node)
    if relation.kind == "literal_rows":
        return frozenset(name for row in relation.rows for name in row)
    if relation.kind == "table":
        value_type = bindings.parameters.get(relation.table_id)
        return (
            frozenset(column.id for column in value_type.columns)
            if isinstance(value_type, Table)
            else None
        )
    if relation.kind == "input":
        value_type = bindings.inputs.get(relation.name)
        return (
            frozenset(column.id for column in value_type.columns)
            if isinstance(value_type, Table)
            else None
        )
    if relation.kind == "grid":
        return frozenset(relation.columns)
    if relation.kind == "select":
        return frozenset(relation.select_columns)
    if relation.kind == "filter" or relation.kind == "sort" or relation.kind == "limit":
        return _relation_output_column_ids(relation.source, bindings)
    if (
        relation.kind == "join"
        or relation.kind == "cross"
        or relation.kind == "lateral_cross"
        or relation.kind == "point_cross"
    ):
        left = _relation_output_column_ids(relation.left, bindings)
        right = _relation_output_column_ids(relation.right, bindings)
        return left | right if left is not None and right is not None else None
    if relation.kind == "zip":
        sources = tuple(
            _relation_output_column_ids(source, bindings) for source in relation.sources
        )
        if any(source is None for source in sources):
            return None
        return frozenset(
            column_id
            for source in sources
            if source is not None
            for column_id in source
        )
    if relation.kind == "with_columns":
        source = _relation_output_column_ids(relation.source, bindings)
        return source | frozenset(relation.new_columns) if source is not None else None
    return None


def _relation_may_have_extra_columns(
    node: RelationExpr,
    bindings: RelationTypeBindings,
) -> bool:
    relation = cast("RelationExpression", node)
    if relation.kind == "table":
        value_type = bindings.parameters.get(relation.table_id)
        return isinstance(value_type, Table) and value_type.allow_extra_columns
    if relation.kind == "input":
        value_type = bindings.inputs.get(relation.name)
        return isinstance(value_type, Table) and value_type.allow_extra_columns
    if (
        relation.kind == "filter"
        or relation.kind == "sort"
        or relation.kind == "limit"
        or relation.kind == "with_columns"
    ):
        return _relation_may_have_extra_columns(relation.source, bindings)
    if (
        relation.kind == "join"
        or relation.kind == "cross"
        or relation.kind == "lateral_cross"
        or relation.kind == "point_cross"
    ):
        return _relation_may_have_extra_columns(
            relation.left, bindings
        ) or _relation_may_have_extra_columns(relation.right, bindings)
    if relation.kind == "zip":
        return any(
            _relation_may_have_extra_columns(source, bindings)
            for source in relation.sources
        )
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
    current: set[str] = set()
    outer: set[str] = set()
    arguments: dict[RowScopeId, set[str]] = {}
    for reference in free_references:
        if reference.kind is PlanReferenceKind.OUTER_COLUMN:
            outer.add(reference.id)
        elif reference.kind is PlanReferenceKind.CURRENT_COLUMN:
            if reference.row_scope_id is None:
                current.add(reference.id)
            else:
                arguments.setdefault(reference.row_scope_id, set()).add(reference.id)

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
            requires_full_row=verifier.requires_full_external_point_row,
        ),
        current=_external_row_requirement(bindings.current_row, current),
        outer=_external_row_requirement(bindings.outer_row, outer),
        arguments=named,
    )


def _external_row_requirement(
    row_type: RowType | None,
    references: set[str],
    *,
    requires_full_row: bool = False,
) -> ExternalRowRequirement | None:
    if not references and not requires_full_row:
        return None
    bound = row_type or RowType()
    if requires_full_row:
        required_type = bound
    else:
        selected_ids = {
            _row_column_root_id(bound, reference) for reference in references
        }
        required_type = RowType(
            tuple(column for column in bound.columns if column.id in selected_ids),
            bound.allow_extra_columns,
        )
    return ExternalRowRequirement(
        row_type=required_type,
        column_references=tuple(references),
        requires_full_row=requires_full_row,
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


def _literal_is_provably_nonzero(node: ScalarExpr) -> bool:
    if not isinstance(node, LiteralScalarExpr):
        return False
    value = node.value
    if isinstance(value, QuantityValue):
        return value.value != 0
    return isinstance(value, int | float) and not isinstance(value, bool) and value != 0


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


def _min_optional(value: int | None, limit: int) -> int:
    return limit if value is None else min(value, limit)


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
