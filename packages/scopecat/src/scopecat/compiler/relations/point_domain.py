"""Backend-neutral algebra for ordered logical point domains.

The algebra records *how* point rows compose without embedding that composition
in any particular relation language.  Authoring and compiler IR use the same
tree with different relation-leaf payloads.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from scopecat.compiler.relations.uses import RelationUseId
from scopecat.kernel.value_types import Table, TableColumn

type PointDomainPath = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class PointCardinality:
    """Known lower and upper bounds for an ordered point domain."""

    minimum: int
    maximum: int | None

    def __post_init__(self) -> None:
        if self.minimum < 0:
            msg = "point cardinality minimum must be non-negative"
            raise ValueError(msg)
        if self.maximum is not None and self.maximum < self.minimum:
            msg = "point cardinality maximum must not be smaller than minimum"
            raise ValueError(msg)

    @classmethod
    def exact(cls, count: int) -> PointCardinality:
        return cls(count, count)


@dataclass(frozen=True, slots=True)
class PointUnit:
    """The exact-one empty-row identity for point products."""


@dataclass(frozen=True, slots=True)
class PointRelationRows[LeafT]:
    """One ordered relation-backed leaf."""

    rows: LeafT
    relation_use_id: RelationUseId = field(default_factory=RelationUseId.fresh)


@dataclass(frozen=True, slots=True)
class PointProduct[LeafT]:
    """Independent Cartesian factors evaluated in one ambient environment."""

    factors: tuple[PointDomainExpr[LeafT], ...]

    def __post_init__(self) -> None:
        factors = tuple(self.factors)
        if len(factors) < 2:
            msg = "canonical point product requires at least two factors"
            raise ValueError(msg)
        if any(isinstance(factor, PointUnit | PointProduct) for factor in factors):
            msg = "point product factors must be canonical"
            raise ValueError(msg)
        object.__setattr__(self, "factors", factors)


@dataclass(frozen=True, slots=True)
class PointDependentProduct[LeafT]:
    """A product whose right side is evaluated once per left row."""

    left: PointDomainExpr[LeafT]
    right: PointDomainExpr[LeafT]

    def __post_init__(self) -> None:
        if isinstance(self.left, PointUnit) or isinstance(self.right, PointUnit):
            msg = "canonical dependent product cannot contain point unit"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PointZip[LeafT]:
    """Positional composition of equally long child domains."""

    sources: tuple[PointDomainExpr[LeafT], ...]

    def __post_init__(self) -> None:
        sources = tuple(self.sources)
        if len(sources) < 2:
            msg = "canonical point zip requires at least two sources"
            raise ValueError(msg)
        if any(isinstance(source, PointZip) for source in sources):
            msg = "point zip sources must be canonical"
            raise ValueError(msg)
        object.__setattr__(self, "sources", sources)


type PointDomainExpr[LeafT] = (
    PointUnit
    | PointRelationRows[LeafT]
    | PointProduct[LeafT]
    | PointDependentProduct[LeafT]
    | PointZip[LeafT]
)

POINT_UNIT = PointUnit()


def point_rows[LeafT](rows: LeafT) -> PointRelationRows[LeafT]:
    """Lift one relation payload into the point-domain algebra."""

    return PointRelationRows(rows)


def point_product[LeafT](
    *factors: PointDomainExpr[LeafT],
) -> PointDomainExpr[LeafT]:
    """Build a canonical ordered product without reordering or deduplication."""

    flattened: list[PointDomainExpr[LeafT]] = []
    for factor in factors:
        if isinstance(factor, PointUnit):
            continue
        if isinstance(factor, PointProduct):
            flattened.extend(factor.factors)
        else:
            flattened.append(factor)
    if not flattened:
        return POINT_UNIT
    if len(flattened) == 1:
        return flattened[0]
    return PointProduct(tuple(flattened))


def point_dependent_product[LeafT](
    left: PointDomainExpr[LeafT],
    right: PointDomainExpr[LeafT],
) -> PointDomainExpr[LeafT]:
    """Build directional point composition, applying only the Unit laws."""

    if isinstance(left, PointUnit):
        return right
    if isinstance(right, PointUnit):
        return left
    return PointDependentProduct(left, right)


def point_zip[LeafT](
    *sources: PointDomainExpr[LeafT],
) -> PointDomainExpr[LeafT]:
    """Build a canonical positional composition.

    Unit is deliberately not an identity for Zip: its one empty row constrains
    every other source to have exactly one materialized row.
    """

    flattened: list[PointDomainExpr[LeafT]] = []
    for source in sources:
        if isinstance(source, PointZip):
            flattened.extend(source.sources)
        else:
            flattened.append(source)
    if not flattened:
        msg = "point zip requires at least one source"
        raise ValueError(msg)
    if len(flattened) == 1:
        return flattened[0]
    return PointZip(tuple(flattened))


def walk_point_domain[LeafT](
    root: PointDomainExpr[LeafT],
) -> Iterator[tuple[PointDomainPath, PointDomainExpr[LeafT]]]:
    """Walk a canonical domain in deterministic preorder."""

    def visit(
        node: PointDomainExpr[LeafT],
        path: PointDomainPath,
    ) -> Iterator[tuple[PointDomainPath, PointDomainExpr[LeafT]]]:
        yield path, node
        if isinstance(node, PointProduct):
            for index, factor in enumerate(node.factors):
                yield from visit(factor, (*path, "factors", index))
        elif isinstance(node, PointDependentProduct):
            yield from visit(node.left, (*path, "left"))
            yield from visit(node.right, (*path, "right"))
        elif isinstance(node, PointZip):
            for index, source in enumerate(node.sources):
                yield from visit(source, (*path, "sources", index))

    yield from visit(root, ())


def iter_point_relation_rows[LeafT](
    root: PointDomainExpr[LeafT],
) -> Iterator[tuple[PointDomainPath, PointRelationRows[LeafT]]]:
    """Yield relation leaves with their structural node paths."""

    for path, node in walk_point_domain(root):
        if isinstance(node, PointRelationRows):
            yield path, node


def map_point_relation_rows[LeafT, MappedLeafT](
    root: PointDomainExpr[LeafT],
    transform: Callable[[LeafT, PointDomainPath], MappedLeafT],
) -> PointDomainExpr[MappedLeafT]:
    """Map leaf payloads while preserving the exact canonical tree and paths."""

    def visit(
        node: PointDomainExpr[LeafT],
        path: PointDomainPath,
    ) -> PointDomainExpr[MappedLeafT]:
        if isinstance(node, PointUnit):
            return POINT_UNIT
        if isinstance(node, PointRelationRows):
            return PointRelationRows(
                transform(node.rows, path),
                relation_use_id=node.relation_use_id,
            )
        if isinstance(node, PointProduct):
            return PointProduct(
                tuple(
                    visit(factor, (*path, "factors", index))
                    for index, factor in enumerate(node.factors)
                )
            )
        if isinstance(node, PointDependentProduct):
            return PointDependentProduct(
                visit(node.left, (*path, "left")),
                visit(node.right, (*path, "right")),
            )
        return PointZip(
            tuple(
                visit(source, (*path, "sources", index))
                for index, source in enumerate(node.sources)
            )
        )

    return visit(root, ())


class PointDomainShapeError(ValueError):
    """A domain tree has incompatible schemas or cardinality bounds."""

    def __init__(self, code: str, path: PointDomainPath, message: str) -> None:
        self.code = code
        self.path = path
        self.message = message
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class PointDomainShape:
    """The table schema and cardinality projected for one algebra node."""

    value_type: Table

    @property
    def cardinality(self) -> PointCardinality:
        return PointCardinality(self.value_type.min_rows, self.value_type.max_rows)


@dataclass(frozen=True, slots=True)
class PointDomainAnalysis:
    """Root and per-node shapes for one canonical domain tree."""

    root: PointDomainShape
    facts: Mapping[PointDomainPath, PointDomainShape]

    def __post_init__(self) -> None:
        facts = MappingProxyType(dict(self.facts))
        if facts.get(()) != self.root:
            msg = "point-domain analysis root fact must match its root shape"
            raise ValueError(msg)
        object.__setattr__(self, "facts", facts)


def analyze_point_domain[LeafT](
    root: PointDomainExpr[LeafT],
    *,
    leaf_value_type: Callable[[LeafT, PointDomainPath], Table],
) -> PointDomainAnalysis:
    """Compute schema/cardinality facts without inspecting relation syntax."""

    facts: dict[PointDomainPath, PointDomainShape] = {}

    def analyze(
        node: PointDomainExpr[LeafT],
        path: PointDomainPath,
    ) -> PointDomainShape:
        if isinstance(node, PointUnit):
            shape = PointDomainShape(Table(columns=(), min_rows=1, max_rows=1))
        elif isinstance(node, PointRelationRows):
            shape = PointDomainShape(leaf_value_type(node.rows, path))
        elif isinstance(node, PointProduct):
            children = tuple(
                analyze(factor, (*path, "factors", index))
                for index, factor in enumerate(node.factors)
            )
            shape = _product_shape(children, path=path)
        elif isinstance(node, PointDependentProduct):
            children = (
                analyze(node.left, (*path, "left")),
                analyze(node.right, (*path, "right")),
            )
            shape = _product_shape(children, path=path)
        else:
            children = tuple(
                analyze(source, (*path, "sources", index))
                for index, source in enumerate(node.sources)
            )
            shape = _zip_shape(children, path=path)
        facts[path] = shape
        return shape

    root_shape = analyze(root, ())
    return PointDomainAnalysis(
        root=root_shape,
        facts=MappingProxyType(dict(facts)),
    )


def _product_shape(
    children: tuple[PointDomainShape, ...],
    *,
    path: PointDomainPath,
) -> PointDomainShape:
    tables = tuple(child.value_type for child in children)
    columns = _merged_columns(tables, path=path)
    minimum = 1
    for table in tables:
        minimum *= table.min_rows
    maximum = _product_maximum(tuple(table.max_rows for table in tables))
    primary_key = (
        tuple(column_id for table in tables for column_id in table.primary_key)
        if tables and all(table.primary_key for table in tables)
        else ()
    )
    return PointDomainShape(
        Table(
            columns=columns,
            primary_key=primary_key,
            min_rows=minimum,
            max_rows=maximum,
            allow_extra_columns=any(table.allow_extra_columns for table in tables),
        )
    )


def _zip_shape(
    children: tuple[PointDomainShape, ...],
    *,
    path: PointDomainPath,
) -> PointDomainShape:
    tables = tuple(child.value_type for child in children)
    columns = _merged_columns(tables, path=path)
    minimum = max(table.min_rows for table in tables)
    finite_maximums = tuple(
        table.max_rows for table in tables if table.max_rows is not None
    )
    maximum = min(finite_maximums) if finite_maximums else None
    if maximum is not None and minimum > maximum:
        raise PointDomainShapeError(
            "point_domain_zip_cardinality_mismatch",
            path,
            "point zip sources have disjoint cardinality bounds",
        )
    primary_key = next(
        (table.primary_key for table in tables if table.primary_key),
        (),
    )
    return PointDomainShape(
        Table(
            columns=columns,
            primary_key=primary_key,
            min_rows=minimum,
            max_rows=maximum,
            allow_extra_columns=any(table.allow_extra_columns for table in tables),
        )
    )


def _merged_columns(
    tables: tuple[Table, ...],
    *,
    path: PointDomainPath,
) -> tuple[TableColumn, ...]:
    columns = tuple(column for table in tables for column in table.columns)
    column_ids = tuple(column.id for column in columns)
    duplicates = tuple(
        sorted(
            {column_id for column_id in column_ids if column_ids.count(column_id) > 1}
        )
    )
    if duplicates:
        raise PointDomainShapeError(
            "point_domain_duplicate_columns",
            path,
            "point-domain composition produces duplicate columns: "
            + ", ".join(duplicates),
        )
    return columns


def _product_maximum(maximums: tuple[int | None, ...]) -> int | None:
    if any(maximum == 0 for maximum in maximums):
        return 0
    if any(maximum is None for maximum in maximums):
        return None
    result = 1
    for maximum in maximums:
        if maximum is None:
            raise AssertionError("unknown point maximum was handled above")
        result *= maximum
    return result
