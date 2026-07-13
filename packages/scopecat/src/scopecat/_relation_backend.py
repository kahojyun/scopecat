"""Explicit backend boundary for backend-neutral relation plans.

Plan nodes live in :mod:`scopecat._relations` and contain no execution policy.
This module owns runtime bindings, capability selection, and the deterministic
Python implementation used as Scopecat's reference semantics.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cmp_to_key
from itertools import product
from typing import Any, Protocol, cast, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat._relation_analysis import (
    PlanNode,
    RelationOperation,
    verify_plan_scopes,
)
from scopecat._relation_scalar_eval import eval_binary, is_cell_value, read_path
from scopecat._relation_verification import (
    ExternalRowInterface,
    ExternalRowRequirement,
    PlanImportNamespace,
    PlanPath,
    PlanTypeFact,
    RelationRuntimeObligationKind,
    RowType,
    RuntimeObligation,
    TypedPlanImport,
    VerifiedRelationPlan,
)
from scopecat._relations import (
    CellValue,
    GridColumn,
    RelationExpr,
    Row,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
)
from scopecat._scalar_operators import compare_ordered_values, runtime_values_equal
from scopecat.models.entity import EntityRef, same_entity_identity
from scopecat.models.parameter import Quantity
from scopecat.value_types import Record, Scalar, Series, Table, TableColumn, ValueType
from scopecat.value_validation import (
    ValueValidationError,
    coerce_literal,
    validate_literal,
)


class ParameterRelationData(BaseModel):
    """Resolved scalar, series, and table imports for relation materialization."""

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    scalars: dict[str, CellValue] = Field(default_factory=dict)
    series: dict[str, list[CellValue]] = Field(default_factory=dict)
    tables: dict[str, list[Row]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unified_namespace(self) -> ParameterRelationData:
        collisions = sorted(
            (self.scalars.keys() & self.series.keys())
            | (self.scalars.keys() & self.tables.keys())
            | (self.series.keys() & self.tables.keys())
        )
        if collisions:
            msg = (
                "parameter ids must be unique across scalar, series, and table "
                f"shapes: {', '.join(collisions)}"
            )
            raise ValueError(msg)
        return self

    def scalar(self, parameter_id: str) -> CellValue:
        try:
            return self.scalars[parameter_id]
        except KeyError as error:
            msg = f"unknown scalar parameter {parameter_id!r}"
            raise KeyError(msg) from error

    def value(self, parameter_id: str) -> object:
        if parameter_id in self.scalars:
            return self.scalars[parameter_id]
        if parameter_id in self.series:
            return list(self.series[parameter_id])
        if parameter_id in self.tables:
            return [dict(row) for row in self.tables[parameter_id]]
        msg = f"unknown parameter {parameter_id!r}"
        raise KeyError(msg)

    def table_rows(self, table_id: str) -> list[Row]:
        try:
            return [dict(row) for row in self.tables[table_id]]
        except KeyError as error:
            msg = f"unknown parameter table {table_id!r}"
            raise KeyError(msg) from error

    def series_values(self, parameter_id: str) -> list[CellValue]:
        try:
            return list(self.series[parameter_id])
        except KeyError as error:
            msg = f"unknown series parameter {parameter_id!r}"
            raise KeyError(msg) from error

    def lookup_row(self, table_id: str, key: Mapping[str, CellValue]) -> Row:
        matches = [
            row
            for row in self.table_rows(table_id)
            if all(
                _cell_matches(row.get(column), value) for column, value in key.items()
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


class EvalContext(BaseModel):
    """Closed bindings for one backend evaluation.

    ``row`` is the current relation-row scope, ``outer_row`` is an explicit
    lexical/lateral parent, and ``point_row`` is the experiment point.  They
    never fall back to one another by name.
    """

    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    params: ParameterRelationData = Field(default_factory=ParameterRelationData)
    row: Row | None = None
    outer_row: Row | None = None
    point_row: Row = Field(default_factory=dict)
    row_scopes: dict[RowScopeId, Row] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)


class RelationBackendCapabilityDimension(StrEnum):
    """Orthogonal dimensions on which backend selection can reject a plan."""

    OPERATION = "operation"
    ROW_INTERFACE = "row_interface"
    RUNTIME_OBLIGATION = "runtime_obligation"
    TYPE_REQUIREMENT = "type_requirement"


@dataclass(frozen=True, slots=True)
class RelationBackendCapabilityIssue:
    """One structured reason a verified plan cannot target a backend."""

    dimension: RelationBackendCapabilityDimension
    code: str
    path: PlanPath
    message: str


@dataclass(frozen=True, slots=True)
class RelationPlanRequirements:
    """The backend-facing static projection of one relation proof."""

    certified_type: ValueType
    node_type_facts: tuple[PlanTypeFact, ...]
    typed_imports: tuple[TypedPlanImport, ...]
    external_row_interface: ExternalRowInterface
    required_operations: tuple[RelationOperation, ...]
    runtime_obligations: tuple[RuntimeObligation, ...]

    @classmethod
    def from_verified(
        cls,
        verified_plan: VerifiedRelationPlan[PlanNode],
    ) -> RelationPlanRequirements:
        return cls(
            certified_type=verified_plan.certified_type,
            node_type_facts=verified_plan.facts,
            typed_imports=verified_plan.imports,
            external_row_interface=verified_plan.external_row_interface,
            required_operations=verified_plan.required_operations,
            runtime_obligations=verified_plan.runtime_obligations,
        )


class RelationBackendCapabilityError(ValueError):
    """A selected backend cannot implement a verified plan's requirements."""

    def __init__(
        self,
        backend_id: str,
        issues: Sequence[RelationBackendCapabilityIssue],
    ) -> None:
        self.backend_id = backend_id
        self.issues = tuple(issues)
        rendered = "; ".join(
            f"{issue.dimension.value}:{issue.code} ({issue.message})"
            for issue in self.issues
        )
        super().__init__(f"relation backend {backend_id!r} rejected plan: {rendered}")


@runtime_checkable
class RelationBackend(Protocol):
    """Implementation selected by compiler policy for one verified plan."""

    @property
    def backend_id(self) -> str: ...

    @property
    def supported_operations(self) -> frozenset[RelationOperation]: ...

    @property
    def discharged_obligations(
        self,
    ) -> frozenset[RelationRuntimeObligationKind]: ...

    def assess_relation_requirements(
        self,
        requirements: RelationPlanRequirements,
    ) -> Sequence[RelationBackendCapabilityIssue]: ...

    def materialize_scalar(
        self,
        evaluation: PreparedRelationEvaluation[ScalarExpr],
    ) -> CellValue: ...

    def materialize_series(
        self,
        evaluation: PreparedRelationEvaluation[SeriesExpr],
    ) -> list[CellValue]: ...

    def materialize_relation(
        self,
        evaluation: PreparedRelationEvaluation[RelationExpr],
    ) -> list[Row]: ...


_SELECTED_PLAN_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class SelectedRelationPlan[NodeT: PlanNode]:
    """A verified plan whose operations are supported by one backend.

    Construction is sealed behind :func:`select_relation_plan`.  The selected
    backend is represented by its stable public identity; the enclosed proof
    retains the defensive-copy guarantees of :class:`VerifiedRelationPlan`.
    """

    backend_id: str
    _verified_plan: VerifiedRelationPlan[NodeT]

    def __init__(
        self,
        backend_id: str,
        verified_plan: VerifiedRelationPlan[NodeT],
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _SELECTED_PLAN_TOKEN:
            msg = "SelectedRelationPlan can only be created by select_relation_plan"
            raise TypeError(msg)
        object.__setattr__(self, "backend_id", backend_id)
        object.__setattr__(self, "_verified_plan", verified_plan)

    @property
    def verified_plan(self) -> VerifiedRelationPlan[NodeT]:
        return self._verified_plan

    @property
    def root(self) -> NodeT:
        """Return a defensive copy of the selected plan root."""

        return self._verified_plan.root

    @property
    def certified_type(self) -> ValueType:
        return self._verified_plan.certified_type

    @property
    def required_operations(self) -> tuple[RelationOperation, ...]:
        return self._verified_plan.required_operations

    @property
    def requirements(self) -> RelationPlanRequirements:
        return RelationPlanRequirements.from_verified(self._verified_plan)

    def _unwrap_for_backend(self, backend: RelationBackend) -> NodeT:
        """Internal dispatch hook for proof-requiring evaluators."""

        return _unwrap_selected_plan(backend, self)


_PREPARED_EVALUATION_TOKEN = object()


@dataclass(frozen=True, slots=True, init=False)
class PreparedRelationEvaluation[NodeT: PlanNode]:
    """A selected plan paired with a context validated against its proof."""

    _selected_plan: SelectedRelationPlan[NodeT]
    context: EvalContext

    def __init__(
        self,
        selected_plan: SelectedRelationPlan[NodeT],
        context: EvalContext,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _PREPARED_EVALUATION_TOKEN:
            msg = (
                "PreparedRelationEvaluation can only be created by the "
                "validated evaluation boundary"
            )
            raise TypeError(msg)
        object.__setattr__(self, "_selected_plan", selected_plan)
        object.__setattr__(self, "context", context)

    @property
    def certified_type(self) -> ValueType:
        return self._selected_plan.certified_type

    @property
    def selected_plan(self) -> SelectedRelationPlan[NodeT]:
        return self._selected_plan


def select_relation_plan[NodeT: PlanNode](
    backend: RelationBackend,
    verified_plan: VerifiedRelationPlan[NodeT],
) -> SelectedRelationPlan[NodeT]:
    """Bind a static relation proof to a backend capability set."""

    if not isinstance(cast("object", verified_plan), VerifiedRelationPlan):
        msg = "backend selection requires a VerifiedRelationPlan"
        raise TypeError(msg)
    issues = assess_relation_plan(backend, verified_plan)
    if issues:
        raise RelationBackendCapabilityError(backend.backend_id, issues)
    return SelectedRelationPlan[NodeT](
        backend.backend_id,
        verified_plan,
        _token=_SELECTED_PLAN_TOKEN,
    )


def _unwrap_selected_plan[NodeT: PlanNode](
    backend: RelationBackend,
    selected_plan: SelectedRelationPlan[NodeT],
) -> NodeT:
    """Recover a defensive root for a backend-bound evaluator dispatch."""

    if not isinstance(cast("object", selected_plan), SelectedRelationPlan):
        msg = "backend evaluation requires a SelectedRelationPlan"
        raise TypeError(msg)
    if selected_plan.backend_id != backend.backend_id:
        msg = (
            f"relation plan selected for backend {selected_plan.backend_id!r} "
            f"cannot be evaluated by backend {backend.backend_id!r}"
        )
        raise ValueError(msg)
    issues = assess_relation_plan(backend, selected_plan.verified_plan)
    if issues:
        raise RelationBackendCapabilityError(backend.backend_id, issues)
    return selected_plan.root


def assess_relation_plan[NodeT: PlanNode](
    backend: RelationBackend,
    verified_plan: VerifiedRelationPlan[NodeT],
) -> tuple[RelationBackendCapabilityIssue, ...]:
    """Return every stable reason a backend rejects a verified plan."""

    requirements = RelationPlanRequirements.from_verified(verified_plan)
    operation_issues = tuple(
        RelationBackendCapabilityIssue(
            dimension=RelationBackendCapabilityDimension.OPERATION,
            code=fact.operation.value,
            path=fact.path,
            message=f"operation {fact.operation.value!r} is unsupported",
        )
        for fact in requirements.node_type_facts
        if fact.operation not in backend.supported_operations
    )
    obligation_issues = tuple(
        RelationBackendCapabilityIssue(
            dimension=RelationBackendCapabilityDimension.RUNTIME_OBLIGATION,
            code=obligation.code.value,
            path=obligation.path,
            message=f"runtime obligation {obligation.code.value!r} is not discharged",
        )
        for obligation in requirements.runtime_obligations
        if obligation.code not in backend.discharged_obligations
    )
    type_issues = tuple(backend.assess_relation_requirements(requirements))
    return (*operation_issues, *obligation_issues, *type_issues)


def evaluate_scalar(
    backend: RelationBackend,
    selected_plan: SelectedRelationPlan[ScalarExpr],
    ctx: EvalContext,
) -> CellValue:
    evaluation = _prepare_evaluation(backend, selected_plan, ctx)
    result = backend.materialize_scalar(evaluation)
    return cast(
        "CellValue",
        _normalize_materialized_result(evaluation.certified_type, result),
    )


def evaluate_series(
    backend: RelationBackend,
    selected_plan: SelectedRelationPlan[SeriesExpr],
    ctx: EvalContext,
) -> list[CellValue]:
    evaluation = _prepare_evaluation(backend, selected_plan, ctx)
    result = backend.materialize_series(evaluation)
    return cast(
        "list[CellValue]",
        _normalize_materialized_result(evaluation.certified_type, result),
    )


def evaluate_relation_in_context(
    backend: RelationBackend,
    selected_plan: SelectedRelationPlan[RelationExpr],
    ctx: EvalContext,
) -> list[Row]:
    evaluation = _prepare_evaluation(backend, selected_plan, ctx)
    result = backend.materialize_relation(evaluation)
    return cast(
        "list[Row]",
        _normalize_materialized_result(evaluation.certified_type, result),
    )


def evaluate_relation(
    backend: RelationBackend,
    selected_plan: SelectedRelationPlan[RelationExpr],
    params: ParameterRelationData | None = None,
    *,
    row: Row | None = None,
    outer_row: Row | None = None,
    point_row: Row | None = None,
    row_scopes: Mapping[RowScopeId, Row] | None = None,
    inputs: Mapping[str, object] | None = None,
) -> list[Row]:
    return evaluate_relation_in_context(
        backend,
        selected_plan,
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


def _validate_evaluation_context[NodeT: PlanNode](
    backend: RelationBackend,
    selected_plan: SelectedRelationPlan[NodeT],
    ctx: EvalContext,
) -> None:
    """Validate the dynamic lexical environment before backend dispatch."""

    expression = _unwrap_selected_plan(backend, selected_plan)
    verify_plan_scopes(
        expression,
        current_row_available=ctx.row is not None,
        outer_row_available=ctx.outer_row is not None,
        active_row_scopes=ctx.row_scopes,
    )
    _validate_used_imports(selected_plan.verified_plan, ctx)
    _validate_used_row_roles(selected_plan.verified_plan, ctx)


def _prepare_evaluation[NodeT: PlanNode](
    backend: RelationBackend,
    selected_plan: SelectedRelationPlan[NodeT],
    ctx: EvalContext,
) -> PreparedRelationEvaluation[NodeT]:
    _validate_evaluation_context(backend, selected_plan, ctx)
    normalized_context = _normalize_evaluation_context(
        selected_plan.verified_plan,
        ctx,
    )
    return PreparedRelationEvaluation(
        selected_plan,
        normalized_context,
        _token=_PREPARED_EVALUATION_TOKEN,
    )


def _unwrap_prepared_evaluation[NodeT: PlanNode](
    backend: RelationBackend,
    evaluation: PreparedRelationEvaluation[NodeT],
) -> tuple[NodeT, EvalContext]:
    if not isinstance(cast("object", evaluation), PreparedRelationEvaluation):
        msg = "backend materialization requires a PreparedRelationEvaluation"
        raise TypeError(msg)
    return (
        _unwrap_selected_plan(backend, evaluation.selected_plan),
        evaluation.context,
    )


def _validate_used_imports[NodeT: PlanNode](
    verified_plan: VerifiedRelationPlan[NodeT],
    ctx: EvalContext,
) -> None:
    for imported in verified_plan.imports:
        if imported.namespace is PlanImportNamespace.PARAMETER:
            _validate_parameter_import(imported, verified_plan, ctx.params)
            continue
        path = ("inputs", imported.id)
        try:
            value = _input_import_value(ctx.inputs, imported)
        except (KeyError, TypeError) as error:
            raise ValueValidationError(path, str(error)) from error
        validate_literal(imported.value_type, value, path=path)


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
        if imported.id in params.scalars or imported.id in params.series:
            actual_shape = "scalar" if imported.id in params.scalars else "series"
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

    inputs: dict[str, Any] = dict(ctx.inputs)
    parameter_scalars = dict(ctx.params.scalars)
    parameter_series = {
        parameter_id: list(values) for parameter_id, values in ctx.params.series.items()
    }
    tables_by_parameter = {
        parameter_id: [dict(row) for row in rows]
        for parameter_id, rows in ctx.params.tables.items()
    }

    for imported in verified_plan.imports:
        path = (imported.namespace.value + "s", imported.id)
        if imported.namespace is PlanImportNamespace.INPUT:
            value = _input_import_value(inputs, imported)
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
                tables_by_parameter[imported.id],
                path=path,
            )
            continue

        value = _parameter_value(
            imported.id,
            scalars=parameter_scalars,
            series=parameter_series,
            tables=tables_by_parameter,
        )
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
        raise AssertionError("validated point row is unexpectedly missing")

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
    rows: list[Row],
    *,
    path: tuple[str, str],
) -> list[Row]:
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
        value = read_path(row, lookup.column_id)
        normalized = _normalize_typed_value(
            lookup.result_type,
            value,
            path=(*path, index, lookup.column_id),
        )
        normalized_rows.append(
            cast("Row", _replace_path_value(row, lookup.column_id, normalized))
        )
    return normalized_rows


def _parameter_value(
    parameter_id: str,
    *,
    scalars: Mapping[str, CellValue],
    series: Mapping[str, list[CellValue]],
    tables: Mapping[str, list[Row]],
) -> object:
    if parameter_id in scalars:
        return scalars[parameter_id]
    if parameter_id in series:
        return series[parameter_id]
    if parameter_id in tables:
        return tables[parameter_id]
    raise AssertionError(f"validated parameter {parameter_id!r} is unexpectedly absent")


def _replace_path_value(
    source: Mapping[str, object],
    path: str,
    value: object,
) -> dict[str, Any]:
    selected: dict[str, Any] = dict(source)
    if path in selected:
        selected[path] = value
        return selected

    parts = path.split(".")
    current = selected
    for part in parts[:-1]:
        nested = current.get(part)
        if not isinstance(nested, Mapping):
            raise AssertionError(f"validated path {path!r} is unexpectedly absent")
        nested_copy: dict[str, Any] = dict(cast("Mapping[str, object]", nested))
        current[part] = nested_copy
        current = nested_copy
    current[parts[-1]] = value
    return selected


def _validate_used_row_roles[NodeT: PlanNode](
    verified_plan: VerifiedRelationPlan[NodeT],
    ctx: EvalContext,
) -> None:
    row_interface = verified_plan.external_row_interface
    _validate_external_row(
        row_interface.current,
        ctx.row,
        path=("rows", "current"),
    )
    _validate_external_row(
        row_interface.outer,
        ctx.outer_row,
        path=("rows", "outer"),
    )
    for argument in row_interface.arguments:
        _validate_external_row(
            argument.requirement,
            ctx.row_scopes.get(argument.row_scope_id),
            path=("rows", argument.row_scope_id.qualified_name),
        )
    _validate_external_row(
        row_interface.point,
        ctx.point_row,
        path=("rows", "point"),
    )


def _validate_external_row(
    requirement: ExternalRowRequirement | None,
    row: Row | None,
    *,
    path: tuple[str, str],
) -> None:
    if requirement is None:
        return
    if requirement.requires_full_row:
        if row is None:
            raise ValueValidationError(path, "required row binding is missing")
        _validate_full_row_role(requirement.row_type, row, path=path)
        return
    _validate_row_role(
        requirement.row_type,
        row,
        set(requirement.column_references),
        path=path,
    )


def _validate_row_role(
    row_type: RowType | None,
    row: Row | None,
    references: set[str],
    *,
    path: tuple[str, str],
) -> None:
    if row_type is None or not references:
        return
    columns = _referenced_row_columns(row_type, references)
    if not columns:
        return
    if row is None:
        raise ValueValidationError(path, "required row binding is missing")
    contract = Table(
        columns,
        min_rows=1,
        max_rows=1,
        allow_extra_columns=True,
    )
    validate_literal(contract, [row], path=path)


def _validate_full_row_role(
    row_type: RowType,
    row: Row,
    *,
    path: tuple[str, str],
) -> None:
    """Validate a row whose complete shape participates in an operation."""

    contract = Table(
        row_type.columns,
        min_rows=1,
        max_rows=1,
        allow_extra_columns=row_type.allow_extra_columns,
    )
    validate_literal(contract, [row], path=path)


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
            raise AssertionError("validated full row binding is unexpectedly missing")
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
    if row is None:
        return None
    selected: Row = dict(row)
    if row_type is None or not references:
        return selected
    for column in _referenced_row_columns(row_type, references):
        value = read_path(selected, column.id)
        normalized = _normalize_typed_value(
            column.value_type,
            value,
            path=(*path, column.id),
        )
        selected = cast(
            "Row",
            _replace_path_value(selected, column.id, normalized),
        )
    return selected


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
    """Normalize a backend result and enforce its runtime carrier contract."""

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


@dataclass(frozen=True, slots=True)
class ReferenceRelationBackend:
    """Deterministic Python implementation defining observable semantics."""

    backend_id: str = "reference.python"
    supported_operations: frozenset[RelationOperation] = frozenset(RelationOperation)
    discharged_obligations: frozenset[RelationRuntimeObligationKind] = frozenset(
        {
            RelationRuntimeObligationKind.DIVISION_RIGHT_NONZERO,
            RelationRuntimeObligationKind.NO_EXTRA_COLUMN_COLLISION,
            RelationRuntimeObligationKind.PARAMETER_LOOKUP_EXACTLY_ONE,
            RelationRuntimeObligationKind.RANGE_PROGRESS,
            RelationRuntimeObligationKind.RANGE_STEP_NONZERO,
            RelationRuntimeObligationKind.SCALAR_RESULT_FINITE,
            RelationRuntimeObligationKind.SERIES_VALUES_FINITE,
            RelationRuntimeObligationKind.ZIP_EQUAL_LENGTH,
        }
    )

    def assess_relation_requirements(
        self,
        requirements: RelationPlanRequirements,
    ) -> Sequence[RelationBackendCapabilityIssue]:
        """Accept every verified value type supported by Python containers."""

        _ = requirements
        return ()

    def materialize_scalar(
        self,
        evaluation: PreparedRelationEvaluation[ScalarExpr],
    ) -> CellValue:
        expression, ctx = _unwrap_prepared_evaluation(self, evaluation)
        return _evaluate_scalar(expression, ctx)

    def materialize_series(
        self,
        evaluation: PreparedRelationEvaluation[SeriesExpr],
    ) -> list[CellValue]:
        expression, ctx = _unwrap_prepared_evaluation(self, evaluation)
        return _evaluate_series(expression, ctx)

    def materialize_relation(
        self,
        evaluation: PreparedRelationEvaluation[RelationExpr],
    ) -> list[Row]:
        expression, ctx = _unwrap_prepared_evaluation(self, evaluation)
        return _evaluate_relation(expression, ctx)


REFERENCE_RELATION_BACKEND = ReferenceRelationBackend()


def _evaluate_scalar(expression: ScalarExpr, ctx: EvalContext) -> CellValue:
    if expression.kind == "literal":
        return expression.value
    if expression.kind == "column":
        row_scope_id = expression.row_scope_id
        row = ctx.row_scopes.get(row_scope_id) if row_scope_id is not None else ctx.row
        if row is None:
            scope_name = (
                row_scope_id.qualified_name
                if row_scope_id is not None
                else "<implicit-current-row>"
            )
            msg = f"row column references an inactive scope: {scope_name!r}"
            raise ValueError(msg)
        return read_path(row, _required(expression.name))
    if expression.kind == "outer_column":
        if ctx.outer_row is None:
            msg = f"outer column {_required(expression.name)!r} used outside scope"
            raise ValueError(msg)
        return read_path(ctx.outer_row, _required(expression.name))
    if expression.kind == "point_column":
        return read_path(ctx.point_row, _required(expression.name))
    if expression.kind == "input":
        return read_path(ctx.inputs, _required(expression.name))
    if expression.kind == "param_scalar":
        return ctx.params.scalar(_required(expression.name))
    if expression.kind == "param_lookup":
        resolved_key = {
            name: _evaluate_scalar(value, ctx)
            for name, value in _required(expression.key).items()
        }
        row = ctx.params.lookup_row(_required(expression.table_id), resolved_key)
        return read_path(row, _required(expression.column))
    if expression.kind == "binary":
        return eval_binary(
            _required(expression.op),
            _evaluate_scalar(_required(expression.left), ctx),
            _evaluate_scalar(_required(expression.right), ctx),
        )
    if expression.kind == "case":
        for branch in _required(expression.cases):
            if _evaluate_scalar(branch.condition, ctx) is True:
                return _evaluate_scalar(branch.value, ctx)
        return _evaluate_scalar(_required(expression.fallback), ctx)
    msg = f"unsupported scalar expression kind: {expression.kind}"
    raise ValueError(msg)


def _evaluate_series(expression: SeriesExpr, ctx: EvalContext) -> list[CellValue]:
    if expression.kind == "values":
        return list(_required(expression.items))
    if expression.kind == "linspace":
        count = _required(expression.count)
        start_value = _evaluate_scalar(_required(expression.start), ctx)
        stop_value = _evaluate_scalar(_required(expression.stop), ctx)
        unit = expression.unit or _quantity_unit(start_value)
        start = _series_float(start_value, unit=unit)
        stop = _series_float(stop_value, unit=unit)
        if count == 1:
            return _series_values([start], unit=unit)
        step_value = (stop - start) / (count - 1)
        return _series_values(
            [start + index * step_value for index in range(count)],
            unit=unit,
        )
    if expression.kind == "range":
        start_value = _evaluate_scalar(_required(expression.start), ctx)
        stop_value = _evaluate_scalar(_required(expression.stop), ctx)
        step_value = _evaluate_scalar(_required(expression.step), ctx)
        unit = expression.unit or _quantity_unit(start_value)
        start = _series_float(start_value, unit=unit)
        stop = _series_float(stop_value, unit=unit)
        step = _series_float(step_value, unit=unit)
        if step == 0:
            msg = "range step must not be zero"
            raise ValueError(msg)
        selected: list[float] = []
        current = start
        if step > 0:
            while current < stop or (
                expression.include_stop and _float_almost_equal(current, stop)
            ):
                selected.append(current)
                next_current = current + step
                if next_current == current:
                    msg = "range step is too small to advance the current value"
                    raise ValueError(msg)
                current = next_current
        else:
            while current > stop or (
                expression.include_stop and _float_almost_equal(current, stop)
            ):
                selected.append(current)
                next_current = current + step
                if next_current == current:
                    msg = "range step is too small to advance the current value"
                    raise ValueError(msg)
                current = next_current
        return _series_values(selected, unit=unit)
    if expression.kind == "input":
        return _input_series(ctx.inputs, _required(expression.name))
    if expression.kind == "param_series":
        return ctx.params.series_values(_required(expression.name))
    if expression.kind == "relation_column":
        return [
            read_path(row, _required(expression.column))
            for row in _evaluate_relation(_required(expression.source), ctx)
        ]
    if expression.kind == "relation_entities":
        entities: list[CellValue] = []
        for row in _evaluate_relation(_required(expression.source), ctx):
            for column in _required(expression.columns):
                value = read_path(row, column)
                if not any(_cell_matches(existing, value) for existing in entities):
                    entities.append(value)
        return entities
    msg = f"unsupported series kind: {expression.kind}"
    raise ValueError(msg)


def _evaluate_grid_column(column: GridColumn, ctx: EvalContext) -> list[CellValue]:
    if column.kind == "scalar":
        return [_evaluate_scalar(_required(column.scalar), ctx)]
    if column.kind == "series":
        return _evaluate_series(_required(column.series), ctx)
    if column.kind == "relation":
        return cast(
            "list[CellValue]",
            _evaluate_relation(_required(column.relation), ctx),
        )
    if column.kind == "values":
        return list(_required(column.values))
    msg = f"unsupported grid column kind: {column.kind}"
    raise ValueError(msg)


def _evaluate_relation(expression: RelationExpr, ctx: EvalContext) -> list[Row]:
    if expression.kind == "literal_rows":
        return [dict(row) for row in _required(expression.rows)]
    if expression.kind == "table":
        return ctx.params.table_rows(_required(expression.table_id))
    if expression.kind == "input":
        return _input_table(ctx.inputs, _required(expression.name))
    if expression.kind == "grid":
        names = tuple(_required(expression.columns))
        choices = [
            _evaluate_grid_column(_required(expression.columns)[name], ctx)
            for name in names
        ]
        return [dict(zip(names, values, strict=True)) for values in product(*choices)]
    if expression.kind == "select":
        return [
            {
                column: read_path(source_row, column)
                for column in _required(expression.select_columns)
            }
            for source_row in _evaluate_relation(_required(expression.source), ctx)
        ]
    if expression.kind == "filter":
        selected: list[Row] = []
        for source_row in _evaluate_relation(_required(expression.source), ctx):
            child_ctx = _child_context(
                ctx,
                row=source_row,
                row_scope_id=expression.row_scope_id,
            )
            if _evaluate_scalar(_required(expression.condition), child_ctx) is True:
                selected.append(source_row)
        return selected
    if expression.kind == "join":
        left_rows = _evaluate_relation(_required(expression.left), ctx)
        right_rows = _evaluate_relation(_required(expression.right), ctx)
        on = _required(expression.on)
        allowed_shared = {
            left_column
            for left_column, right_column in on.items()
            if left_column == right_column
        }
        _require_disjoint_row_columns(
            left_rows,
            right_rows,
            operation="join",
            allowed_shared=allowed_shared,
        )
        return [
            _merge_rows(
                left_row,
                right_row,
                operation="join",
                allowed_shared=allowed_shared,
            )
            for left_row in left_rows
            for right_row in right_rows
            if _join_keys_match(left_row, right_row, on)
        ]
    if expression.kind == "cross":
        left_rows = _evaluate_relation(_required(expression.left), ctx)
        right_rows = _evaluate_relation(_required(expression.right), ctx)
        _require_disjoint_row_columns(left_rows, right_rows, operation="cross")
        return [
            _merge_rows(left_row, right_row, operation="cross")
            for left_row in left_rows
            for right_row in right_rows
        ]
    if expression.kind == "lateral_cross":
        crossed: list[Row] = []
        for left_row in _evaluate_relation(_required(expression.left), ctx):
            right_rows = _evaluate_relation(
                _required(expression.right),
                EvalContext(
                    params=ctx.params,
                    row=left_row,
                    outer_row=left_row,
                    point_row=ctx.point_row,
                    row_scopes=ctx.row_scopes,
                    inputs=ctx.inputs,
                ),
            )
            _require_disjoint_row_columns(
                [left_row],
                right_rows,
                operation="lateral_cross",
            )
            crossed.extend(
                _merge_rows(left_row, right_row, operation="lateral_cross")
                for right_row in right_rows
            )
        return crossed
    if expression.kind == "point_cross":
        crossed = []
        for left_row in _evaluate_relation(_required(expression.left), ctx):
            point_row = (
                _merge_rows(ctx.point_row, left_row, operation="point_cross")
                if ctx.point_row
                else left_row
            )
            right_rows = _evaluate_relation(
                _required(expression.right),
                EvalContext(
                    params=ctx.params,
                    row=ctx.row,
                    outer_row=ctx.outer_row,
                    point_row=point_row,
                    row_scopes=ctx.row_scopes,
                    inputs=ctx.inputs,
                ),
            )
            _require_disjoint_row_columns(
                [left_row],
                right_rows,
                operation="point_cross",
            )
            crossed.extend(
                _merge_rows(left_row, right_row, operation="point_cross")
                for right_row in right_rows
            )
        return crossed
    if expression.kind == "zip":
        rows_by_source = [
            _evaluate_relation(source, ctx) for source in _required(expression.sources)
        ]
        lengths = {len(rows) for rows in rows_by_source}
        if len(lengths) != 1:
            msg = "zip relation requires sources with equal length"
            raise ValueError(msg)
        zipped: list[Row] = []
        for row_group in zip(*rows_by_source, strict=True):
            merged: Row = {}
            for row in row_group:
                overlap = set(merged).intersection(row)
                if overlap:
                    msg = "zip relation contains duplicate columns: " + ", ".join(
                        sorted(overlap)
                    )
                    raise ValueError(msg)
                merged.update(row)
            zipped.append(merged)
        return zipped
    if expression.kind == "with_columns":
        derived: list[Row] = []
        for source_row in _evaluate_relation(_required(expression.source), ctx):
            next_row = dict(source_row)
            child_ctx = _child_context(
                ctx,
                row=next_row,
                row_scope_id=expression.row_scope_id,
            )
            for name, scalar in _required(expression.new_columns).items():
                next_row[name] = _evaluate_scalar(scalar, child_ctx)
            derived.append(next_row)
        return derived
    if expression.kind == "sort":
        rows = _evaluate_relation(_required(expression.source), ctx)
        columns = tuple(_required(expression.sort_columns))
        return sorted(
            rows,
            key=cmp_to_key(
                lambda left, right: _compare_rows(left, right, columns=columns)
            ),
        )
    if expression.kind == "limit":
        return _evaluate_relation(_required(expression.source), ctx)[
            : _required(expression.limit_count)
        ]
    msg = f"unsupported relation kind: {expression.kind}"
    raise ValueError(msg)


def _child_context(
    ctx: EvalContext,
    *,
    row: Row,
    point_row: Row | None = None,
    row_scope_id: RowScopeId | None = None,
) -> EvalContext:
    row_scopes = dict(ctx.row_scopes)
    if row_scope_id is not None:
        row_scopes[row_scope_id] = row
    return EvalContext(
        params=ctx.params,
        row=row,
        outer_row=ctx.outer_row,
        point_row=ctx.point_row if point_row is None else point_row,
        row_scopes=row_scopes,
        inputs=ctx.inputs,
    )


def _quantity_unit(value: CellValue) -> str | None:
    return value.unit if isinstance(value, Quantity) else None


def _series_float(value: CellValue, *, unit: str | None) -> float:
    if isinstance(value, Quantity):
        return value.value if unit is None else value.to(unit).value
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    msg = f"series bound must be numeric or quantity, got {value!r}"
    raise TypeError(msg)


def _series_values(raw_values: Sequence[float], *, unit: str | None) -> list[CellValue]:
    if any(not math.isfinite(value) for value in raw_values):
        msg = "series materialization produced a non-finite value"
        raise ValueError(msg)
    values = [round(value, 12) for value in raw_values]
    if unit is None:
        return [cast("CellValue", value) for value in values]
    return [Quantity(value=value, unit=unit) for value in values]


def _float_almost_equal(left: float, right: float) -> bool:
    return abs(left - right) <= 1e-12


def _cell_matches(left: CellValue | None, right: CellValue) -> bool:
    if isinstance(left, EntityRef) and isinstance(right, EntityRef):
        return same_entity_identity(left, right)
    if isinstance(left, EntityRef) and isinstance(right, str):
        return left.id == right
    if isinstance(left, str) and isinstance(right, EntityRef):
        return left == right.id
    try:
        return runtime_values_equal(left, right)
    except TypeError:
        return False


def _join_keys_match(left: Row, right: Row, on: Mapping[str, str]) -> bool:
    for left_column, right_column in on.items():
        left_value = read_path(left, left_column)
        right_value = read_path(right, right_column)
        if left_value is None or right_value is None:
            msg = "join key values must be non-null"
            raise TypeError(msg)
        if not runtime_values_equal(left_value, right_value):
            return False
    return True


def _compare_rows(left: Row, right: Row, *, columns: tuple[str, ...]) -> int:
    for column in columns:
        result = compare_ordered_values(
            read_path(left, column),
            read_path(right, column),
        )
        if result:
            return result
    return 0


def _require_disjoint_row_columns(
    left_rows: Sequence[Row],
    right_rows: Sequence[Row],
    *,
    operation: str,
    allowed_shared: set[str] | None = None,
) -> None:
    left_columns = {column for row in left_rows for column in row}
    right_columns = {column for row in right_rows for column in row}
    conflicts = sorted((left_columns & right_columns) - (allowed_shared or set()))
    if conflicts:
        msg = f"{operation} column collision: {', '.join(conflicts)}"
        raise ValueError(msg)


def _merge_rows(
    left: Row,
    right: Row,
    *,
    operation: str,
    allowed_shared: set[str] | None = None,
) -> Row:
    merged = dict(left)
    for key, value in right.items():
        if key in merged:
            if key not in (allowed_shared or set()):
                msg = f"{operation} column collision for {key!r}"
                raise ValueError(msg)
            if not runtime_values_equal(merged[key], value):
                msg = (
                    f"{operation} shared key {key!r} differs: "
                    f"{merged[key]!r} != {value!r}"
                )
                raise ValueError(msg)
            continue
        merged[key] = value
    return merged


def _input_series(inputs: Mapping[str, object], name: str) -> list[CellValue]:
    try:
        value = inputs[name]
    except KeyError as error:
        msg = f"unknown series input {name!r}"
        raise KeyError(msg) from error
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"series input {name!r} must be a sequence"
        raise TypeError(msg)
    items: list[CellValue] = []
    for item in cast("Sequence[object]", value):
        if not is_cell_value(item):
            msg = f"series input {name!r} contains unsupported value {item!r}"
            raise TypeError(msg)
        items.append(item)
    return items


def _input_table(inputs: Mapping[str, object], name: str) -> list[Row]:
    try:
        value = inputs[name]
    except KeyError as error:
        msg = f"unknown table input {name!r}"
        raise KeyError(msg) from error
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        msg = f"table input {name!r} must be a sequence of rows"
        raise TypeError(msg)
    rows: list[Row] = []
    for row in cast("Sequence[object]", value):
        if not isinstance(row, Mapping):
            msg = f"table input {name!r} contains non-row value {row!r}"
            raise TypeError(msg)
        mapping = cast("Mapping[object, object]", row)
        if not all(isinstance(key, str) for key in mapping):
            msg = f"table input {name!r} row keys must be strings"
            raise TypeError(msg)
        rows.append(
            {
                cast("str", key): _normalize_input_cell(item)
                for key, item in mapping.items()
            }
        )
    return rows


def _normalize_input_cell(value: object) -> CellValue:
    if not isinstance(value, Mapping):
        if is_cell_value(value):
            return value
        msg = f"input table cell contains unsupported value {value!r}"
        raise TypeError(msg)
    mapping = cast("Mapping[object, object]", value)
    if set(mapping) == {"value", "unit"}:
        return Quantity.model_validate(mapping)
    if "id" in mapping and set(mapping) <= {"id", "kind", "metadata"}:
        return EntityRef.model_validate(mapping)
    if not all(isinstance(key, str) for key in mapping):
        msg = "input table mapping cells must use string keys"
        raise TypeError(msg)
    return dict(cast("Mapping[str, Any]", mapping))


def _required[T](value: T | None) -> T:
    if value is None:
        raise AssertionError("validated field is unexpectedly missing")
    return value


__all__ = [
    "REFERENCE_RELATION_BACKEND",
    "EvalContext",
    "ParameterRelationData",
    "PreparedRelationEvaluation",
    "ReferenceRelationBackend",
    "RelationBackend",
    "RelationBackendCapabilityDimension",
    "RelationBackendCapabilityError",
    "RelationBackendCapabilityIssue",
    "RelationPlanRequirements",
    "SelectedRelationPlan",
    "assess_relation_plan",
    "evaluate_relation",
    "evaluate_relation_in_context",
    "evaluate_scalar",
    "evaluate_series",
    "select_relation_plan",
    "validate_relation_parameter_import",
]
