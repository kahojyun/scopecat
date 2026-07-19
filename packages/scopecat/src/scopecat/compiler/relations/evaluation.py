"""Runtime bindings and checked evaluation for verified relation plans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import cast

from scopecat.compiler.relations.analysis import PlanNode
from scopecat.compiler.relations.model import (
    CellValue,
    RelationExpr,
    Row,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
)
from scopecat.compiler.relations.scalar_eval import (
    cell_matches,
    is_cell_value,
    read_path,
)
from scopecat.compiler.relations.verification import (
    ExternalRowRequirement,
    PlanImportNamespace,
    RowType,
    TypedPlanImport,
    VerifiedRelationPlan,
)
from scopecat.kernel.value_types import (
    Record,
    Scalar,
    Series,
    Table,
    TableColumn,
    ValueType,
)
from scopecat.kernel.value_validation import (
    ValueValidationError,
    coerce_literal,
    validate_literal,
)


class ParameterRelationData:
    """Resolved immutable parameter bindings for relation evaluation.

    Config resolution establishes the value-level invariants before building this
    object. This class owns detached containers, enforces the unified parameter
    namespace, and returns a new binding set for lexical point overrides.
    """

    __slots__ = ("_scalars", "_series", "_tables")

    _scalars: dict[str, CellValue]
    _series: dict[str, tuple[CellValue, ...]]
    _tables: dict[str, tuple[Row, ...]]

    def __init__(
        self,
        *,
        scalars: Mapping[str, CellValue] | None = None,
        series: Mapping[str, Sequence[CellValue]] | None = None,
        tables: Mapping[str, Sequence[Mapping[str, CellValue]]] | None = None,
    ) -> None:
        scalar_bindings = {} if scalars is None else dict(scalars)
        series_values = (
            {}
            if series is None
            else {
                parameter_id: tuple(values) for parameter_id, values in series.items()
            }
        )
        table_rows = (
            {}
            if tables is None
            else {
                table_id: tuple(dict(row) for row in rows)
                for table_id, rows in tables.items()
            }
        )
        collisions = sorted(
            (scalar_bindings.keys() & series_values.keys())
            | (scalar_bindings.keys() & table_rows.keys())
            | (series_values.keys() & table_rows.keys())
        )
        if collisions:
            msg = (
                "parameter ids must be unique across scalar, series, and table "
                f"shapes: {', '.join(collisions)}"
            )
            raise ValueError(msg)
        self._scalars = scalar_bindings
        self._series = series_values
        self._tables = table_rows

    def parameter_shape(self, parameter_id: str) -> str | None:
        """Return the stored shape for one parameter id, if present."""

        if parameter_id in self._scalars:
            return "scalar"
        if parameter_id in self._series:
            return "series"
        if parameter_id in self._tables:
            return "table"
        return None

    def snapshot_scalars(self) -> dict[str, CellValue]:
        """Return a detached mapping of all scalar bindings."""

        return dict(self._scalars)

    def snapshot_series(self) -> dict[str, list[CellValue]]:
        """Return detached sequences for all series bindings."""

        return {
            parameter_id: list(values) for parameter_id, values in self._series.items()
        }

    def snapshot_tables(self) -> dict[str, list[Row]]:
        """Return detached rows for all table bindings."""

        return {
            table_id: [dict(row) for row in rows]
            for table_id, rows in self._tables.items()
        }

    def scalar(self, parameter_id: str) -> CellValue:
        try:
            return self._scalars[parameter_id]
        except KeyError as error:
            msg = f"unknown scalar parameter {parameter_id!r}"
            raise KeyError(msg) from error

    def value(self, parameter_id: str) -> object:
        if parameter_id in self._scalars:
            return self._scalars[parameter_id]
        if parameter_id in self._series:
            return list(self._series[parameter_id])
        if parameter_id in self._tables:
            return [dict(row) for row in self._tables[parameter_id]]
        msg = f"unknown parameter {parameter_id!r}"
        raise KeyError(msg)

    def table_rows(self, table_id: str) -> list[Row]:
        try:
            return [dict(row) for row in self._tables[table_id]]
        except KeyError as error:
            msg = f"unknown parameter table {table_id!r}"
            raise KeyError(msg) from error

    def series_values(self, parameter_id: str) -> list[CellValue]:
        try:
            return list(self._series[parameter_id])
        except KeyError as error:
            msg = f"unknown series parameter {parameter_id!r}"
            raise KeyError(msg) from error

    def with_table_cell(
        self,
        table_id: str,
        *,
        row_index: int,
        column_id: str,
        value: CellValue,
    ) -> ParameterRelationData:
        """Return bindings with one table cell lexically overridden."""

        try:
            rows = self._tables[table_id]
        except KeyError as error:
            msg = f"unknown parameter table {table_id!r}"
            raise KeyError(msg) from error
        if row_index < 0 or row_index >= len(rows):
            msg = f"parameter table {table_id!r} has no row {row_index}"
            raise IndexError(msg)
        row = rows[row_index]
        if column_id not in row:
            msg = (
                f"parameter table {table_id!r} row does not contain "
                f"column {column_id!r}"
            )
            raise KeyError(msg)
        updated_row = dict(row)
        updated_row[column_id] = value
        return ParameterRelationData(
            scalars=self._scalars,
            series=self._series,
            tables={
                **self._tables,
                table_id: (
                    *rows[:row_index],
                    updated_row,
                    *rows[row_index + 1 :],
                ),
            },
        )

    def lookup_row(self, table_id: str, key: Mapping[str, CellValue]) -> Row:
        matches = [
            row
            for row in self.table_rows(table_id)
            if all(
                cell_matches(row.get(column), value) for column, value in key.items()
            )
        ]
        if len(matches) != 1:
            msg = f"{table_id!r} key {dict(key)!r} matched {len(matches)} rows"
            raise ValueError(msg)
        return matches[0]

    def to_context(
        self,
        *,
        row: Row | None = None,
        outer_row: Row | None = None,
        point_row: Row | None = None,
        row_scopes: Mapping[RowScopeId, Row] | None = None,
        inputs: Mapping[str, object] | None = None,
    ) -> EvalContext:
        return EvalContext(
            params=self,
            row=row,
            outer_row=outer_row,
            point_row=point_row or {},
            row_scopes=dict(row_scopes or {}),
            inputs=dict(inputs or {}),
        )


@dataclass(slots=True)
class EvalContext:
    """Closed bindings for one relation evaluation.

    ``row`` is the current relation-row scope, ``outer_row`` is an explicit
    lexical/lateral parent, and ``point_row`` is the experiment point.  They
    never fall back to one another by name.
    """

    params: ParameterRelationData = field(default_factory=ParameterRelationData)
    row: Row | None = None
    outer_row: Row | None = None
    point_row: Row = field(default_factory=dict)
    row_scopes: dict[RowScopeId, Row] = field(default_factory=dict)
    inputs: dict[str, object] = field(default_factory=dict)


def evaluate_scalar(
    verified_plan: VerifiedRelationPlan[ScalarExpr],
    ctx: EvalContext,
) -> CellValue:
    from scopecat.compiler.relations.evaluator import evaluate_scalar_expression

    normalized = _prepare_context(verified_plan, ctx)
    result = evaluate_scalar_expression(verified_plan.root, normalized)
    return cast(
        "CellValue",
        _normalize_materialized_result(verified_plan.certified_type, result),
    )


def evaluate_series(
    verified_plan: VerifiedRelationPlan[SeriesExpr],
    ctx: EvalContext,
) -> list[CellValue]:
    from scopecat.compiler.relations.evaluator import evaluate_series_expression

    normalized = _prepare_context(verified_plan, ctx)
    result = evaluate_series_expression(verified_plan.root, normalized)
    return cast(
        "list[CellValue]",
        _normalize_materialized_result(verified_plan.certified_type, result),
    )


def evaluate_relation_in_context(
    verified_plan: VerifiedRelationPlan[RelationExpr],
    ctx: EvalContext,
) -> list[Row]:
    from scopecat.compiler.relations.evaluator import evaluate_relation_expression

    normalized = _prepare_context(verified_plan, ctx)
    result = evaluate_relation_expression(verified_plan.root, normalized)
    return cast(
        "list[Row]",
        _normalize_materialized_result(verified_plan.certified_type, result),
    )


def evaluate_relation_ordinals(
    verified_plan: VerifiedRelationPlan[RelationExpr],
    ctx: EvalContext,
    ordinals: Sequence[int],
    *,
    max_points: int,
) -> list[Row]:
    """Evaluate a canonical finite ordinal selection under an explicit budget."""

    selected = tuple(ordinals)
    if type(max_points) is not int or max_points <= 0:
        raise ValueError("relation ordinal budget must be a positive integer")
    if len(selected) > max_points:
        raise ValueError("relation ordinal selection exceeds the requested budget")
    if selected != tuple(sorted(set(selected))) or any(
        ordinal < 0 for ordinal in selected
    ):
        msg = "relation ordinals must be unique, non-negative, and canonical"
        raise ValueError(msg)
    from scopecat.compiler.relations.evaluator import (
        evaluate_relation_expression_ordinals,
    )

    normalized = _prepare_context(verified_plan, ctx)
    result = evaluate_relation_expression_ordinals(
        verified_plan.root,
        normalized,
        selected,
    )
    certified = cast("Table", verified_plan.certified_type)
    selected_type = replace(
        certified,
        min_rows=len(selected),
        max_rows=len(selected),
    )
    return cast(
        "list[Row]",
        _normalize_materialized_result(selected_type, result),
    )


def evaluate_relation(
    verified_plan: VerifiedRelationPlan[RelationExpr],
    params: ParameterRelationData | None = None,
    *,
    row: Row | None = None,
    outer_row: Row | None = None,
    point_row: Row | None = None,
    row_scopes: Mapping[RowScopeId, Row] | None = None,
    inputs: Mapping[str, object] | None = None,
) -> list[Row]:
    return evaluate_relation_in_context(
        verified_plan,
        EvalContext(
            params=params or ParameterRelationData(),
            row=row,
            outer_row=outer_row,
            point_row=point_row or {},
            row_scopes=dict(row_scopes or {}),
            inputs=dict(inputs or {}),
        ),
    )


def validate_relation_parameter_import[NodeT: PlanNode](
    verified_plan: VerifiedRelationPlan[NodeT],
    imported: TypedPlanImport,
    params: ParameterRelationData,
) -> None:
    """Validate one used parameter import without evaluating its plan.

    Compiler linking uses the same contract check as runtime dispatch so an
    accepted configuration cannot become a late missing-parameter or
    parameter-type failure merely because no relation has been evaluated yet.
    """

    if imported not in verified_plan.imports:
        msg = "parameter import is not owned by the supplied relation proof"
        raise ValueError(msg)
    _validate_parameter_import(imported, verified_plan, params)


def _prepare_context[NodeT: PlanNode](
    verified_plan: VerifiedRelationPlan[NodeT],
    ctx: EvalContext,
) -> EvalContext:
    return _normalize_evaluation_context(verified_plan, ctx)


def _validate_parameter_import[NodeT: PlanNode](
    imported: TypedPlanImport,
    verified_plan: VerifiedRelationPlan[NodeT],
    params: ParameterRelationData,
) -> None:
    if imported.namespace is not PlanImportNamespace.PARAMETER:
        msg = "parameter import validation requires the parameter namespace"
        raise ValueError(msg)
    if imported.lookup is not None:
        _validate_lookup_parameter(imported, verified_plan, params)
        return
    path = ("parameters", imported.id)
    try:
        value = params.value(imported.id)
    except (KeyError, TypeError) as error:
        raise ValueValidationError(
            path,
            str(error),
            code="unknown_parameter",
        ) from error
    validate_literal(imported.value_type, value, path=path)


def _input_import_value(
    inputs: Mapping[str, object],
    imported: TypedPlanImport,
) -> object:
    if isinstance(imported.value_type, Scalar):
        return read_path(inputs, imported.id)
    try:
        return inputs[imported.id]
    except KeyError as error:
        shape = "series" if isinstance(imported.value_type, Series) else "table"
        msg = f"unknown {shape} input {imported.id!r}"
        raise KeyError(msg) from error


def _validate_lookup_parameter[NodeT: PlanNode](
    imported: TypedPlanImport,
    verified_plan: VerifiedRelationPlan[NodeT],
    params: ParameterRelationData,
) -> None:
    lookup = imported.lookup
    if lookup is None:
        raise AssertionError("lookup import is unexpectedly missing its signature")
    path = ("parameters", imported.id)
    try:
        rows = params.table_rows(imported.id)
    except KeyError as error:
        actual_shape = params.parameter_shape(imported.id)
        if actual_shape is not None:
            raise ValueValidationError(
                path,
                f"expected table parameter, got {actual_shape}",
            ) from error
        raise ValueValidationError(
            path,
            str(error),
            code="unknown_parameter",
        ) from error

    declared = verified_plan.bindings.parameters.get(imported.id)
    if isinstance(declared, Table):
        validate_literal(declared, rows, path=path)
        return

    for index, row in enumerate(rows):
        result_path = (*path, index, lookup.column_id)
        try:
            value = read_path(row, lookup.column_id)
        except (KeyError, TypeError) as error:
            raise ValueValidationError(result_path, str(error)) from error
        validate_literal(lookup.result_type, value, path=result_path)


def _normalize_evaluation_context[NodeT: PlanNode](
    verified_plan: VerifiedRelationPlan[NodeT],
    ctx: EvalContext,
) -> EvalContext:
    """Snapshot and normalize every dynamic value the proof actually consumes."""

    inputs: dict[str, object] = dict(ctx.inputs)
    parameter_scalars = ctx.params.snapshot_scalars()
    parameter_series = ctx.params.snapshot_series()
    tables_by_parameter = ctx.params.snapshot_tables()

    for imported in verified_plan.imports:
        path = (imported.namespace.value + "s", imported.id)
        if imported.namespace is PlanImportNamespace.INPUT:
            try:
                value = _input_import_value(inputs, imported)
            except (KeyError, TypeError) as error:
                raise ValueValidationError(path, str(error)) from error
            normalized = _normalize_typed_value(
                imported.value_type,
                value,
                path=path,
            )
            inputs = _replace_path_value(inputs, imported.id, normalized)
            continue
        if imported.lookup is not None:
            tables_by_parameter[imported.id] = _normalize_lookup_rows(
                imported,
                verified_plan,
                ctx.params,
                path=path,
            )
            continue

        try:
            value = ctx.params.value(imported.id)
        except (KeyError, TypeError) as error:
            raise ValueValidationError(
                path,
                str(error),
                code="unknown_parameter",
            ) from error
        normalized = _normalize_typed_value(
            imported.value_type,
            value,
            path=path,
        )
        if isinstance(imported.value_type, Scalar):
            parameter_scalars[imported.id] = cast("CellValue", normalized)
        elif isinstance(imported.value_type, Series):
            parameter_series[imported.id] = cast("list[CellValue]", normalized)
        else:
            tables_by_parameter[imported.id] = cast("list[Row]", normalized)

    row_interface = verified_plan.external_row_interface
    row = _normalize_external_row(
        row_interface.current,
        ctx.row,
        path=("rows", "current"),
    )
    outer_row = _normalize_external_row(
        row_interface.outer,
        ctx.outer_row,
        path=("rows", "outer"),
    )
    row_scopes = {scope_id: dict(value) for scope_id, value in ctx.row_scopes.items()}
    for argument in row_interface.arguments:
        normalized_row = _normalize_external_row(
            argument.requirement,
            row_scopes.get(argument.row_scope_id),
            path=("rows", argument.row_scope_id.qualified_name),
        )
        if normalized_row is not None:
            row_scopes[argument.row_scope_id] = normalized_row

    point_row = (
        _normalize_external_row(
            row_interface.point,
            ctx.point_row,
            path=("rows", "point"),
        )
        if row_interface.point is not None
        else {}
    )
    if point_row is None:
        raise ValueValidationError(
            ("rows", "point"),
            "required row binding is missing",
        )

    return EvalContext(
        params=ParameterRelationData(
            scalars=parameter_scalars,
            series=parameter_series,
            tables=tables_by_parameter,
        ),
        row=row,
        outer_row=outer_row,
        point_row=point_row,
        row_scopes=row_scopes,
        inputs=inputs,
    )


def _normalize_lookup_rows[NodeT: PlanNode](
    imported: TypedPlanImport,
    verified_plan: VerifiedRelationPlan[NodeT],
    params: ParameterRelationData,
    *,
    path: tuple[str, str],
) -> list[Row]:
    try:
        rows = params.table_rows(imported.id)
    except KeyError as error:
        actual_shape = params.parameter_shape(imported.id)
        if actual_shape is not None:
            raise ValueValidationError(
                path,
                f"expected table parameter, got {actual_shape}",
            ) from error
        raise ValueValidationError(
            path,
            str(error),
            code="unknown_parameter",
        ) from error

    declared = verified_plan.bindings.parameters.get(imported.id)
    if isinstance(declared, Table):
        return cast(
            "list[Row]",
            _normalize_typed_value(declared, rows, path=path),
        )

    lookup = imported.lookup
    if lookup is None:
        raise AssertionError("lookup import is unexpectedly missing its signature")
    normalized_rows: list[Row] = []
    for index, row in enumerate(rows):
        result_path = (*path, index, lookup.column_id)
        try:
            value = read_path(row, lookup.column_id)
        except (KeyError, TypeError) as error:
            raise ValueValidationError(result_path, str(error)) from error
        normalized = _normalize_typed_value(
            lookup.result_type,
            value,
            path=result_path,
        )
        normalized_rows.append(
            cast("Row", _replace_path_value(row, lookup.column_id, normalized))
        )
    return normalized_rows


def _replace_path_value(
    source: Mapping[str, object],
    path: str,
    value: object,
) -> dict[str, object]:
    selected: dict[str, object] = dict(source)
    if path in selected:
        selected[path] = value
        return selected

    parts = path.split(".")
    current = selected
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, Mapping):
            raise AssertionError(f"validated path {path!r} is unexpectedly absent")
        nested_copy: dict[str, object] = dict(cast("Mapping[str, object]", nested))
        current[part] = nested_copy
        current = nested_copy
    current[parts[-1]] = value
    return selected


def _normalize_external_row(
    requirement: ExternalRowRequirement | None,
    row: Row | None,
    *,
    path: tuple[str, str],
) -> Row | None:
    if requirement is None:
        return dict(row) if row is not None else None
    if requirement.requires_full_row:
        if row is None:
            raise ValueValidationError(path, "required row binding is missing")
        return _normalize_full_row_role(requirement.row_type, row, path=path)
    return _normalize_row_role(
        requirement.row_type,
        row,
        set(requirement.column_references),
        path=path,
    )


def _normalize_row_role(
    row_type: RowType | None,
    row: Row | None,
    references: set[str],
    *,
    path: tuple[str, str],
) -> Row | None:
    if row_type is None or not references:
        return dict(row) if row is not None else None
    columns = _referenced_row_columns(row_type, references)
    if not columns:
        return dict(row) if row is not None else None
    if row is None:
        raise ValueValidationError(path, "required row binding is missing")
    contract = Table(
        columns,
        min_rows=1,
        max_rows=1,
        allow_extra_columns=True,
    )
    normalized = _restore_runtime_collection_carriers(
        contract,
        coerce_literal(contract, [row], path=path),
    )
    return cast("list[Row]", normalized)[0]


def _normalize_full_row_role(
    row_type: RowType,
    row: Row,
    *,
    path: tuple[str, str],
) -> Row:
    contract = Table(
        row_type.columns,
        min_rows=1,
        max_rows=1,
        allow_extra_columns=row_type.allow_extra_columns,
    )
    normalized = cast(
        "list[Row]",
        _normalize_typed_value(contract, [row], path=path),
    )
    return normalized[0]


def _referenced_row_columns(
    row_type: RowType,
    references: set[str],
) -> tuple[TableColumn, ...]:
    columns = {column.id: column for column in row_type.columns}
    selected: set[str] = set()
    for reference in references:
        if reference in columns:
            selected.add(reference)
            continue
        root = reference.split(".", maxsplit=1)[0]
        if root in columns:
            selected.add(root)
    return tuple(column for column in row_type.columns if column.id in selected)


def _normalize_materialized_result(
    value_type: ValueType,
    value: object,
) -> CellValue | list[CellValue] | list[Row]:
    """Normalize a result and enforce its runtime carrier contract."""

    return _normalize_typed_value(value_type, value, path=("result",))


def _normalize_typed_value(
    value_type: ValueType,
    value: object,
    *,
    path: tuple[str | int, ...],
) -> CellValue | list[CellValue] | list[Row]:
    normalized = _restore_runtime_collection_carriers(
        value_type,
        coerce_literal(value_type, value, path=path),
    )
    if isinstance(value_type, Scalar):
        if not is_cell_value(normalized):
            raise ValueValidationError(
                path,
                f"unsupported scalar runtime value {normalized!r}",
            )
        return normalized
    if isinstance(value_type, Series):
        items = list(cast("tuple[object, ...]", normalized))
        for index, item in enumerate(items):
            if not is_cell_value(item):
                raise ValueValidationError(
                    (*path, index),
                    f"unsupported series runtime value {item!r}",
                )
        return cast("list[CellValue]", items)

    rows = list(cast("tuple[dict[str, object], ...]", normalized))
    for index, row in enumerate(rows):
        for column_id, item in row.items():
            if not is_cell_value(item):
                raise ValueValidationError(
                    (*path, index, column_id),
                    f"unsupported table runtime cell {item!r}",
                )
    return cast("list[Row]", rows)


def _restore_runtime_collection_carriers(
    value_type: ValueType,
    value: object,
) -> object:
    """Use mutable runtime collections while retaining normalized scalar atoms."""

    if isinstance(value_type, Scalar):
        if not isinstance(value_type.atom, Record) or not isinstance(value, dict):
            return value
        selected = dict(cast("dict[str, object]", value))
        for field in value_type.atom.fields:
            if field.id in selected:
                selected[field.id] = _restore_runtime_collection_carriers(
                    field.value_type,
                    selected[field.id],
                )
        return selected
    if isinstance(value_type, Series):
        return [
            _restore_runtime_collection_carriers(value_type.item_type, item)
            for item in cast("tuple[object, ...]", value)
        ]

    selected_rows: list[dict[str, object]] = []
    columns = {column.id: column for column in value_type.columns}
    for row in cast("tuple[dict[str, object], ...]", value):
        selected = dict(row)
        for column_id, column in columns.items():
            if column_id in selected:
                selected[column_id] = _restore_runtime_collection_carriers(
                    column.value_type,
                    selected[column_id],
                )
        selected_rows.append(selected)
    return selected_rows
