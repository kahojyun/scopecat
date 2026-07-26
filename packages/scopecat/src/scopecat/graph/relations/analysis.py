"""Traversal and reference analysis for relation plans.

Relation plan nodes are semantic data.  This module is the single owner of
their child structure so compiler analyses do not grow independent, silently
incomplete tree walkers.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast

from scopecat.graph.relations.model import (
    BinaryScalarExpr,
    InputRelationExpr,
    InputScalarExpr,
    InputSeriesExpr,
    LiteralScalarExpr,
    ParameterLookupScalarExpr,
    ParameterScalarExpr,
    ParameterSeriesExpr,
    PointColumnScalarExpr,
    RelationExpr,
    RelationExpression,
    ScalarExpr,
    ScalarExpression,
    SeriesExpr,
    SeriesExpression,
    TableRelationExpr,
)

type PlanNode = ScalarExpr | SeriesExpr | RelationExpr


class PlanReferenceKind(StrEnum):
    """Shape-preserving identity for an external plan reference."""

    POINT_COLUMN = "point_column"
    INPUT_SCALAR = "input.scalar"
    INPUT_SERIES = "input.series"
    INPUT_TABLE = "input.table"
    PARAMETER_SCALAR = "parameter.scalar"
    PARAMETER_SERIES = "parameter.series"
    PARAMETER_TABLE = "parameter.table"


@dataclass(frozen=True, slots=True)
class PlanReference:
    kind: PlanReferenceKind
    id: str

    def __post_init__(self) -> None:
        if not self.id:
            msg = "plan reference ids must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PlanReferences:
    references: frozenset[PlanReference] = frozenset()

    def __iter__(self) -> Iterator[PlanReference]:
        return iter(
            sorted(
                self.references,
                key=lambda reference: (
                    reference.kind.value,
                    reference.id,
                ),
            )
        )

    def ids(self, *kinds: PlanReferenceKind) -> tuple[str, ...]:
        selected = frozenset(kinds)
        return tuple(
            sorted(
                {
                    reference.id
                    for reference in self.references
                    if reference.kind in selected
                }
            )
        )


def iter_plan_children(node: PlanNode) -> Iterator[PlanNode]:
    """Yield direct semantic children in deterministic declaration order."""

    if isinstance(node, ScalarExpr):
        scalar = cast("ScalarExpression", node)
        if isinstance(
            scalar,
            LiteralScalarExpr
            | PointColumnScalarExpr
            | InputScalarExpr
            | ParameterScalarExpr,
        ):
            return
        if isinstance(scalar, ParameterLookupScalarExpr):
            yield from scalar.key.values()
            return
        yield scalar.left
        yield scalar.right
        return

    if isinstance(node, SeriesExpr):
        return

    return


def walk_plan(root: PlanNode) -> Iterator[PlanNode]:
    """Walk all operation occurrences in deterministic pre-order."""

    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(tuple(iter_plan_children(node))))


def rewrite_plan[NodeT: PlanNode](
    root: NodeT,
    transform: Callable[[PlanNode], PlanNode],
) -> NodeT:
    """Rewrite a plan bottom-up while preserving each node's value shape.

    This is the shared structural boundary for compiler transformations. The
    callback may replace operations, but scalar, series, and relation nodes
    must retain their respective shapes.
    """

    def visit(node: PlanNode) -> PlanNode:
        if isinstance(node, ScalarExpr):
            scalar = cast("ScalarExpression", node)
            if isinstance(scalar, ParameterLookupScalarExpr):
                rewritten: PlanNode = replace(
                    scalar,
                    key={
                        name: cast("ScalarExpression", visit(value))
                        for name, value in scalar.key.items()
                    },
                )
            elif isinstance(scalar, BinaryScalarExpr):
                rewritten = replace(
                    scalar,
                    left=cast("ScalarExpression", visit(scalar.left)),
                    right=cast("ScalarExpression", visit(scalar.right)),
                )
            else:
                rewritten = scalar
            return transform(rewritten)

        if isinstance(node, SeriesExpr):
            return transform(cast("SeriesExpression", node))

        return transform(cast("RelationExpression", node))

    return cast("NodeT", visit(root))


def plan_references(root: PlanNode) -> PlanReferences:
    """Collect all external references while retaining their semantic shape."""

    references: set[PlanReference] = set()
    for node in walk_plan(root):
        if isinstance(node, ScalarExpr):
            reference = _scalar_reference(node)
        elif isinstance(node, SeriesExpr):
            reference = _series_reference(node)
        else:
            reference = _relation_reference(node)
        if reference is not None:
            references.add(reference)
    return PlanReferences(frozenset(references))


def plan_input_refs(root: PlanNode) -> tuple[str, ...]:
    """Return free input ids across scalar, series, and table input shapes."""

    return plan_references(root).ids(
        PlanReferenceKind.INPUT_SCALAR,
        PlanReferenceKind.INPUT_SERIES,
        PlanReferenceKind.INPUT_TABLE,
    )


def _scalar_reference(node: ScalarExpr) -> PlanReference | None:
    scalar = cast("ScalarExpression", node)
    if isinstance(scalar, PointColumnScalarExpr):
        return PlanReference(PlanReferenceKind.POINT_COLUMN, scalar.name)
    if isinstance(scalar, InputScalarExpr):
        return PlanReference(PlanReferenceKind.INPUT_SCALAR, scalar.name)
    if isinstance(scalar, ParameterScalarExpr):
        return PlanReference(PlanReferenceKind.PARAMETER_SCALAR, scalar.name)
    if isinstance(scalar, ParameterLookupScalarExpr):
        return PlanReference(
            PlanReferenceKind.PARAMETER_TABLE,
            scalar.use.table_id,
        )
    return None


def _series_reference(node: SeriesExpr) -> PlanReference | None:
    series = cast("SeriesExpression", node)
    if isinstance(series, InputSeriesExpr):
        return PlanReference(
            PlanReferenceKind.INPUT_SERIES,
            series.name,
        )
    if isinstance(series, ParameterSeriesExpr):
        return PlanReference(
            PlanReferenceKind.PARAMETER_SERIES,
            series.name,
        )
    return None


def _relation_reference(node: RelationExpr) -> PlanReference | None:
    relation = cast("RelationExpression", node)
    if isinstance(relation, InputRelationExpr):
        return PlanReference(
            PlanReferenceKind.INPUT_TABLE,
            relation.name,
        )
    if isinstance(relation, TableRelationExpr):
        return PlanReference(
            PlanReferenceKind.PARAMETER_TABLE,
            relation.table_id,
        )
    return None
