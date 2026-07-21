"""Exact symbolic point domains and stable logical point identity.

The point model deliberately owns only finite point-generation semantics.  A
linear axis may carry one verified scalar plan for its center; arbitrary table
relations are not point-domain leaves.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import product
from typing import cast

from scopecat.compiler.relations.evaluation import (
    EvalContext,
    ParameterRelationData,
    evaluate_scalar,
)
from scopecat.compiler.relations.model import CellValue, Row
from scopecat.compiler.relations.point_domain import (
    PointAxis,
    PointAxisLinear,
    PointAxisValues,
    PointDomainAnalysis,
    PointDomainExpr,
    PointDomainPath,
    PointDomainShapeError,
    PointProduct,
    PointRows,
    PointUnit,
    PointZip,
    analyze_point_domain,
    decompose_product_ordinal,
    is_point_coordinate_type,
    point_axis_linear_value,
)
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.relations.verification import (
    PlanImportNamespace,
    RelationPlanVerificationError,
    RowType,
    verify_relation_plan,
)
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.value_types import Entity, Scalar, Table, TableColumn
from scopecat.kernel.value_validation import coerce_literal
from scopecat.records.parameter import Quantity as QuantityValue

type PointRowNormalizer = Callable[[Row], Mapping[str, object]]
type CompilerPointDomainExpr = PointDomainExpr[RelationUse[ScalarValueExpr]]


@dataclass(frozen=True, slots=True)
class PointDomain:
    """One exact algebra tree defining an ordered logical point space."""

    root: CompilerPointDomainExpr
    id: str = "root"

    @property
    def value_type(self) -> Table:
        return analyze_point_domain(self.root).root.value_type


@dataclass(frozen=True, slots=True)
class PointDomainVerificationIssue:
    """One static violation at the point-domain boundary."""

    code: str
    path: PointDomainPath
    message: str


class PointDomainVerificationError(ValueError):
    """A symbolic point domain is not a closed, well-typed point root."""

    def __init__(self, issues: Sequence[PointDomainVerificationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


class PointDomainEvaluationError(ValueError):
    """A dynamic linear-axis center failed during point evaluation."""

    def __init__(self, path: PointDomainPath, error: Exception) -> None:
        self.path = path
        self.error = error
        rendered = "/".join(str(part) for part in path)
        prefix = f"point domain {rendered}" if rendered else "point domain root"
        super().__init__(f"{prefix} failed: {error}")


@dataclass(frozen=True, slots=True)
class VerifiedPointDomain:
    """A shape-checked exact point domain."""

    id: PointDomainId
    root: CompilerPointDomainExpr
    analysis: PointDomainAnalysis

    @property
    def cardinality(self) -> int:
        return self.analysis.root.cardinality

    @property
    def entity_columns(self) -> tuple[str, ...]:
        return tuple(
            column.id
            for column in self.value_type.columns
            if isinstance(column.value_type.atom, Entity)
        )

    @property
    def value_type(self) -> Table:
        return self.analysis.root.value_type

    @property
    def coordinate_columns(self) -> tuple[TableColumn, ...]:
        return tuple(
            column
            for column in self.value_type.columns
            if is_point_coordinate_type(column.value_type)
        )


@dataclass(frozen=True, slots=True)
class MaterializedPoint:
    """One concrete point retaining its canonical logical identity."""

    logical_id: LogicalPointId
    row: Row

    @property
    def logical_ordinal(self) -> int:
        return self.logical_id.logical_ordinal


@dataclass(frozen=True, slots=True)
class MaterializedPointDomain:
    """One materialized coverage of an exact symbolic domain."""

    id: PointDomainId
    points: tuple[MaterializedPoint, ...]


def verify_point_domain(
    domain: PointDomain,
    *,
    program_id: str,
) -> VerifiedPointDomain:
    """Check exact shape and every dynamic center in its structural row role."""

    domain_id = PointDomainId(program_id=program_id, domain_id=domain.id)
    try:
        analysis = analyze_point_domain(domain.root)
    except PointDomainShapeError as error:
        raise PointDomainVerificationError(
            (
                PointDomainVerificationIssue(
                    error.code,
                    error.path,
                    error.message,
                ),
            )
        ) from error
    issues: list[PointDomainVerificationIssue] = []
    _verify_center_roles(
        domain.root,
        analysis=analysis,
        path=(),
        ambient_row=None,
        issues=issues,
    )
    if issues:
        raise PointDomainVerificationError(issues)
    return VerifiedPointDomain(domain_id, domain.root, analysis)


def materialize_point_domain(
    verified: VerifiedPointDomain,
    params: ParameterRelationData,
    *,
    row_normalizer: PointRowNormalizer | None = None,
) -> MaterializedPointDomain:
    """Materialize the exact tree and assign canonical ordinal identities."""

    rows = _materialize_node(
        verified.root,
        params=params,
        ambient_row={},
        path=(),
    )
    normalized_rows: Sequence[Mapping[str, object]] = rows
    if row_normalizer is not None:
        normalized_rows = tuple(row_normalizer(dict(row)) for row in rows)
    typed_rows = _coerce_rows(
        verified.value_type,
        normalized_rows,
        path=("points",),
    )
    points = tuple(
        MaterializedPoint(
            LogicalPointId(verified.id, ordinal),
            row,
        )
        for ordinal, row in enumerate(typed_rows)
    )
    return MaterializedPointDomain(verified.id, points)


def materialize_point_domain_ordinals(
    verified: VerifiedPointDomain,
    params: ParameterRelationData,
    ordinals: Sequence[int],
    *,
    max_points: int,
    row_normalizer: PointRowNormalizer | None = None,
) -> tuple[MaterializedPoint, ...]:
    """Materialize selected ordinals without expanding the complete domain."""

    selected = tuple(ordinals)
    if type(max_points) is not int or max_points <= 0:
        raise ValueError("point selection budget must be a positive integer")
    if len(selected) > max_points:
        raise ValueError("point selection exceeds the requested budget")
    if any(ordinal < 0 or ordinal >= verified.cardinality for ordinal in selected):
        raise ValueError("point selection contains an unknown logical ordinal")
    if not selected:
        return ()
    unique_ordinals = tuple(sorted(set(selected)))
    rows = _materialize_node_ordinals(
        verified.root,
        ordinals=unique_ordinals,
        analysis=verified.analysis,
        params=params,
        ambient_row={},
        path=(),
    )
    normalized = {
        ordinal: (
            row_normalizer(dict(rows[ordinal]))
            if row_normalizer is not None
            else rows[ordinal]
        )
        for ordinal in unique_ordinals
    }
    row_type = replace(verified.value_type, min_rows=1, max_rows=1)
    typed_rows = {
        ordinal: _coerce_rows(
            row_type,
            (normalized[ordinal],),
            path=("points", ordinal),
        )[0]
        for ordinal in unique_ordinals
    }
    points = {
        ordinal: MaterializedPoint(
            LogicalPointId(verified.id, ordinal),
            typed_rows[ordinal],
        )
        for ordinal in unique_ordinals
    }
    return tuple(points[ordinal] for ordinal in selected)


def _materialize_node(
    node: CompilerPointDomainExpr,
    *,
    params: ParameterRelationData,
    ambient_row: Row,
    path: PointDomainPath,
) -> list[Row]:
    if isinstance(node, PointUnit):
        return [{}]
    if isinstance(node, PointRows):
        column_ids = tuple(column.id for column in node.columns)
        return [dict(zip(column_ids, row, strict=True)) for row in node.rows]
    if isinstance(node, PointAxis):
        return [
            {node.id: value}
            for value in _axis_values(
                node,
                params=params,
                ambient_row=ambient_row,
                path=path,
            )
        ]
    if isinstance(node, PointProduct):
        factor_rows = tuple(
            _materialize_node(
                factor,
                params=params,
                ambient_row=ambient_row,
                path=(*path, "factors", index),
            )
            for index, factor in enumerate(node.factors)
        )
        return [_merge_rows(group) for group in product(*factor_rows)]
    if isinstance(node, PointZip):
        source_rows = tuple(
            _materialize_node(
                source,
                params=params,
                ambient_row=ambient_row,
                path=(*path, "sources", index),
            )
            for index, source in enumerate(node.sources)
        )
        return [_merge_rows(group) for group in zip(*source_rows, strict=True)]
    left_rows = _materialize_node(
        node.left,
        params=params,
        ambient_row=ambient_row,
        path=(*path, "left"),
    )
    rows: list[Row] = []
    for left in left_rows:
        right_rows = _materialize_node(
            node.right,
            params=params,
            ambient_row=_merge_rows((ambient_row, left)),
            path=(*path, "right"),
        )
        rows.extend(_merge_rows((left, right)) for right in right_rows)
    return rows


def _materialize_node_ordinals(
    node: CompilerPointDomainExpr,
    *,
    ordinals: tuple[int, ...],
    analysis: PointDomainAnalysis,
    params: ParameterRelationData,
    ambient_row: Row,
    path: PointDomainPath,
) -> dict[int, Row]:
    if isinstance(node, PointUnit):
        return {ordinal: {} for ordinal in ordinals}
    if isinstance(node, PointRows):
        column_ids = tuple(column.id for column in node.columns)
        return {
            ordinal: dict(zip(column_ids, node.rows[ordinal], strict=True))
            for ordinal in ordinals
        }
    if isinstance(node, PointAxis):
        values = _axis_values_at(
            node,
            ordinals,
            params=params,
            ambient_row=ambient_row,
            path=path,
        )
        return {
            ordinal: {node.id: value}
            for ordinal, value in zip(ordinals, values, strict=True)
        }
    if isinstance(node, PointZip):
        sources = tuple(
            _materialize_node_ordinals(
                source,
                ordinals=ordinals,
                analysis=analysis,
                params=params,
                ambient_row=ambient_row,
                path=(*path, "sources", index),
            )
            for index, source in enumerate(node.sources)
        )
        return {
            ordinal: _merge_rows(tuple(source[ordinal] for source in sources))
            for ordinal in ordinals
        }
    if isinstance(node, PointProduct):
        child_paths = tuple(
            (*path, "factors", index) for index in range(len(node.factors))
        )
        child_counts = tuple(
            analysis.facts[child_path].cardinality for child_path in child_paths
        )
        local_ordinals = {
            ordinal: decompose_product_ordinal(ordinal, child_counts)
            for ordinal in ordinals
        }
        children = tuple(
            _materialize_node_ordinals(
                factor,
                ordinals=tuple(
                    sorted({local_ordinals[root][index] for root in ordinals})
                ),
                analysis=analysis,
                params=params,
                ambient_row=ambient_row,
                path=child_paths[index],
            )
            for index, factor in enumerate(node.factors)
        )
        return {
            ordinal: _merge_rows(
                tuple(
                    child[local_ordinals[ordinal][index]]
                    for index, child in enumerate(children)
                )
            )
            for ordinal in ordinals
        }
    left_path = (*path, "left")
    right_path = (*path, "right")
    right_count = analysis.facts[right_path].cardinality
    left_ordinal = {ordinal: ordinal // right_count for ordinal in ordinals}
    right_ordinal = {ordinal: ordinal % right_count for ordinal in ordinals}
    left_rows = _materialize_node_ordinals(
        node.left,
        ordinals=tuple(sorted(set(left_ordinal.values()))),
        analysis=analysis,
        params=params,
        ambient_row=ambient_row,
        path=left_path,
    )
    right_rows: dict[int, dict[int, Row]] = {}
    for outer_ordinal, left_row in left_rows.items():
        selected_right = tuple(
            sorted(
                {
                    right_ordinal[root]
                    for root in ordinals
                    if left_ordinal[root] == outer_ordinal
                }
            )
        )
        right_rows[outer_ordinal] = _materialize_node_ordinals(
            node.right,
            ordinals=selected_right,
            analysis=analysis,
            params=params,
            ambient_row=_merge_rows((ambient_row, left_row)),
            path=right_path,
        )
    return {
        ordinal: _merge_rows(
            (
                left_rows[left_ordinal[ordinal]],
                right_rows[left_ordinal[ordinal]][right_ordinal[ordinal]],
            )
        )
        for ordinal in ordinals
    }


def _axis_values(
    axis: PointAxis[RelationUse[ScalarValueExpr]],
    *,
    params: ParameterRelationData,
    ambient_row: Row,
    path: PointDomainPath,
) -> tuple[CellValue, ...]:
    source = axis.source
    count = len(source.values) if isinstance(source, PointAxisValues) else source.count
    return _axis_values_at(
        axis,
        range(count),
        params=params,
        ambient_row=ambient_row,
        path=path,
    )


def _axis_values_at(
    axis: PointAxis[RelationUse[ScalarValueExpr]],
    ordinals: Sequence[int],
    *,
    params: ParameterRelationData,
    ambient_row: Row,
    path: PointDomainPath,
) -> tuple[CellValue, ...]:
    source = axis.source
    if isinstance(source, PointAxisValues):
        return tuple(source.values[ordinal] for ordinal in ordinals)
    try:
        center = evaluate_scalar(
            source.center.value.plan,
            EvalContext(params=params, point_row=ambient_row),
        )
        if not isinstance(center, QuantityValue):
            msg = "linear point axis center must materialize as a quantity"
            raise TypeError(msg)
        return tuple(
            point_axis_linear_value(center, source.span, source.count, index)
            for index in ordinals
        )
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        raise PointDomainEvaluationError(
            (*path, "source", "center"),
            error,
        ) from error


def _verify_center_roles(
    node: CompilerPointDomainExpr,
    *,
    analysis: PointDomainAnalysis,
    path: PointDomainPath,
    ambient_row: RowType | None,
    issues: list[PointDomainVerificationIssue],
) -> None:
    if isinstance(node, PointUnit | PointRows):
        return
    if isinstance(node, PointAxis):
        if isinstance(node.source, PointAxisLinear):
            _verify_center_role(
                node.source.center.value,
                expected_type=node.value_type,
                path=(*path, "source", "center"),
                ambient_row=ambient_row,
                issues=issues,
            )
        return
    if isinstance(node, PointProduct):
        for index, factor in enumerate(node.factors):
            _verify_center_roles(
                factor,
                analysis=analysis,
                path=(*path, "factors", index),
                ambient_row=ambient_row,
                issues=issues,
            )
        return
    if isinstance(node, PointZip):
        for index, source in enumerate(node.sources):
            _verify_center_roles(
                source,
                analysis=analysis,
                path=(*path, "sources", index),
                ambient_row=ambient_row,
                issues=issues,
            )
        return
    left_path = (*path, "left")
    _verify_center_roles(
        node.left,
        analysis=analysis,
        path=left_path,
        ambient_row=ambient_row,
        issues=issues,
    )
    _verify_center_roles(
        node.right,
        analysis=analysis,
        path=(*path, "right"),
        ambient_row=_extend_row_type(
            ambient_row,
            analysis.facts[left_path].value_type,
        ),
        issues=issues,
    )


def _verify_center_role(
    value: ScalarValueExpr,
    *,
    expected_type: Scalar,
    path: PointDomainPath,
    ambient_row: RowType | None,
    issues: list[PointDomainVerificationIssue],
) -> None:
    plan = value.plan
    row_interface = plan.external_row_interface
    open_interface = bool(row_interface.arguments) or (
        row_interface.point is not None and ambient_row is None
    )
    if open_interface:
        issues.append(
            PointDomainVerificationIssue(
                "point_axis_center_open_row_interface",
                path,
                "point-axis center has an unbound external row",
            )
        )
    if any(
        imported.namespace is PlanImportNamespace.INPUT for imported in plan.imports
    ):
        issues.append(
            PointDomainVerificationIssue(
                "point_axis_center_open_input",
                path,
                "point-axis center depends on an unresolved input",
            )
        )
    if open_interface:
        return
    try:
        reverified = verify_relation_plan(
            plan.root,
            bindings=replace(
                plan.bindings,
                point_row=ambient_row,
                row_arguments={},
            ),
            expected_type=expected_type,
        )
    except RelationPlanVerificationError as error:
        issues.append(
            PointDomainVerificationIssue(
                error.code,
                (*path, *error.path),
                error.reason,
            )
        )
        return
    if (
        reverified.certified_type != plan.certified_type
        or reverified.imports != plan.imports
        or reverified.external_row_interface != plan.external_row_interface
    ):
        issues.append(
            PointDomainVerificationIssue(
                "point_axis_center_stale_proof",
                path,
                "point-axis center proof does not match its structural role",
            )
        )


def _extend_row_type(parent: RowType | None, child: Table) -> RowType:
    return RowType(
        (*(() if parent is None else parent.columns), *child.columns),
        (False if parent is None else parent.allow_extra_columns)
        or child.allow_extra_columns,
    )


def _merge_rows(rows: Sequence[Mapping[str, CellValue]]) -> Row:
    return {key: value for row in rows for key, value in row.items()}


def _coerce_rows(
    value_type: Table,
    rows: Sequence[Mapping[str, object]],
    *,
    path: tuple[str | int, ...],
) -> tuple[Row, ...]:
    coerced = coerce_literal(value_type, rows, path=path)
    return cast("tuple[Row, ...]", coerced)


__all__ = [
    "CompilerPointDomainExpr",
    "MaterializedPoint",
    "MaterializedPointDomain",
    "PointDomain",
    "PointDomainEvaluationError",
    "PointDomainVerificationError",
    "PointDomainVerificationIssue",
    "PointRowNormalizer",
    "VerifiedPointDomain",
    "materialize_point_domain",
    "materialize_point_domain_ordinals",
    "verify_point_domain",
]
