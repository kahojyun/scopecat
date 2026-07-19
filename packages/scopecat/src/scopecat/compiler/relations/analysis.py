"""Traversal and reference analysis for relation plans.

Relation plan nodes are semantic data.  This module is the single owner of
their child structure and operation identities so compiler analyses do not
grow independent, silently incomplete tree walkers.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterator
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast

from scopecat.compiler.relations.model import (
    BinaryScalarExpr,
    CaseBranch,
    CaseScalarExpr,
    ColumnScalarExpr,
    CrossRelationExpr,
    FilterRelationExpr,
    GridColumn,
    GridRelationExpr,
    InputRelationExpr,
    InputScalarExpr,
    InputSeriesExpr,
    JoinRelationExpr,
    LateralCrossRelationExpr,
    LimitRelationExpr,
    LinspaceSeriesExpr,
    LiteralRowsRelationExpr,
    LiteralScalarExpr,
    OuterColumnScalarExpr,
    ParameterLookupScalarExpr,
    ParameterScalarExpr,
    ParameterSeriesExpr,
    PointColumnScalarExpr,
    PointCrossRelationExpr,
    RangeSeriesExpr,
    RelationColumnSeriesExpr,
    RelationEntitiesSeriesExpr,
    RelationExpr,
    RelationExpression,
    RelationGridColumn,
    RowScopeId,
    ScalarExpr,
    ScalarExpression,
    ScalarGridColumn,
    SelectRelationExpr,
    SeriesExpr,
    SeriesExpression,
    SeriesGridColumn,
    SortRelationExpr,
    TableRelationExpr,
    ValuesGridColumn,
    ValuesSeriesExpr,
    WithColumnsRelationExpr,
    ZipRelationExpr,
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


_PLAN_OPERATIONS: dict[type[PlanNode], PlanOperation] = {
    LiteralScalarExpr: PlanOperation.SCALAR_LITERAL,
    ColumnScalarExpr: PlanOperation.SCALAR_CURRENT_COLUMN,
    OuterColumnScalarExpr: PlanOperation.SCALAR_OUTER_COLUMN,
    PointColumnScalarExpr: PlanOperation.SCALAR_POINT_COLUMN,
    InputScalarExpr: PlanOperation.SCALAR_INPUT,
    ParameterScalarExpr: PlanOperation.SCALAR_PARAMETER,
    ParameterLookupScalarExpr: PlanOperation.SCALAR_PARAMETER_LOOKUP,
    BinaryScalarExpr: PlanOperation.SCALAR_BINARY,
    CaseScalarExpr: PlanOperation.SCALAR_CASE,
    ValuesSeriesExpr: PlanOperation.SERIES_VALUES,
    LinspaceSeriesExpr: PlanOperation.SERIES_LINSPACE,
    RangeSeriesExpr: PlanOperation.SERIES_RANGE,
    InputSeriesExpr: PlanOperation.SERIES_INPUT,
    ParameterSeriesExpr: PlanOperation.SERIES_PARAMETER,
    RelationColumnSeriesExpr: PlanOperation.SERIES_RELATION_COLUMN,
    RelationEntitiesSeriesExpr: PlanOperation.SERIES_RELATION_ENTITIES,
    LiteralRowsRelationExpr: PlanOperation.RELATION_LITERAL_ROWS,
    TableRelationExpr: PlanOperation.RELATION_PARAMETER_TABLE,
    InputRelationExpr: PlanOperation.RELATION_INPUT,
    GridRelationExpr: PlanOperation.RELATION_GRID,
    SelectRelationExpr: PlanOperation.RELATION_SELECT,
    FilterRelationExpr: PlanOperation.RELATION_FILTER,
    JoinRelationExpr: PlanOperation.RELATION_JOIN,
    CrossRelationExpr: PlanOperation.RELATION_CROSS,
    LateralCrossRelationExpr: PlanOperation.RELATION_LATERAL_CROSS,
    PointCrossRelationExpr: PlanOperation.RELATION_POINT_CROSS,
    ZipRelationExpr: PlanOperation.RELATION_ZIP,
    WithColumnsRelationExpr: PlanOperation.RELATION_WITH_COLUMNS,
    SortRelationExpr: PlanOperation.RELATION_SORT,
    LimitRelationExpr: PlanOperation.RELATION_LIMIT,
}


def relation_operation(node: PlanNode) -> PlanOperation:
    """Return the stable operation identity for one plan node."""

    try:
        return _PLAN_OPERATIONS[type(node)]
    except KeyError as error:
        msg = f"unsupported plan operation: {type(node).__name__}"
        raise ValueError(msg) from error


def iter_plan_children(node: PlanNode) -> Iterator[PlanNode]:
    """Yield direct semantic children in deterministic declaration order."""

    if isinstance(node, ScalarExpr):
        scalar = cast("ScalarExpression", node)
        if isinstance(
            scalar,
            LiteralScalarExpr
            | ColumnScalarExpr
            | OuterColumnScalarExpr
            | PointColumnScalarExpr
            | InputScalarExpr
            | ParameterScalarExpr,
        ):
            return
        if isinstance(scalar, ParameterLookupScalarExpr):
            yield from scalar.key.values()
            return
        if isinstance(scalar, BinaryScalarExpr):
            yield scalar.left
            yield scalar.right
            return
        for branch in scalar.cases:
            yield branch.condition
            yield branch.value
        yield scalar.fallback
        return

    if isinstance(node, SeriesExpr):
        series = cast("SeriesExpression", node)
        if isinstance(series, ValuesSeriesExpr | InputSeriesExpr | ParameterSeriesExpr):
            return
        if isinstance(series, LinspaceSeriesExpr):
            yield series.start
            yield series.stop
            return
        if isinstance(series, RangeSeriesExpr):
            yield series.start
            yield series.stop
            yield series.step
            return
        if isinstance(series, RelationColumnSeriesExpr):
            yield series.source
            return
        yield series.source
        return

    relation = cast("RelationExpression", node)
    if isinstance(
        relation, (LiteralRowsRelationExpr, TableRelationExpr, InputRelationExpr)
    ):
        return
    if isinstance(relation, GridRelationExpr):
        for column in relation.columns.values():
            match column:
                case ScalarGridColumn(scalar=scalar):
                    yield scalar
                case SeriesGridColumn(series=series):
                    yield series
                case RelationGridColumn(relation=source):
                    yield source
                case ValuesGridColumn():
                    pass
        return
    if isinstance(relation, (SelectRelationExpr, SortRelationExpr, LimitRelationExpr)):
        yield relation.source
        return
    if isinstance(relation, FilterRelationExpr):
        yield relation.source
        yield relation.condition
        return
    if isinstance(
        relation,
        (
            JoinRelationExpr,
            CrossRelationExpr,
            LateralCrossRelationExpr,
            PointCrossRelationExpr,
        ),
    ):
        yield relation.left
        yield relation.right
        return
    if isinstance(relation, ZipRelationExpr):
        yield from relation.sources
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
            elif isinstance(scalar, CaseScalarExpr):
                rewritten = replace(
                    scalar,
                    cases=[
                        CaseBranch(
                            condition=cast("ScalarExpression", visit(branch.condition)),
                            value=cast("ScalarExpression", visit(branch.value)),
                        )
                        for branch in scalar.cases
                    ],
                    fallback=cast("ScalarExpression", visit(scalar.fallback)),
                )
            else:
                rewritten = scalar
            return transform(rewritten)

        if isinstance(node, SeriesExpr):
            series = cast("SeriesExpression", node)
            if isinstance(series, LinspaceSeriesExpr):
                rewritten = replace(
                    series,
                    start=cast("ScalarExpression", visit(series.start)),
                    stop=cast("ScalarExpression", visit(series.stop)),
                )
            elif isinstance(series, RangeSeriesExpr):
                rewritten = replace(
                    series,
                    start=cast("ScalarExpression", visit(series.start)),
                    stop=cast("ScalarExpression", visit(series.stop)),
                    step=cast("ScalarExpression", visit(series.step)),
                )
            elif isinstance(
                series, RelationColumnSeriesExpr | RelationEntitiesSeriesExpr
            ):
                rewritten = replace(
                    series,
                    source=cast("RelationExpression", visit(series.source)),
                )
            else:
                rewritten = series
            return transform(rewritten)

        relation = cast("RelationExpression", node)
        if isinstance(relation, GridRelationExpr):
            columns: dict[str, GridColumn] = {}
            for name, column in relation.columns.items():
                match column:
                    case ScalarGridColumn():
                        columns[name] = replace(
                            column,
                            scalar=cast("ScalarExpression", visit(column.scalar)),
                        )
                    case SeriesGridColumn():
                        columns[name] = replace(
                            column,
                            series=cast("SeriesExpression", visit(column.series)),
                        )
                    case RelationGridColumn():
                        columns[name] = replace(
                            column,
                            relation=cast("RelationExpression", visit(column.relation)),
                        )
                    case ValuesGridColumn():
                        columns[name] = column
            rewritten = replace(relation, columns=columns)
        elif isinstance(
            relation, SelectRelationExpr | SortRelationExpr | LimitRelationExpr
        ):
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
        elif isinstance(
            relation,
            JoinRelationExpr
            | CrossRelationExpr
            | LateralCrossRelationExpr
            | PointCrossRelationExpr,
        ):
            rewritten = replace(
                relation,
                left=cast("RelationExpression", visit(relation.left)),
                right=cast("RelationExpression", visit(relation.right)),
            )
        elif isinstance(relation, ZipRelationExpr):
            rewritten = replace(
                relation,
                sources=[
                    cast("RelationExpression", visit(source))
                    for source in relation.sources
                ],
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
        if not isinstance(relation, FilterRelationExpr | WithColumnsRelationExpr):
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
        if isinstance(scalar, ColumnScalarExpr):
            reference = PlanReference(
                PlanReferenceKind.CURRENT_COLUMN,
                scalar.name,
                row_scope_id=scalar.row_scope_id,
            )
            if (
                scalar.row_scope_id is not None and scalar.row_scope_id not in active
            ) or (scalar.row_scope_id is None and not current_row_available):
                references.add(reference)
        elif isinstance(scalar, OuterColumnScalarExpr) and not outer_row_available:
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
    if isinstance(relation, FilterRelationExpr):
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
    if isinstance(relation, WithColumnsRelationExpr):
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
    if isinstance(relation, LateralCrossRelationExpr):
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
        if isinstance(scalar, ColumnScalarExpr):
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
        elif isinstance(scalar, OuterColumnScalarExpr) and not outer_row_available:
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
    if isinstance(relation, FilterRelationExpr):
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
    if isinstance(relation, WithColumnsRelationExpr):
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
    if isinstance(relation, LateralCrossRelationExpr):
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
        if isinstance(scalar, ColumnScalarExpr):
            if scalar.row_scope_id is None:
                return scalar
            return replace(
                scalar,
                row_scope_id=scalar.row_scope_id.prefixed(*scope),
            )
        if isinstance(scalar, ParameterLookupScalarExpr):
            return replace(
                scalar,
                key={
                    name: _prefix_plan_row_scopes(value, scope)
                    for name, value in scalar.key.items()
                },
            )
        if isinstance(scalar, BinaryScalarExpr):
            return replace(
                scalar,
                left=_prefix_plan_row_scopes(scalar.left, scope),
                right=_prefix_plan_row_scopes(scalar.right, scope),
            )
        if isinstance(scalar, CaseScalarExpr):
            return replace(
                scalar,
                cases=[
                    replace(
                        branch,
                        condition=_prefix_plan_row_scopes(
                            branch.condition,
                            scope,
                        ),
                        value=_prefix_plan_row_scopes(
                            branch.value,
                            scope,
                        ),
                    )
                    for branch in scalar.cases
                ],
                fallback=_prefix_plan_row_scopes(scalar.fallback, scope),
            )
        return scalar

    if isinstance(node, SeriesExpr):
        series = cast("SeriesExpression", node)
        if isinstance(series, LinspaceSeriesExpr):
            return replace(
                series,
                start=_prefix_plan_row_scopes(series.start, scope),
                stop=_prefix_plan_row_scopes(series.stop, scope),
            )
        if isinstance(series, RangeSeriesExpr):
            return replace(
                series,
                start=_prefix_plan_row_scopes(series.start, scope),
                stop=_prefix_plan_row_scopes(series.stop, scope),
                step=_prefix_plan_row_scopes(series.step, scope),
            )
        if isinstance(series, (RelationColumnSeriesExpr, RelationEntitiesSeriesExpr)):
            source = series.source
        else:
            return series
        return replace(series, source=_prefix_plan_row_scopes(source, scope))

    relation = cast("RelationExpression", node)
    if isinstance(
        relation, (LiteralRowsRelationExpr, TableRelationExpr, InputRelationExpr)
    ):
        return relation
    if isinstance(relation, GridRelationExpr):
        columns = {}
        for name, column in relation.columns.items():
            match column:
                case ScalarGridColumn(scalar=scalar):
                    columns[name] = replace(
                        column,
                        scalar=_prefix_plan_row_scopes(scalar, scope),
                    )
                case SeriesGridColumn(series=series):
                    columns[name] = replace(
                        column,
                        series=_prefix_plan_row_scopes(series, scope),
                    )
                case RelationGridColumn(relation=source):
                    columns[name] = replace(
                        column,
                        relation=_prefix_plan_row_scopes(source, scope),
                    )
                case ValuesGridColumn():
                    columns[name] = column
        return replace(relation, columns=columns)
    if isinstance(relation, (SelectRelationExpr, SortRelationExpr, LimitRelationExpr)):
        return replace(
            relation,
            source=_prefix_plan_row_scopes(relation.source, scope),
        )
    if isinstance(relation, FilterRelationExpr):
        return replace(
            relation,
            source=_prefix_plan_row_scopes(relation.source, scope),
            condition=_prefix_plan_row_scopes(relation.condition, scope),
            row_scope_id=(
                relation.row_scope_id.prefixed(*scope)
                if relation.row_scope_id is not None
                else None
            ),
        )
    if isinstance(
        relation,
        (
            JoinRelationExpr,
            CrossRelationExpr,
            LateralCrossRelationExpr,
            PointCrossRelationExpr,
        ),
    ):
        return replace(
            relation,
            left=_prefix_plan_row_scopes(relation.left, scope),
            right=_prefix_plan_row_scopes(relation.right, scope),
        )
    if isinstance(relation, ZipRelationExpr):
        return replace(
            relation,
            sources=[
                _prefix_plan_row_scopes(source, scope) for source in relation.sources
            ],
        )
    return replace(
        relation,
        source=_prefix_plan_row_scopes(relation.source, scope),
        new_columns={
            name: _prefix_plan_row_scopes(value, scope)
            for name, value in relation.new_columns.items()
        },
        row_scope_id=(
            relation.row_scope_id.prefixed(*scope)
            if relation.row_scope_id is not None
            else None
        ),
    )


def _scalar_reference(node: ScalarExpr) -> PlanReference | None:
    scalar = cast("ScalarExpression", node)
    if isinstance(scalar, ColumnScalarExpr):
        return PlanReference(
            PlanReferenceKind.CURRENT_COLUMN,
            scalar.name,
            row_scope_id=scalar.row_scope_id,
        )
    if isinstance(scalar, OuterColumnScalarExpr):
        return PlanReference(PlanReferenceKind.OUTER_COLUMN, scalar.name)
    if isinstance(scalar, PointColumnScalarExpr):
        return PlanReference(PlanReferenceKind.POINT_COLUMN, scalar.name)
    if isinstance(scalar, InputScalarExpr):
        return PlanReference(PlanReferenceKind.INPUT_SCALAR, scalar.name)
    if isinstance(scalar, ParameterScalarExpr):
        return PlanReference(PlanReferenceKind.PARAMETER_SCALAR, scalar.name)
    if isinstance(scalar, ParameterLookupScalarExpr):
        return PlanReference(
            PlanReferenceKind.PARAMETER_TABLE,
            scalar.table_id,
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
