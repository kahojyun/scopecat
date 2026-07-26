"""Exact symbolic point domains and stable logical point identity."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import product
from typing import cast

from scopecat.compiler.relations.context import EvalContext, ParameterRelationData
from scopecat.compiler.relations.evaluation import (
    evaluate_scalar,
)
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.relations.verification import (
    PlanImportNamespace,
    RelationPlanVerificationError,
    verify_relation_plan,
)
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.graph.relations.model import CellValue, Row
from scopecat.graph.relations.point_domain import (
    PointAxis,
    PointAxisLinear,
    PointAxisValues,
    PointDomainExpr,
    PointDomainPath,
    PointDomainShape,
    PointDomainShapeError,
    PointUnit,
    analyze_point_domain,
    is_point_coordinate_type,
    point_axis_linear_value,
)
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.quantity import Quantity as QuantityValue
from scopecat.kernel.value_types import Entity, Scalar, Table, TableColumn
from scopecat.kernel.value_validation import coerce_literal

type PointRowNormalizer = Callable[[Row], Mapping[str, object]]
type CompilerPointDomainExpr = PointDomainExpr[RelationUse[ScalarValueExpr]]


@dataclass(frozen=True, slots=True)
class PointDomain:
    """One exact algebra value defining an ordered logical point space."""

    root: CompilerPointDomainExpr
    id: str = "root"

    @property
    def value_type(self) -> Table:
        return analyze_point_domain(self.root).value_type


@dataclass(frozen=True, slots=True)
class PointDomainVerificationIssue:
    """One static violation at the point-domain boundary."""

    code: str
    path: PointDomainPath
    message: str


class PointDomainVerificationError(ValueError):
    """A symbolic point domain is not closed and well typed."""

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
    shape: PointDomainShape

    @property
    def cardinality(self) -> int:
        return self.shape.cardinality

    @property
    def entity_columns(self) -> tuple[str, ...]:
        return tuple(
            column.id
            for column in self.value_type.columns
            if isinstance(column.value_type.atom, Entity)
        )

    @property
    def value_type(self) -> Table:
        return self.shape.value_type

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
    """Check exact shape and require every dynamic center to be closed."""

    domain_id = PointDomainId(program_id=program_id, domain_id=domain.id)
    try:
        shape = analyze_point_domain(domain.root)
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
    for path, axis in _iter_axes(domain.root):
        if isinstance(axis.source, PointAxisLinear):
            _verify_center_role(
                axis.source.center.value,
                expected_type=axis.value_type,
                path=(*path, "source", "center"),
                issues=issues,
            )
    if issues:
        raise PointDomainVerificationError(issues)
    return VerifiedPointDomain(domain_id, domain.root, shape)


def materialize_point_domain(
    verified: VerifiedPointDomain,
    params: ParameterRelationData,
    *,
    row_normalizer: PointRowNormalizer | None = None,
) -> MaterializedPointDomain:
    """Materialize the exact domain and assign canonical ordinal identities."""

    rows = _materialize_node(verified.root, params=params, path=())
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


def _iter_axes(
    root: CompilerPointDomainExpr,
) -> Iterator[tuple[PointDomainPath, PointAxis[RelationUse[ScalarValueExpr]]]]:
    if isinstance(root, PointUnit):
        return
    if isinstance(root, PointAxis):
        yield (), root
        return
    for index, axis in enumerate(root.factors):
        yield ("factors", index), axis


def _materialize_node(
    node: CompilerPointDomainExpr,
    *,
    params: ParameterRelationData,
    path: PointDomainPath,
) -> list[Row]:
    if isinstance(node, PointUnit):
        return [{}]
    if isinstance(node, PointAxis):
        return [
            {node.id: value} for value in _axis_values(node, params=params, path=path)
        ]
    factor_rows = tuple(
        [
            {axis.id: value}
            for value in _axis_values(
                axis,
                params=params,
                path=("factors", index),
            )
        ]
        for index, axis in enumerate(node.factors)
    )
    return [_merge_rows(group) for group in product(*factor_rows)]


def _axis_values(
    axis: PointAxis[RelationUse[ScalarValueExpr]],
    *,
    params: ParameterRelationData,
    path: PointDomainPath,
) -> tuple[CellValue, ...]:
    source = axis.source
    if isinstance(source, PointAxisValues):
        return source.values
    try:
        center = evaluate_scalar(
            source.center.value.plan,
            EvalContext(params=params),
        )
        if not isinstance(center, QuantityValue):
            msg = "linear point axis center must materialize as a quantity"
            raise TypeError(msg)
        return tuple(
            point_axis_linear_value(center, source.span, source.count, index)
            for index in range(source.count)
        )
    except (ArithmeticError, KeyError, TypeError, ValueError) as error:
        raise PointDomainEvaluationError(
            (*path, "source", "center"),
            error,
        ) from error


def _verify_center_role(
    value: ScalarValueExpr,
    *,
    expected_type: Scalar,
    path: PointDomainPath,
    issues: list[PointDomainVerificationIssue],
) -> None:
    plan = value.plan
    open_interface = plan.external_point_requirement is not None
    if open_interface:
        issues.append(
            PointDomainVerificationIssue(
                "point_axis_center_open_point",
                path,
                "point-axis center depends on the current experiment point",
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
                point_row=None,
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
        or reverified.external_point_requirement != plan.external_point_requirement
    ):
        issues.append(
            PointDomainVerificationIssue(
                "point_axis_center_stale_proof",
                path,
                "point-axis center proof does not match its closed role",
            )
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
    "verify_point_domain",
]
