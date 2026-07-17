"""Traversal and reference analysis for relation plans.

Relation plan nodes are semantic data.  This module is the single owner of
their child structure and operation identities so compiler analyses do not
grow independent, silently incomplete tree walkers.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from scopecat.compiler.relations.model import (
    RelationExpr,
    RelationExpression,
    RowScopeId,
    ScalarExpr,
    ScalarExpression,
    SeriesExpr,
    SeriesExpression,
)

type PlanNode = ScalarExpr | SeriesExpr | RelationExpr


class PlanOperation(StrEnum):
    """Stable identity for one relation-plan operation."""

    SCALAR_LITERAL = "scalar.literal"
    SCALAR_CURRENT_COLUMN = "scalar.column"
    SCALAR_OUTER_COLUMN = "scalar.outer_column"
    SCALAR_POINT_COLUMN = "scalar.point_column"
    SCALAR_INPUT = "scalar.input"
    SCALAR_PARAMETER = "scalar.param_scalar"
    SCALAR_PARAMETER_LOOKUP = "scalar.param_lookup"
    SCALAR_BINARY = "scalar.binary"
    SCALAR_CASE = "scalar.case"

    SERIES_VALUES = "series.values"
    SERIES_LINSPACE = "series.linspace"
    SERIES_RANGE = "series.range"
    SERIES_INPUT = "series.input"
    SERIES_PARAMETER = "series.param_series"
    SERIES_RELATION_COLUMN = "series.relation_column"
    SERIES_RELATION_ENTITIES = "series.relation_entities"

    RELATION_LITERAL_ROWS = "relation.literal_rows"
    RELATION_PARAMETER_TABLE = "relation.table"
    RELATION_INPUT = "relation.input"
    RELATION_GRID = "relation.grid"
    RELATION_SELECT = "relation.select"
    RELATION_FILTER = "relation.filter"
    RELATION_JOIN = "relation.join"
    RELATION_CROSS = "relation.cross"
    RELATION_LATERAL_CROSS = "relation.lateral_cross"
    RELATION_POINT_CROSS = "relation.point_cross"
    RELATION_ZIP = "relation.zip"
    RELATION_WITH_COLUMNS = "relation.with_columns"
    RELATION_SORT = "relation.sort"
    RELATION_LIMIT = "relation.limit"


class PlanReferenceKind(StrEnum):
    """Shape-preserving identity for an external plan reference."""

    CURRENT_COLUMN = "current_column"
    OUTER_COLUMN = "outer_column"
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

    def merged(self, other: PlanReferences) -> PlanReferences:
        return PlanReferences(self.references | other.references)

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


_SCALAR_OPERATIONS: dict[str, PlanOperation] = {
    "literal": PlanOperation.SCALAR_LITERAL,
    "column": PlanOperation.SCALAR_CURRENT_COLUMN,
    "outer_column": PlanOperation.SCALAR_OUTER_COLUMN,
    "point_column": PlanOperation.SCALAR_POINT_COLUMN,
    "input": PlanOperation.SCALAR_INPUT,
    "param_scalar": PlanOperation.SCALAR_PARAMETER,
    "param_lookup": PlanOperation.SCALAR_PARAMETER_LOOKUP,
    "binary": PlanOperation.SCALAR_BINARY,
    "case": PlanOperation.SCALAR_CASE,
}
_SERIES_OPERATIONS: dict[str, PlanOperation] = {
    "values": PlanOperation.SERIES_VALUES,
    "linspace": PlanOperation.SERIES_LINSPACE,
    "range": PlanOperation.SERIES_RANGE,
    "input": PlanOperation.SERIES_INPUT,
    "param_series": PlanOperation.SERIES_PARAMETER,
    "relation_column": PlanOperation.SERIES_RELATION_COLUMN,
    "relation_entities": PlanOperation.SERIES_RELATION_ENTITIES,
}
_RELATION_OPERATIONS: dict[str, PlanOperation] = {
    "literal_rows": PlanOperation.RELATION_LITERAL_ROWS,
    "table": PlanOperation.RELATION_PARAMETER_TABLE,
    "input": PlanOperation.RELATION_INPUT,
    "grid": PlanOperation.RELATION_GRID,
    "select": PlanOperation.RELATION_SELECT,
    "filter": PlanOperation.RELATION_FILTER,
    "join": PlanOperation.RELATION_JOIN,
    "cross": PlanOperation.RELATION_CROSS,
    "lateral_cross": PlanOperation.RELATION_LATERAL_CROSS,
    "point_cross": PlanOperation.RELATION_POINT_CROSS,
    "zip": PlanOperation.RELATION_ZIP,
    "with_columns": PlanOperation.RELATION_WITH_COLUMNS,
    "sort": PlanOperation.RELATION_SORT,
    "limit": PlanOperation.RELATION_LIMIT,
}


def relation_operation(node: PlanNode) -> PlanOperation:
    """Return the stable operation identity for one plan node."""

    if isinstance(node, ScalarExpr):
        operations = _SCALAR_OPERATIONS
        shape = "scalar"
        kind = cast("ScalarExpression", node).kind
    elif isinstance(node, SeriesExpr):
        operations = _SERIES_OPERATIONS
        shape = "series"
        kind = cast("SeriesExpression", node).kind
    else:
        operations = _RELATION_OPERATIONS
        shape = "relation"
        kind = cast("RelationExpression", node).kind
    try:
        return operations[kind]
    except KeyError as error:
        msg = f"unsupported {shape} plan operation: {kind!r}"
        raise ValueError(msg) from error


def iter_plan_children(node: PlanNode) -> Iterator[PlanNode]:
    """Yield direct semantic children in deterministic declaration order."""

    operation = relation_operation(node)
    if isinstance(node, ScalarExpr):
        scalar = cast("ScalarExpression", node)
        if scalar.kind in {
            "literal",
            "column",
            "outer_column",
            "point_column",
            "input",
            "param_scalar",
        }:
            return
        if scalar.kind == "param_lookup":
            yield from scalar.key.values()
            return
        if scalar.kind == "binary":
            yield scalar.left
            yield scalar.right
            return
        if scalar.kind == "case":
            for branch in scalar.cases:
                yield branch.condition
                yield branch.value
            yield scalar.fallback
            return
        raise AssertionError(f"unhandled scalar expression: {scalar!r}")

    if isinstance(node, SeriesExpr):
        series = cast("SeriesExpression", node)
        if series.kind in {"values", "input", "param_series"}:
            return
        if series.kind == "linspace":
            yield series.start
            yield series.stop
            return
        if series.kind == "range":
            yield series.start
            yield series.stop
            yield series.step
            return
        if series.kind == "relation_column":
            yield series.source
            return
        if series.kind == "relation_entities":
            yield series.source
            return
        raise AssertionError(f"unhandled series relation operation: {operation}")

    relation = cast("RelationExpression", node)
    if (
        relation.kind == "literal_rows"
        or relation.kind == "table"
        or relation.kind == "input"
    ):
        return
    if relation.kind == "grid":
        for column in relation.columns.values():
            if column.kind == "scalar":
                yield column.scalar
            elif column.kind == "series":
                yield column.series
            elif column.kind == "relation":
                yield column.relation
        return
    if relation.kind == "select" or relation.kind == "sort" or relation.kind == "limit":
        yield relation.source
        return
    if relation.kind == "filter":
        yield relation.source
        yield relation.condition
        return
    if (
        relation.kind == "join"
        or relation.kind == "cross"
        or relation.kind == "lateral_cross"
        or relation.kind == "point_cross"
    ):
        yield relation.left
        yield relation.right
        return
    if relation.kind == "zip":
        yield from relation.sources
        return
    if relation.kind == "with_columns":
        yield relation.source
        yield from relation.new_columns.values()
        return
    raise AssertionError(f"unhandled relation expression: {relation!r}")


def walk_plan(root: PlanNode) -> Iterator[PlanNode]:
    """Walk all operation occurrences in deterministic pre-order."""

    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(tuple(iter_plan_children(node))))


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
        if reference.row_scope_id is not None:
            scope = reference.row_scope_id.qualified_name
        elif reference.kind is PlanReferenceKind.OUTER_COLUMN:
            scope = "<outer-row>"
        else:
            scope = "<implicit-current-row>"
        super().__init__(
            f"relation row reference {reference.id!r} has no active scope {scope!r}"
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
    current_row_available: bool = False,
    outer_row_available: bool = False,
    active_row_scopes: Collection[RowScopeId] = (),
) -> None:
    """Require every row reference to be closed by an explicit plan scope."""

    active = frozenset(active_row_scopes)
    _verify_row_binder_hygiene(root, external=active)
    _verify_node_scopes(
        root,
        active=active,
        current_row_available=current_row_available,
        outer_row_available=outer_row_available,
    )


def _verify_row_binder_hygiene(
    root: PlanNode,
    *,
    external: frozenset[RowScopeId],
) -> None:
    for node in walk_plan(root):
        if not isinstance(node, RelationExpr):
            continue
        relation = cast("RelationExpression", node)
        if relation.kind != "filter" and relation.kind != "with_columns":
            continue
        row_scope_id = relation.row_scope_id
        if row_scope_id is None:
            continue
        if row_scope_id in external:
            raise RelationPlanBinderError(row_scope_id)


def free_row_references(root: PlanNode) -> PlanReferences:
    """Return row uses not closed by a binder declared inside ``root``.

    This is lexical dependency analysis, not a list of every column node.  A
    filter/with-columns callback closes its own row argument, and the right
    side of a lateral cross closes its implicit current/outer arguments.  Any
    remaining use must be supplied by an enclosing semantic region.
    """

    references: set[PlanReference] = set()
    _collect_free_row_references(
        root,
        active=frozenset(),
        current_row_available=False,
        outer_row_available=False,
        references=references,
    )
    return PlanReferences(frozenset(references))


def _collect_free_row_references(
    node: PlanNode,
    *,
    active: frozenset[RowScopeId],
    current_row_available: bool,
    outer_row_available: bool,
    references: set[PlanReference],
) -> None:
    if isinstance(node, ScalarExpr):
        scalar = cast("ScalarExpression", node)
        if scalar.kind == "column":
            reference = PlanReference(
                PlanReferenceKind.CURRENT_COLUMN,
                scalar.name,
                row_scope_id=scalar.row_scope_id,
            )
            if (
                scalar.row_scope_id is not None and scalar.row_scope_id not in active
            ) or (scalar.row_scope_id is None and not current_row_available):
                references.add(reference)
        elif scalar.kind == "outer_column" and not outer_row_available:
            references.add(
                PlanReference(
                    PlanReferenceKind.OUTER_COLUMN,
                    scalar.name,
                )
            )
        for child in iter_plan_children(scalar):
            _collect_free_row_references(
                child,
                active=active,
                current_row_available=current_row_available,
                outer_row_available=outer_row_available,
                references=references,
            )
        return

    if isinstance(node, SeriesExpr):
        for child in iter_plan_children(node):
            _collect_free_row_references(
                child,
                active=active,
                current_row_available=current_row_available,
                outer_row_available=outer_row_available,
                references=references,
            )
        return

    relation = cast("RelationExpression", node)
    if relation.kind == "filter":
        _collect_free_row_references(
            relation.source,
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
            references=references,
        )
        nested = (
            active | {relation.row_scope_id}
            if relation.row_scope_id is not None
            else active
        )
        _collect_free_row_references(
            relation.condition,
            active=frozenset(nested),
            current_row_available=True,
            outer_row_available=outer_row_available,
            references=references,
        )
        return
    if relation.kind == "with_columns":
        _collect_free_row_references(
            relation.source,
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
            references=references,
        )
        nested = (
            active | {relation.row_scope_id}
            if relation.row_scope_id is not None
            else active
        )
        for scalar in relation.new_columns.values():
            _collect_free_row_references(
                scalar,
                active=frozenset(nested),
                current_row_available=True,
                outer_row_available=outer_row_available,
                references=references,
            )
        return
    if relation.kind == "lateral_cross":
        _collect_free_row_references(
            relation.left,
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
            references=references,
        )
        _collect_free_row_references(
            relation.right,
            active=active,
            current_row_available=True,
            outer_row_available=True,
            references=references,
        )
        return
    for child in iter_plan_children(relation):
        _collect_free_row_references(
            child,
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
            references=references,
        )


def _verify_node_scopes(
    node: PlanNode,
    *,
    active: frozenset[RowScopeId],
    current_row_available: bool,
    outer_row_available: bool,
) -> None:
    if isinstance(node, ScalarExpr):
        scalar = cast("ScalarExpression", node)
        if scalar.kind == "column":
            reference = PlanReference(
                PlanReferenceKind.CURRENT_COLUMN,
                scalar.name,
                row_scope_id=scalar.row_scope_id,
            )
            if scalar.row_scope_id is not None:
                if scalar.row_scope_id not in active:
                    raise RelationPlanScopeError(reference)
            elif not current_row_available:
                raise RelationPlanScopeError(reference)
        elif scalar.kind == "outer_column" and not outer_row_available:
            raise RelationPlanScopeError(
                PlanReference(
                    PlanReferenceKind.OUTER_COLUMN,
                    scalar.name,
                )
            )
        for child in iter_plan_children(scalar):
            _verify_node_scopes(
                child,
                active=active,
                current_row_available=current_row_available,
                outer_row_available=outer_row_available,
            )
        return

    if isinstance(node, SeriesExpr):
        for child in iter_plan_children(node):
            _verify_node_scopes(
                child,
                active=active,
                current_row_available=current_row_available,
                outer_row_available=outer_row_available,
            )
        return

    relation = cast("RelationExpression", node)
    if relation.kind == "filter":
        _verify_node_scopes(
            relation.source,
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
        )
        nested = (
            active | {relation.row_scope_id}
            if relation.row_scope_id is not None
            else active
        )
        _verify_node_scopes(
            relation.condition,
            active=frozenset(nested),
            current_row_available=True,
            outer_row_available=outer_row_available,
        )
        return
    if relation.kind == "with_columns":
        _verify_node_scopes(
            relation.source,
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
        )
        nested = (
            active | {relation.row_scope_id}
            if relation.row_scope_id is not None
            else active
        )
        for scalar in relation.new_columns.values():
            _verify_node_scopes(
                scalar,
                active=frozenset(nested),
                current_row_available=True,
                outer_row_available=outer_row_available,
            )
        return
    if relation.kind == "lateral_cross":
        _verify_node_scopes(
            relation.left,
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
        )
        _verify_node_scopes(
            relation.right,
            active=active,
            current_row_available=True,
            outer_row_available=True,
        )
        return
    for child in iter_plan_children(relation):
        _verify_node_scopes(
            child,
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
        )


def prefix_plan_row_scopes[NodeT: PlanNode](
    root: NodeT,
    *scope: str,
) -> NodeT:
    """Alpha-rename every nominal row binder and reference in one plan."""

    if not scope:
        return root
    return cast("NodeT", _prefix_plan_row_scopes(root, scope))


def _prefix_plan_row_scopes(
    node: PlanNode,
    scope: tuple[str, ...],
) -> PlanNode:
    if isinstance(node, ScalarExpr):
        scalar = cast("ScalarExpression", node)
        if scalar.kind == "column":
            if scalar.row_scope_id is None:
                return scalar
            return scalar.model_copy(
                update={"row_scope_id": scalar.row_scope_id.prefixed(*scope)}
            )
        if scalar.kind == "param_lookup":
            return scalar.model_copy(
                update={
                    "key": {
                        name: _prefix_plan_row_scopes(value, scope)
                        for name, value in scalar.key.items()
                    }
                }
            )
        if scalar.kind == "binary":
            return scalar.model_copy(
                update={
                    "left": _prefix_plan_row_scopes(scalar.left, scope),
                    "right": _prefix_plan_row_scopes(scalar.right, scope),
                }
            )
        if scalar.kind == "case":
            return scalar.model_copy(
                update={
                    "cases": [
                        branch.model_copy(
                            update={
                                "condition": _prefix_plan_row_scopes(
                                    branch.condition,
                                    scope,
                                ),
                                "value": _prefix_plan_row_scopes(
                                    branch.value,
                                    scope,
                                ),
                            }
                        )
                        for branch in scalar.cases
                    ],
                    "fallback": _prefix_plan_row_scopes(scalar.fallback, scope),
                }
            )
        return scalar

    if isinstance(node, SeriesExpr):
        series = cast("SeriesExpression", node)
        if series.kind == "linspace":
            return series.model_copy(
                update={
                    "start": _prefix_plan_row_scopes(series.start, scope),
                    "stop": _prefix_plan_row_scopes(series.stop, scope),
                }
            )
        if series.kind == "range":
            return series.model_copy(
                update={
                    "start": _prefix_plan_row_scopes(series.start, scope),
                    "stop": _prefix_plan_row_scopes(series.stop, scope),
                    "step": _prefix_plan_row_scopes(series.step, scope),
                }
            )
        if series.kind == "relation_column" or series.kind == "relation_entities":
            source = series.source
        else:
            return series
        return series.model_copy(
            update={"source": _prefix_plan_row_scopes(source, scope)}
        )

    relation = cast("RelationExpression", node)
    if (
        relation.kind == "literal_rows"
        or relation.kind == "table"
        or relation.kind == "input"
    ):
        return relation
    if relation.kind == "grid":
        columns = {}
        for name, column in relation.columns.items():
            if column.kind == "scalar":
                columns[name] = column.model_copy(
                    update={"scalar": _prefix_plan_row_scopes(column.scalar, scope)}
                )
            elif column.kind == "series":
                columns[name] = column.model_copy(
                    update={"series": _prefix_plan_row_scopes(column.series, scope)}
                )
            elif column.kind == "relation":
                columns[name] = column.model_copy(
                    update={"relation": _prefix_plan_row_scopes(column.relation, scope)}
                )
            else:
                columns[name] = column
        return relation.model_copy(update={"columns": columns})
    if relation.kind == "select" or relation.kind == "sort" or relation.kind == "limit":
        return relation.model_copy(
            update={"source": _prefix_plan_row_scopes(relation.source, scope)}
        )
    if relation.kind == "filter":
        update: dict[str, object] = {
            "source": _prefix_plan_row_scopes(relation.source, scope),
            "condition": _prefix_plan_row_scopes(relation.condition, scope),
        }
        if relation.row_scope_id is not None:
            update["row_scope_id"] = relation.row_scope_id.prefixed(*scope)
        return relation.model_copy(update=update)
    if (
        relation.kind == "join"
        or relation.kind == "cross"
        or relation.kind == "lateral_cross"
        or relation.kind == "point_cross"
    ):
        return relation.model_copy(
            update={
                "left": _prefix_plan_row_scopes(relation.left, scope),
                "right": _prefix_plan_row_scopes(relation.right, scope),
            }
        )
    if relation.kind == "zip":
        return relation.model_copy(
            update={
                "sources": [
                    _prefix_plan_row_scopes(source, scope)
                    for source in relation.sources
                ]
            }
        )
    if relation.kind == "with_columns":
        update = {
            "source": _prefix_plan_row_scopes(relation.source, scope),
            "new_columns": {
                name: _prefix_plan_row_scopes(value, scope)
                for name, value in relation.new_columns.items()
            },
        }
        if relation.row_scope_id is not None:
            update["row_scope_id"] = relation.row_scope_id.prefixed(*scope)
        return relation.model_copy(update=update)
    raise AssertionError(f"unhandled relation expression: {relation!r}")


def _scalar_reference(node: ScalarExpr) -> PlanReference | None:
    scalar = cast("ScalarExpression", node)
    if scalar.kind == "column":
        return PlanReference(
            PlanReferenceKind.CURRENT_COLUMN,
            scalar.name,
            row_scope_id=scalar.row_scope_id,
        )
    if scalar.kind == "outer_column":
        return PlanReference(PlanReferenceKind.OUTER_COLUMN, scalar.name)
    if scalar.kind == "point_column":
        return PlanReference(PlanReferenceKind.POINT_COLUMN, scalar.name)
    if scalar.kind == "input":
        return PlanReference(PlanReferenceKind.INPUT_SCALAR, scalar.name)
    if scalar.kind == "param_scalar":
        return PlanReference(PlanReferenceKind.PARAMETER_SCALAR, scalar.name)
    if scalar.kind == "param_lookup":
        return PlanReference(
            PlanReferenceKind.PARAMETER_TABLE,
            scalar.table_id,
        )
    return None


def _series_reference(node: SeriesExpr) -> PlanReference | None:
    series = cast("SeriesExpression", node)
    if series.kind == "input":
        return PlanReference(
            PlanReferenceKind.INPUT_SERIES,
            series.name,
        )
    if series.kind == "param_series":
        return PlanReference(
            PlanReferenceKind.PARAMETER_SERIES,
            series.name,
        )
    return None


def _relation_reference(node: RelationExpr) -> PlanReference | None:
    relation = cast("RelationExpression", node)
    if relation.kind == "input":
        return PlanReference(
            PlanReferenceKind.INPUT_TABLE,
            relation.name,
        )
    if relation.kind == "table":
        return PlanReference(
            PlanReferenceKind.PARAMETER_TABLE,
            relation.table_id,
        )
    return None
