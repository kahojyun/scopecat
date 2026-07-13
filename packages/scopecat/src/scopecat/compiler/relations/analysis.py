"""Backend-neutral traversal and reference analysis for relation plans.

Relation plan nodes are semantic data.  This module is the single owner of
their child structure and capability identities so compiler analyses do not
grow independent, silently incomplete tree walkers.
"""

from __future__ import annotations

from collections.abc import Collection, Iterator
from dataclasses import dataclass
from enum import StrEnum
from typing import cast

from scopecat.compiler.relations.model import (
    RelationExpr,
    RowScopeId,
    ScalarExpr,
    SeriesExpr,
)

type PlanNode = ScalarExpr | SeriesExpr | RelationExpr


class RelationOperation(StrEnum):
    """Stable capability identity for one backend-neutral plan operation."""

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


_SCALAR_OPERATIONS: dict[str, RelationOperation] = {
    "literal": RelationOperation.SCALAR_LITERAL,
    "column": RelationOperation.SCALAR_CURRENT_COLUMN,
    "outer_column": RelationOperation.SCALAR_OUTER_COLUMN,
    "point_column": RelationOperation.SCALAR_POINT_COLUMN,
    "input": RelationOperation.SCALAR_INPUT,
    "param_scalar": RelationOperation.SCALAR_PARAMETER,
    "param_lookup": RelationOperation.SCALAR_PARAMETER_LOOKUP,
    "binary": RelationOperation.SCALAR_BINARY,
    "case": RelationOperation.SCALAR_CASE,
}
_SERIES_OPERATIONS: dict[str, RelationOperation] = {
    "values": RelationOperation.SERIES_VALUES,
    "linspace": RelationOperation.SERIES_LINSPACE,
    "range": RelationOperation.SERIES_RANGE,
    "input": RelationOperation.SERIES_INPUT,
    "param_series": RelationOperation.SERIES_PARAMETER,
    "relation_column": RelationOperation.SERIES_RELATION_COLUMN,
    "relation_entities": RelationOperation.SERIES_RELATION_ENTITIES,
}
_RELATION_OPERATIONS: dict[str, RelationOperation] = {
    "literal_rows": RelationOperation.RELATION_LITERAL_ROWS,
    "table": RelationOperation.RELATION_PARAMETER_TABLE,
    "input": RelationOperation.RELATION_INPUT,
    "grid": RelationOperation.RELATION_GRID,
    "select": RelationOperation.RELATION_SELECT,
    "filter": RelationOperation.RELATION_FILTER,
    "join": RelationOperation.RELATION_JOIN,
    "cross": RelationOperation.RELATION_CROSS,
    "lateral_cross": RelationOperation.RELATION_LATERAL_CROSS,
    "point_cross": RelationOperation.RELATION_POINT_CROSS,
    "zip": RelationOperation.RELATION_ZIP,
    "with_columns": RelationOperation.RELATION_WITH_COLUMNS,
    "sort": RelationOperation.RELATION_SORT,
    "limit": RelationOperation.RELATION_LIMIT,
}


def relation_operation(node: PlanNode) -> RelationOperation:
    """Return the backend capability required by one plan node."""

    if isinstance(node, ScalarExpr):
        operations = _SCALAR_OPERATIONS
        shape = "scalar"
    elif isinstance(node, SeriesExpr):
        operations = _SERIES_OPERATIONS
        shape = "series"
    else:
        operations = _RELATION_OPERATIONS
        shape = "relation"
    try:
        return operations[str(node.kind)]
    except KeyError as error:
        msg = f"unsupported {shape} plan operation: {node.kind!r}"
        raise ValueError(msg) from error


def iter_plan_children(node: PlanNode) -> Iterator[PlanNode]:
    """Yield direct semantic children in deterministic declaration order."""

    operation = relation_operation(node)
    if isinstance(node, ScalarExpr):
        if operation in {
            RelationOperation.SCALAR_LITERAL,
            RelationOperation.SCALAR_CURRENT_COLUMN,
            RelationOperation.SCALAR_OUTER_COLUMN,
            RelationOperation.SCALAR_POINT_COLUMN,
            RelationOperation.SCALAR_INPUT,
            RelationOperation.SCALAR_PARAMETER,
        }:
            return
        if operation is RelationOperation.SCALAR_PARAMETER_LOOKUP:
            yield from (node.key or {}).values()
            return
        if operation is RelationOperation.SCALAR_BINARY:
            yield _required_node(node.left, "scalar binary left")
            yield _required_node(node.right, "scalar binary right")
            return
        if operation is RelationOperation.SCALAR_CASE:
            for branch in node.cases or ():
                yield branch.condition
                yield branch.value
            yield _required_node(node.fallback, "scalar case fallback")
            return
        raise AssertionError(f"unhandled scalar relation operation: {operation}")

    if isinstance(node, SeriesExpr):
        if operation in {
            RelationOperation.SERIES_VALUES,
            RelationOperation.SERIES_INPUT,
            RelationOperation.SERIES_PARAMETER,
        }:
            return
        if operation in {
            RelationOperation.SERIES_LINSPACE,
            RelationOperation.SERIES_RANGE,
        }:
            for bound in (node.start, node.stop, node.step):
                if bound is not None:
                    yield bound
            return
        if operation in {
            RelationOperation.SERIES_RELATION_COLUMN,
            RelationOperation.SERIES_RELATION_ENTITIES,
        }:
            yield _required_node(node.source, "relation-backed series source")
            return
        raise AssertionError(f"unhandled series relation operation: {operation}")

    if operation in {
        RelationOperation.RELATION_LITERAL_ROWS,
        RelationOperation.RELATION_PARAMETER_TABLE,
        RelationOperation.RELATION_INPUT,
    }:
        return
    if operation is RelationOperation.RELATION_GRID:
        for column in (node.columns or {}).values():
            for child in (column.scalar, column.series, column.relation):
                if child is not None:
                    yield child
        return
    if operation in {
        RelationOperation.RELATION_SELECT,
        RelationOperation.RELATION_SORT,
        RelationOperation.RELATION_LIMIT,
    }:
        yield _required_node(node.source, f"{operation} source")
        return
    if operation is RelationOperation.RELATION_FILTER:
        yield _required_node(node.source, "relation filter source")
        yield _required_node(node.condition, "relation filter condition")
        return
    if operation in {
        RelationOperation.RELATION_JOIN,
        RelationOperation.RELATION_CROSS,
        RelationOperation.RELATION_LATERAL_CROSS,
        RelationOperation.RELATION_POINT_CROSS,
    }:
        yield _required_node(node.left, f"{operation} left")
        yield _required_node(node.right, f"{operation} right")
        return
    if operation is RelationOperation.RELATION_ZIP:
        yield from node.sources or ()
        return
    if operation is RelationOperation.RELATION_WITH_COLUMNS:
        yield _required_node(node.source, "relation with_columns source")
        yield from (node.new_columns or {}).values()
        return
    raise AssertionError(f"unhandled relation operation: {operation}")


def walk_plan(root: PlanNode) -> Iterator[PlanNode]:
    """Walk all operation occurrences in deterministic pre-order."""

    pending = [root]
    while pending:
        node = pending.pop()
        yield node
        pending.extend(reversed(tuple(iter_plan_children(node))))


def relation_operations(root: PlanNode) -> tuple[RelationOperation, ...]:
    """Return required backend capabilities in stable first-use order."""

    return tuple(dict.fromkeys(relation_operation(node) for node in walk_plan(root)))


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
        if not isinstance(node, RelationExpr) or node.kind not in {
            "filter",
            "with_columns",
        }:
            continue
        row_scope_id = node.row_scope_id
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
        if node.kind == "column":
            reference = PlanReference(
                PlanReferenceKind.CURRENT_COLUMN,
                _required_id(node.name, str(node.kind)),
                row_scope_id=node.row_scope_id,
            )
            if (node.row_scope_id is not None and node.row_scope_id not in active) or (
                node.row_scope_id is None and not current_row_available
            ):
                references.add(reference)
        elif node.kind == "outer_column" and not outer_row_available:
            references.add(
                PlanReference(
                    PlanReferenceKind.OUTER_COLUMN,
                    _required_id(node.name, str(node.kind)),
                )
            )
        for child in iter_plan_children(node):
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

    operation = relation_operation(node)
    if operation is RelationOperation.RELATION_FILTER:
        _collect_free_row_references(
            _required_node(node.source, "relation filter source"),
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
            references=references,
        )
        nested = (
            active | {node.row_scope_id} if node.row_scope_id is not None else active
        )
        _collect_free_row_references(
            _required_node(node.condition, "relation filter condition"),
            active=frozenset(nested),
            current_row_available=True,
            outer_row_available=outer_row_available,
            references=references,
        )
        return
    if operation is RelationOperation.RELATION_WITH_COLUMNS:
        _collect_free_row_references(
            _required_node(node.source, "relation with_columns source"),
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
            references=references,
        )
        nested = (
            active | {node.row_scope_id} if node.row_scope_id is not None else active
        )
        for scalar in (node.new_columns or {}).values():
            _collect_free_row_references(
                scalar,
                active=frozenset(nested),
                current_row_available=True,
                outer_row_available=outer_row_available,
                references=references,
            )
        return
    if operation is RelationOperation.RELATION_LATERAL_CROSS:
        _collect_free_row_references(
            _required_node(node.left, "relation lateral_cross left"),
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
            references=references,
        )
        _collect_free_row_references(
            _required_node(node.right, "relation lateral_cross right"),
            active=active,
            current_row_available=True,
            outer_row_available=True,
            references=references,
        )
        return
    for child in iter_plan_children(node):
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
        if node.kind == "column":
            reference = PlanReference(
                PlanReferenceKind.CURRENT_COLUMN,
                _required_id(node.name, str(node.kind)),
                row_scope_id=node.row_scope_id,
            )
            if node.row_scope_id is not None:
                if node.row_scope_id not in active:
                    raise RelationPlanScopeError(reference)
            elif not current_row_available:
                raise RelationPlanScopeError(reference)
        elif node.kind == "outer_column" and not outer_row_available:
            raise RelationPlanScopeError(
                PlanReference(
                    PlanReferenceKind.OUTER_COLUMN,
                    _required_id(node.name, str(node.kind)),
                )
            )
        for child in iter_plan_children(node):
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

    operation = relation_operation(node)
    if operation is RelationOperation.RELATION_FILTER:
        _verify_node_scopes(
            _required_node(node.source, "relation filter source"),
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
        )
        nested = (
            active | {node.row_scope_id} if node.row_scope_id is not None else active
        )
        _verify_node_scopes(
            _required_node(node.condition, "relation filter condition"),
            active=frozenset(nested),
            current_row_available=True,
            outer_row_available=outer_row_available,
        )
        return
    if operation is RelationOperation.RELATION_WITH_COLUMNS:
        _verify_node_scopes(
            _required_node(node.source, "relation with_columns source"),
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
        )
        nested = (
            active | {node.row_scope_id} if node.row_scope_id is not None else active
        )
        for scalar in (node.new_columns or {}).values():
            _verify_node_scopes(
                scalar,
                active=frozenset(nested),
                current_row_available=True,
                outer_row_available=outer_row_available,
            )
        return
    if operation is RelationOperation.RELATION_LATERAL_CROSS:
        _verify_node_scopes(
            _required_node(node.left, "relation lateral_cross left"),
            active=active,
            current_row_available=current_row_available,
            outer_row_available=outer_row_available,
        )
        _verify_node_scopes(
            _required_node(node.right, "relation lateral_cross right"),
            active=active,
            current_row_available=True,
            outer_row_available=True,
        )
        return
    for child in iter_plan_children(node):
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
        update: dict[str, object] = {}
        if node.row_scope_id is not None:
            update["row_scope_id"] = node.row_scope_id.prefixed(*scope)
        if node.key is not None:
            update["key"] = {
                name: _prefix_plan_row_scopes(value, scope)
                for name, value in node.key.items()
            }
        for field_name in ("left", "right", "fallback"):
            value = getattr(node, field_name)
            if value is not None:
                update[field_name] = _prefix_plan_row_scopes(value, scope)
        if node.cases is not None:
            update["cases"] = [
                branch.model_copy(
                    update={
                        "condition": _prefix_plan_row_scopes(
                            branch.condition,
                            scope,
                        ),
                        "value": _prefix_plan_row_scopes(branch.value, scope),
                    }
                )
                for branch in node.cases
            ]
        return node.model_copy(update=update) if update else node

    if isinstance(node, SeriesExpr):
        update = {}
        for field_name in ("start", "stop", "step", "source"):
            value = getattr(node, field_name)
            if value is not None:
                update[field_name] = _prefix_plan_row_scopes(value, scope)
        return node.model_copy(update=update) if update else node

    update = {}
    if node.row_scope_id is not None:
        update["row_scope_id"] = node.row_scope_id.prefixed(*scope)
    for field_name in ("source", "left", "right", "condition"):
        value = getattr(node, field_name)
        if value is not None:
            update[field_name] = _prefix_plan_row_scopes(value, scope)
    if node.sources is not None:
        update["sources"] = [
            _prefix_plan_row_scopes(source, scope) for source in node.sources
        ]
    if node.columns is not None:
        columns = {}
        for name, column in node.columns.items():
            column_update = {
                field_name: _prefix_plan_row_scopes(value, scope)
                for field_name in ("scalar", "series", "relation")
                if (value := getattr(column, field_name)) is not None
            }
            columns[name] = (
                column.model_copy(update=column_update) if column_update else column
            )
        update["columns"] = columns
    if node.new_columns is not None:
        update["new_columns"] = {
            name: _prefix_plan_row_scopes(value, scope)
            for name, value in node.new_columns.items()
        }
    return node.model_copy(update=update) if update else node


def _scalar_reference(node: ScalarExpr) -> PlanReference | None:
    kind = str(node.kind)
    reference_kind = {
        "column": PlanReferenceKind.CURRENT_COLUMN,
        "outer_column": PlanReferenceKind.OUTER_COLUMN,
        "point_column": PlanReferenceKind.POINT_COLUMN,
        "input": PlanReferenceKind.INPUT_SCALAR,
        "param_scalar": PlanReferenceKind.PARAMETER_SCALAR,
    }.get(kind)
    if reference_kind is not None:
        return PlanReference(
            reference_kind,
            _required_id(node.name, kind),
            row_scope_id=node.row_scope_id if kind == "column" else None,
        )
    if kind == "param_lookup":
        return PlanReference(
            PlanReferenceKind.PARAMETER_TABLE,
            _required_id(node.table_id, kind),
        )
    return None


def _series_reference(node: SeriesExpr) -> PlanReference | None:
    kind = str(node.kind)
    if kind == "input":
        return PlanReference(
            PlanReferenceKind.INPUT_SERIES,
            _required_id(node.name, kind),
        )
    if kind == "param_series":
        return PlanReference(
            PlanReferenceKind.PARAMETER_SERIES,
            _required_id(node.name, kind),
        )
    return None


def _relation_reference(node: RelationExpr) -> PlanReference | None:
    kind = str(node.kind)
    if kind == "input":
        return PlanReference(
            PlanReferenceKind.INPUT_TABLE,
            _required_id(node.name, kind),
        )
    if kind == "table":
        return PlanReference(
            PlanReferenceKind.PARAMETER_TABLE,
            _required_id(node.table_id, kind),
        )
    return None


def _required_node[NodeT: PlanNode](node: NodeT | None, path: str) -> NodeT:
    if node is None:
        msg = f"validated relation plan is missing {path}"
        raise ValueError(msg)
    return node


def _required_id(value: str | None, operation: str) -> str:
    if not value:
        msg = f"validated {operation} plan reference has no id"
        raise ValueError(msg)
    return value


__all__ = [
    "PlanNode",
    "PlanReference",
    "PlanReferenceKind",
    "PlanReferences",
    "RelationOperation",
    "RelationPlanBinderError",
    "RelationPlanScopeError",
    "free_row_references",
    "iter_plan_children",
    "plan_input_refs",
    "plan_references",
    "prefix_plan_row_scopes",
    "relation_operation",
    "relation_operations",
    "verify_plan_scopes",
    "walk_plan",
]
