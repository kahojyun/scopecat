"""Traversal and reference analysis for relation plans.

Relation plan nodes are semantic data.  This module is the single owner of
their child structure so compiler analyses do not grow independent, silently
incomplete tree walkers.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast

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

type PlanNode = ScalarExpr | SeriesExpr | RelationExpr


class PlanReferenceKind(StrEnum):
    """Shape-preserving identity for an external plan reference."""

    ROW_COLUMN = "row_column"
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
    row_scope_id: RowScopeId | None = None

    def __post_init__(self) -> None:
        if not self.id:
            msg = "plan reference ids must be non-empty"
            raise ValueError(msg)
        if self.kind is PlanReferenceKind.ROW_COLUMN and self.row_scope_id is None:
            msg = "row-column references require a nominal row scope"
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
                    (
                        reference.row_scope_id.qualified_name
                        if reference.row_scope_id is not None
                        else ""
                    ),
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
            | ColumnScalarExpr
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
        series = cast("SeriesExpression", node)
        if isinstance(series, ValuesSeriesExpr | InputSeriesExpr | ParameterSeriesExpr):
            return
        yield series.source
        return

    relation = cast("RelationExpression", node)
    if isinstance(
        relation, (LiteralRowsRelationExpr, TableRelationExpr, InputRelationExpr)
    ):
        return
    if isinstance(relation, SelectRelationExpr):
        yield relation.source
        return
    if isinstance(relation, FilterRelationExpr):
        yield relation.source
        yield relation.condition
        return
    yield relation.source
    yield from relation.new_columns.values()


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
            series = cast("SeriesExpression", node)
            if isinstance(series, RelationEntitiesSeriesExpr):
                rewritten = replace(
                    series,
                    source=cast("RelationExpression", visit(series.source)),
                )
            else:
                rewritten = series
            return transform(rewritten)

        relation = cast("RelationExpression", node)
        if isinstance(relation, SelectRelationExpr):
            rewritten = replace(
                relation,
                source=cast("RelationExpression", visit(relation.source)),
            )
        elif isinstance(relation, FilterRelationExpr):
            rewritten = replace(
                relation,
                source=cast("RelationExpression", visit(relation.source)),
                condition=cast("ScalarExpression", visit(relation.condition)),
            )
        elif isinstance(relation, WithColumnsRelationExpr):
            rewritten = replace(
                relation,
                source=cast("RelationExpression", visit(relation.source)),
                new_columns={
                    name: cast("ScalarExpression", visit(value))
                    for name, value in relation.new_columns.items()
                },
            )
        else:
            rewritten = relation
        return transform(rewritten)

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


class RelationPlanScopeError(ValueError):
    """A row reference is not closed by its lexical relation binder."""

    def __init__(self, reference: PlanReference) -> None:
        self.reference = reference
        row_scope_id = reference.row_scope_id
        if row_scope_id is None:
            raise AssertionError("row reference is missing its nominal scope")
        super().__init__(
            "relation row reference "
            f"{reference.id!r} has no active scope {row_scope_id.qualified_name!r}"
        )


class RelationPlanBinderError(ValueError):
    """A plan-local binder collides with an enclosing nominal row argument."""

    def __init__(self, row_scope_id: RowScopeId) -> None:
        self.row_scope_id = row_scope_id
        super().__init__(
            f"relation row binder {row_scope_id.qualified_name!r} collides "
            "with an enclosing row argument"
        )


def verify_plan_scopes(
    root: PlanNode,
    *,
    active_row_scopes: Collection[RowScopeId] = (),
) -> None:
    """Require every row reference to be closed by an explicit plan scope."""

    external = frozenset(active_row_scopes)
    for node, active in _walk_lexical_plan(root, active=external):
        if isinstance(node, ColumnScalarExpr):
            reference = _row_reference(node)
            if node.row_scope_id not in active:
                raise RelationPlanScopeError(reference)
            continue
        if (
            isinstance(node, FilterRelationExpr | WithColumnsRelationExpr)
            and node.row_scope_id in external
        ):
            raise RelationPlanBinderError(node.row_scope_id)


def free_row_references(root: PlanNode) -> PlanReferences:
    """Return row uses not closed by a binder declared inside ``root``.

    This is lexical dependency analysis, not a list of every column node.  A
    filter/with-columns callback closes its own row argument. Any remaining
    use must be supplied by an enclosing semantic region.
    """

    references = {
        _row_reference(node)
        for node, active in _walk_lexical_plan(root, active=frozenset())
        if isinstance(node, ColumnScalarExpr) and node.row_scope_id not in active
    }
    return PlanReferences(frozenset(references))


def _walk_lexical_plan(
    node: PlanNode,
    *,
    active: frozenset[RowScopeId],
) -> Iterator[tuple[PlanNode, frozenset[RowScopeId]]]:
    """Walk a plan with the exact nominal row scopes active at each node."""

    yield node, active
    if isinstance(node, ScalarExpr):
        for child in iter_plan_children(node):
            yield from _walk_lexical_plan(
                child,
                active=active,
            )
        return

    if isinstance(node, SeriesExpr):
        for child in iter_plan_children(node):
            yield from _walk_lexical_plan(
                child,
                active=active,
            )
        return

    relation = cast("RelationExpression", node)
    if isinstance(relation, FilterRelationExpr):
        yield from _walk_lexical_plan(
            relation.source,
            active=active,
        )
        yield from _walk_lexical_plan(
            relation.condition,
            active=active | {relation.row_scope_id},
        )
        return
    if isinstance(relation, WithColumnsRelationExpr):
        yield from _walk_lexical_plan(
            relation.source,
            active=active,
        )
        for scalar in relation.new_columns.values():
            yield from _walk_lexical_plan(
                scalar,
                active=active | {relation.row_scope_id},
            )
        return
    for child in iter_plan_children(relation):
        yield from _walk_lexical_plan(
            child,
            active=active,
        )


def prefix_plan_row_scopes[NodeT: PlanNode](
    root: NodeT,
    *scope: str,
) -> NodeT:
    """Alpha-rename every nominal row binder and reference in one plan."""

    if not scope:
        return root
    return rewrite_plan(
        root,
        lambda node: (
            replace(node, row_scope_id=node.row_scope_id.prefixed(*scope))
            if isinstance(
                node,
                ColumnScalarExpr | FilterRelationExpr | WithColumnsRelationExpr,
            )
            else node
        ),
    )


def _row_reference(scalar: ColumnScalarExpr) -> PlanReference:
    return PlanReference(
        PlanReferenceKind.ROW_COLUMN,
        scalar.name,
        row_scope_id=scalar.row_scope_id,
    )


def _scalar_reference(node: ScalarExpr) -> PlanReference | None:
    scalar = cast("ScalarExpression", node)
    if isinstance(scalar, ColumnScalarExpr):
        return _row_reference(scalar)
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
