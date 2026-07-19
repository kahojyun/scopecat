"""Proof-carrying symbolic point domains and stable logical point identity."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import InitVar, dataclass, field, replace
from itertools import product
from typing import cast

from scopecat.compiler.relations.evaluation import (
    EvalContext,
    ParameterRelationData,
    evaluate_relation_in_context,
    evaluate_relation_ordinals,
)
from scopecat.compiler.relations.model import (
    CellValue,
    Row,
)
from scopecat.compiler.relations.point_domain import (
    PointCardinality,
    PointDomainAnalysis,
    PointDomainExpr,
    PointDomainPath,
    PointDomainShapeError,
    PointProduct,
    PointRelationRows,
    PointUnit,
    PointZip,
    analyze_point_domain,
    decompose_product_ordinal,
    iter_point_relation_rows,
    map_point_relation_rows,
)
from scopecat.compiler.relations.uses import RelationUseId
from scopecat.compiler.relations.verification import (
    PlanImportNamespace,
    RelationPlanVerificationError,
    RowType,
    verify_relation_plan,
)
from scopecat.compiler.semantic.value_expressions import TableValueExpr
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.point_identity import LogicalPointId, PointDomainId
from scopecat.kernel.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Quantity,
    Scalar,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_validation import ValueValidationError, coerce_literal

type PointRowNormalizer = Callable[[Row], Mapping[str, object]]
type CompilerPointDomainExpr = PointDomainExpr[TableValueExpr]


@dataclass(frozen=True, slots=True)
class PointDomain:
    """One canonical algebra tree defining an ordered logical point space."""

    root: CompilerPointDomainExpr
    entity_columns: tuple[str, ...] = ()
    id: str = "root"

    def __post_init__(self) -> None:
        if not self.id:
            msg = "point domain id must be non-empty"
            raise ValueError(msg)
        object.__setattr__(self, "root", _copy_root(self.root))
        object.__setattr__(self, "entity_columns", tuple(self.entity_columns))

    @property
    def value_type(self) -> Table:
        return _analyze(self.root).root.value_type

    @property
    def row_type(self) -> RowType:
        return RowType.from_table(self.value_type)

    @property
    def coordinate_columns(self) -> tuple[TableColumn, ...]:
        """Return the statically typed coordinate projection of this domain."""

        return tuple(
            column
            for column in self.value_type.columns
            if is_point_coordinate_type(column.value_type)
        )


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
    """The selected backend failed while evaluating the symbolic point root."""

    def __init__(self, path: PointDomainPath, error: Exception) -> None:
        self.path = path
        self.error = error
        rendered = "/".join(str(part) for part in path)
        prefix = f"point domain {rendered}" if rendered else "point domain root"
        super().__init__(f"{prefix} failed: {error}")


class PointDomainValueError(ValueError):
    """A materialized point row violated the verified table contract."""

    def __init__(self, error: ValueValidationError) -> None:
        self.error = error
        super().__init__(str(error))


@dataclass(frozen=True, slots=True)
class VerifiedPointDomainRelation:
    """One nominal relation use and its diagnostic structural location."""

    id: RelationUseId
    path: PointDomainPath
    value: TableValueExpr


@dataclass(frozen=True, slots=True)
class VerifiedPointDomain:
    """A defensively snapshotted point domain with all root invariants checked."""

    program_id: InitVar[str]
    source: InitVar[PointDomain]
    _id: PointDomainId = field(init=False)
    _domain: PointDomain = field(init=False)
    _analysis: PointDomainAnalysis = field(init=False)
    relation_leaves: tuple[VerifiedPointDomainRelation, ...] = field(init=False)
    cardinality: PointCardinality = field(init=False)

    def __post_init__(self, program_id: str, source: PointDomain) -> None:
        domain_id, analysis, relation_leaves = _verified_point_domain_components(
            source,
            program_id=program_id,
        )
        object.__setattr__(self, "_id", domain_id)
        object.__setattr__(self, "_domain", _copy_domain(source))
        object.__setattr__(self, "_analysis", analysis)
        object.__setattr__(self, "relation_leaves", tuple(relation_leaves))
        object.__setattr__(self, "cardinality", analysis.root.cardinality)

    @property
    def id(self) -> PointDomainId:
        return self._id

    @property
    def domain(self) -> PointDomain:
        return _copy_domain(self._domain)

    @property
    def root(self) -> PointDomainExpr[TableValueExpr]:
        return _copy_root(self._domain.root)

    @property
    def entity_columns(self) -> tuple[str, ...]:
        return self._domain.entity_columns

    @property
    def value_type(self) -> Table:
        return self._analysis.root.value_type

    @property
    def row_type(self) -> RowType:
        return self._domain.row_type

    @property
    def coordinate_columns(self) -> tuple[TableColumn, ...]:
        return self._domain.coordinate_columns

    @property
    def analysis(self) -> PointDomainAnalysis:
        return self._analysis


@dataclass(frozen=True, slots=True, init=False)
class MaterializedPoint:
    """One concrete point retaining its canonical logical identity."""

    logical_id: LogicalPointId
    _row: Row

    def __init__(
        self,
        logical_id: LogicalPointId,
        row: Mapping[str, CellValue],
    ) -> None:
        object.__setattr__(self, "logical_id", logical_id)
        object.__setattr__(self, "_row", _snapshot_row(row))

    @property
    def row(self) -> Row:
        return _snapshot_row(self._row)

    @property
    def logical_ordinal(self) -> int:
        return self.logical_id.logical_ordinal


@dataclass(frozen=True, slots=True, init=False)
class MaterializedPointDomain:
    """The complete canonical ordered materialization of one symbolic domain."""

    id: PointDomainId
    points: tuple[MaterializedPoint, ...]
    cardinality: PointCardinality
    declared_cardinality: PointCardinality

    def __init__(
        self,
        domain_id: PointDomainId,
        points: Sequence[MaterializedPoint],
        declared_cardinality: PointCardinality,
    ) -> None:
        selected = tuple(points)
        if any(point.logical_id.domain_id != domain_id for point in selected):
            msg = "materialized point identities must belong to their domain"
            raise ValueError(msg)
        if any(
            point.logical_id != LogicalPointId(domain_id, ordinal)
            for ordinal, point in enumerate(selected)
        ):
            msg = (
                "materialized point identities must follow canonical contiguous "
                "ordinal order"
            )
            raise ValueError(msg)
        object.__setattr__(self, "id", domain_id)
        object.__setattr__(self, "points", selected)
        object.__setattr__(self, "cardinality", PointCardinality.exact(len(selected)))
        object.__setattr__(
            self,
            "declared_cardinality",
            declared_cardinality,
        )


def verify_point_domain(
    domain: PointDomain,
    *,
    program_id: str,
) -> VerifiedPointDomain:
    """Check the complete algebra, exact leaf roles, and coordinate contract."""

    return VerifiedPointDomain(program_id, domain)


def _verified_point_domain_components(
    domain: PointDomain,
    *,
    program_id: str,
) -> tuple[
    PointDomainId,
    PointDomainAnalysis,
    tuple[VerifiedPointDomainRelation, ...],
]:
    """Validate and derive the fields stored by a verified point domain."""

    domain_id = PointDomainId(program_id=program_id, domain_id=domain.id)
    identity_issues = _relation_use_identity_issues(domain.root)
    if identity_issues:
        raise PointDomainVerificationError(identity_issues)
    try:
        analysis = _analyze(domain.root)
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
    issues = _point_domain_issues(domain, analysis)
    if issues:
        raise PointDomainVerificationError(issues)
    relations = tuple(
        VerifiedPointDomainRelation(
            leaf.relation_use_id,
            path,
            leaf.rows,
        )
        for path, leaf in iter_point_relation_rows(domain.root)
    )
    return (
        domain_id,
        analysis,
        relations,
    )


def materialize_point_domain(
    verified: VerifiedPointDomain,
    params: ParameterRelationData,
    *,
    row_normalizer: PointRowNormalizer | None = None,
) -> MaterializedPointDomain:
    """Coerce every row before assigning canonical ordinal identities."""

    rows = _materialize_node(
        verified.root,
        params=params,
        ambient_row={},
        path=(),
    )
    normalized_rows: list[Mapping[str, object]] = list(rows)
    if row_normalizer is not None:
        normalized_rows = [row_normalizer(dict(row)) for row in rows]
    try:
        typed_rows = cast(
            "tuple[dict[str, object], ...]",
            coerce_literal(
                verified.value_type,
                normalized_rows,
                path=("points",),
            ),
        )
    except ValueValidationError as error:
        raise PointDomainValueError(error) from error
    points = tuple(
        MaterializedPoint(
            LogicalPointId(verified.id, ordinal),
            cast("Mapping[str, CellValue]", row),
        )
        for ordinal, row in enumerate(typed_rows)
    )
    return MaterializedPointDomain(
        verified.id,
        points,
        verified.cardinality,
    )


def materialize_point_domain_ordinals(
    verified: VerifiedPointDomain,
    params: ParameterRelationData,
    ordinals: Sequence[int],
    *,
    max_points: int,
    row_normalizer: PointRowNormalizer | None = None,
) -> tuple[MaterializedPoint, ...]:
    """Materialize selected ordinals without expanding the complete point algebra."""

    selected = tuple(ordinals)
    if type(max_points) is not int or max_points <= 0:
        raise ValueError("point selection budget must be a positive integer")
    if len(selected) > max_points:
        raise ValueError("point selection exceeds the requested budget")
    point_count = _exact_node_count(verified.analysis, ())
    if any(ordinal < 0 or ordinal >= point_count for ordinal in selected):
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
    row_type = replace(
        verified.value_type,
        min_rows=1,
        max_rows=1,
    )
    try:
        typed_rows = {
            ordinal: cast(
                "tuple[dict[str, object], ...]",
                coerce_literal(
                    row_type,
                    [normalized[ordinal]],
                    path=("points", ordinal),
                ),
            )[0]
            for ordinal in unique_ordinals
        }
    except ValueValidationError as error:
        raise PointDomainValueError(error) from error
    points = {
        ordinal: MaterializedPoint(
            LogicalPointId(verified.id, ordinal),
            cast("Mapping[str, CellValue]", typed_rows[ordinal]),
        )
        for ordinal in unique_ordinals
    }
    return tuple(points[ordinal] for ordinal in selected)


def _materialize_node_ordinals(
    node: PointDomainExpr[TableValueExpr],
    *,
    ordinals: tuple[int, ...],
    analysis: PointDomainAnalysis,
    params: ParameterRelationData,
    ambient_row: Row,
    path: PointDomainPath,
) -> dict[int, Row]:
    if isinstance(node, PointUnit):
        return {ordinal: {} for ordinal in ordinals}
    if isinstance(node, PointRelationRows):
        try:
            selected_rows = evaluate_relation_ordinals(
                node.rows.plan,
                EvalContext(params=params, point_row=ambient_row),
                ordinals,
                max_points=len(ordinals),
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            raise PointDomainEvaluationError((*path, "rows"), error) from error
        return dict(zip(ordinals, selected_rows, strict=True))
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
            ordinal: _merge_row_group(
                tuple(source[ordinal] for source in sources),
                path=path,
            )
            for ordinal in ordinals
        }
    if isinstance(node, PointProduct):
        child_paths = tuple(
            (*path, "factors", index) for index in range(len(node.factors))
        )
        child_counts = tuple(
            _exact_node_count(analysis, child_path) for child_path in child_paths
        )
        child_ordinals_by_root = {
            ordinal: decompose_product_ordinal(ordinal, child_counts)
            for ordinal in ordinals
        }
        children = tuple(
            _materialize_node_ordinals(
                factor,
                ordinals=tuple(
                    sorted(
                        {child_ordinals_by_root[ordinal][index] for ordinal in ordinals}
                    )
                ),
                analysis=analysis,
                params=params,
                ambient_row=ambient_row,
                path=child_paths[index],
            )
            for index, factor in enumerate(node.factors)
        )
        return {
            ordinal: _merge_row_group(
                tuple(
                    child[child_ordinals_by_root[ordinal][index]]
                    for index, child in enumerate(children)
                ),
                path=path,
            )
            for ordinal in ordinals
        }
    left_path = (*path, "left")
    right_path = (*path, "right")
    right_count = _exact_node_count(analysis, right_path)
    left_ordinals_by_root = {ordinal: ordinal // right_count for ordinal in ordinals}
    right_ordinals_by_root = {ordinal: ordinal % right_count for ordinal in ordinals}
    left_rows = _materialize_node_ordinals(
        node.left,
        ordinals=tuple(sorted(set(left_ordinals_by_root.values()))),
        analysis=analysis,
        params=params,
        ambient_row=ambient_row,
        path=left_path,
    )
    right_rows_by_left: dict[int, dict[int, Row]] = {}
    for left_ordinal, left_row in left_rows.items():
        right_ordinals = tuple(
            sorted(
                {
                    right_ordinals_by_root[ordinal]
                    for ordinal in ordinals
                    if left_ordinals_by_root[ordinal] == left_ordinal
                }
            )
        )
        right_rows_by_left[left_ordinal] = _materialize_node_ordinals(
            node.right,
            ordinals=right_ordinals,
            analysis=analysis,
            params=params,
            ambient_row=_merge_row_group(
                (ambient_row, left_row),
                path=right_path,
            ),
            path=right_path,
        )
    return {
        ordinal: _merge_row_group(
            (
                left_rows[left_ordinals_by_root[ordinal]],
                right_rows_by_left[left_ordinals_by_root[ordinal]][
                    right_ordinals_by_root[ordinal]
                ],
            ),
            path=path,
        )
        for ordinal in ordinals
    }


def _exact_node_count(
    analysis: PointDomainAnalysis,
    path: PointDomainPath,
) -> int:
    cardinality = analysis.facts[path].cardinality
    if cardinality.maximum != cardinality.minimum:
        rendered = "/".join(str(part) for part in path) or "root"
        raise ValueError(
            f"point ordinal selection requires exact cardinality at {rendered}"
        )
    return cardinality.minimum


def _point_domain_issues(
    domain: PointDomain,
    analysis: PointDomainAnalysis,
) -> tuple[PointDomainVerificationIssue, ...]:
    issues: list[PointDomainVerificationIssue] = []
    _verify_domain_leaf_roles(
        domain.root,
        analysis=analysis,
        path=(),
        ambient_row=None,
        issues=issues,
    )

    entity_columns = domain.entity_columns
    for duplicate in sorted(
        {
            column_id
            for column_id in entity_columns
            if entity_columns.count(column_id) > 1
        }
    ):
        issues.append(
            PointDomainVerificationIssue(
                "point_domain_entity_column_duplicate",
                ("entity_columns", duplicate),
                f"point entity column {duplicate!r} is declared more than once",
            )
        )
    columns = {column.id: column for column in analysis.root.value_type.columns}
    for column_id in dict.fromkeys(entity_columns):
        column = columns.get(column_id)
        if column is None:
            issues.append(
                PointDomainVerificationIssue(
                    "point_domain_entity_column_missing",
                    ("entity_columns", column_id),
                    f"point entity column {column_id!r} does not exist",
                )
            )
        elif not isinstance(column.value_type.atom, Entity):
            issues.append(
                PointDomainVerificationIssue(
                    "point_domain_entity_column_type",
                    ("entity_columns", column_id),
                    f"point entity column {column_id!r} must have Entity type",
                )
            )
    return tuple(issues)


def _relation_use_identity_issues(
    root: PointDomainExpr[TableValueExpr],
) -> tuple[PointDomainVerificationIssue, ...]:
    first_path_by_id: dict[RelationUseId, PointDomainPath] = {}
    issues: list[PointDomainVerificationIssue] = []
    for path, leaf in iter_point_relation_rows(root):
        first_path = first_path_by_id.setdefault(leaf.relation_use_id, path)
        if first_path != path:
            rendered = "/".join(str(part) for part in first_path) or "root"
            issues.append(
                PointDomainVerificationIssue(
                    "point_domain_relation_use_duplicate",
                    (*path, "rows"),
                    "point-domain relation use identity is already owned by "
                    f"{rendered}",
                )
            )
    return tuple(issues)


def _verify_domain_leaf_roles(
    node: PointDomainExpr[TableValueExpr],
    *,
    analysis: PointDomainAnalysis,
    path: PointDomainPath,
    ambient_row: RowType | None,
    issues: list[PointDomainVerificationIssue],
) -> None:
    if isinstance(node, PointUnit):
        return
    if isinstance(node, PointRelationRows):
        _verify_relation_leaf_role(
            node.rows,
            path=path,
            ambient_row=ambient_row,
            issues=issues,
        )
        return
    if isinstance(node, PointProduct):
        for index, factor in enumerate(node.factors):
            _verify_domain_leaf_roles(
                factor,
                analysis=analysis,
                path=(*path, "factors", index),
                ambient_row=ambient_row,
                issues=issues,
            )
        return
    if isinstance(node, PointZip):
        for index, source in enumerate(node.sources):
            _verify_domain_leaf_roles(
                source,
                analysis=analysis,
                path=(*path, "sources", index),
                ambient_row=ambient_row,
                issues=issues,
            )
        return
    left_path = (*path, "left")
    _verify_domain_leaf_roles(
        node.left,
        analysis=analysis,
        path=left_path,
        ambient_row=ambient_row,
        issues=issues,
    )
    right_ambient = _extend_row_type(
        ambient_row,
        analysis.facts[left_path].value_type,
    )
    _verify_domain_leaf_roles(
        node.right,
        analysis=analysis,
        path=(*path, "right"),
        ambient_row=right_ambient,
        issues=issues,
    )


def _verify_relation_leaf_role(
    value: TableValueExpr,
    *,
    path: PointDomainPath,
    ambient_row: RowType | None,
    issues: list[PointDomainVerificationIssue],
) -> None:
    plan = value.plan
    row_interface = plan.external_row_interface
    open_interface = (
        row_interface.current is not None
        or row_interface.outer is not None
        or bool(row_interface.arguments)
        or (row_interface.point is not None and ambient_row is None)
    )
    if open_interface:
        issues.append(
            PointDomainVerificationIssue(
                "point_domain_open_row_interface",
                (*path, "rows"),
                "point-domain relation has an unbound external row",
            )
        )
    if any(
        imported.namespace is PlanImportNamespace.INPUT for imported in plan.imports
    ):
        issues.append(
            PointDomainVerificationIssue(
                "point_domain_open_input",
                (*path, "rows"),
                "point-domain relation depends on an unresolved input",
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
                current_row=None,
                outer_row=None,
                row_arguments={},
            ),
            expected_type=plan.certified_type,
        )
    except RelationPlanVerificationError as error:
        issues.append(
            PointDomainVerificationIssue(
                error.code,
                (*path, "rows", *error.path),
                error.reason,
            )
        )
        return
    if (
        reverified.certified_type != plan.certified_type
        or reverified.facts != plan.facts
        or reverified.imports != plan.imports
        or reverified.runtime_obligations != plan.runtime_obligations
        or reverified.external_row_interface != plan.external_row_interface
    ):
        issues.append(
            PointDomainVerificationIssue(
                "point_domain_stale_relation_proof",
                (*path, "rows"),
                "point-domain relation proof does not match its structural role",
            )
        )


def _extend_row_type(parent: RowType | None, child: Table) -> RowType:
    parent_columns = parent.columns if parent is not None else ()
    return RowType(
        (*parent_columns, *child.columns),
        (parent.allow_extra_columns if parent is not None else False)
        or child.allow_extra_columns,
    )


def _materialize_node(
    node: PointDomainExpr[TableValueExpr],
    *,
    params: ParameterRelationData,
    ambient_row: Row,
    path: PointDomainPath,
) -> list[Row]:
    if isinstance(node, PointUnit):
        return [{}]
    if isinstance(node, PointRelationRows):
        try:
            return evaluate_relation_in_context(
                node.rows.plan,
                EvalContext(params=params, point_row=ambient_row),
            )
        except (ArithmeticError, KeyError, TypeError, ValueError) as error:
            raise PointDomainEvaluationError((*path, "rows"), error) from error
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
        return [_merge_row_group(group, path=path) for group in product(*factor_rows)]
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
        lengths = tuple(len(rows) for rows in source_rows)
        if len(set(lengths)) != 1:
            error = ValueError(
                "point zip sources materialized with unequal lengths: "
                + ", ".join(str(length) for length in lengths)
            )
            raise PointDomainEvaluationError(path, error)
        return [
            _merge_row_group(group, path=path)
            for group in zip(*source_rows, strict=True)
        ]
    left_rows = _materialize_node(
        node.left,
        params=params,
        ambient_row=ambient_row,
        path=(*path, "left"),
    )
    rows: list[Row] = []
    for left in left_rows:
        right_ambient = _merge_row_group(
            (ambient_row, left),
            path=(*path, "right"),
        )
        right_rows = _materialize_node(
            node.right,
            params=params,
            ambient_row=right_ambient,
            path=(*path, "right"),
        )
        rows.extend(_merge_row_group((left, right), path=path) for right in right_rows)
    return rows


def _merge_row_group(
    rows: Sequence[Mapping[str, CellValue]],
    *,
    path: PointDomainPath,
) -> Row:
    merged: Row = {}
    for row in rows:
        duplicates = sorted(set(merged) & set(row))
        if duplicates:
            error = ValueError(
                "point-domain rows contain duplicate columns: " + ", ".join(duplicates)
            )
            raise PointDomainEvaluationError(path, error)
        merged.update(row)
    return merged


def _copy_domain(domain: PointDomain) -> PointDomain:
    return PointDomain(
        id=domain.id,
        root=_copy_root(domain.root),
        entity_columns=domain.entity_columns,
    )


def _copy_root(
    root: CompilerPointDomainExpr,
) -> CompilerPointDomainExpr:
    return map_point_relation_rows(
        root,
        lambda value, _path: value,
    )


def _analyze(root: PointDomainExpr[TableValueExpr]) -> PointDomainAnalysis:
    return analyze_point_domain(
        root,
        leaf_value_type=lambda value, _path: value.value_type,
    )


def _snapshot_row(row: Mapping[str, CellValue]) -> Row:
    """Copy known mutable carriers while treating opaque payloads as atoms."""

    return cast("Row", {key: _snapshot_value(value) for key, value in row.items()})


def _snapshot_value(value: object) -> object:
    if isinstance(value, PayloadValue):
        return PayloadValue(
            schema_id=value.schema_id,
            payload=_snapshot_value(value.payload),
        )
    if isinstance(value, dict):
        return {
            key: _snapshot_value(item)
            for key, item in cast("dict[object, object]", value).items()
        }
    if isinstance(value, list):
        return [_snapshot_value(item) for item in cast("list[object]", value)]
    if isinstance(value, tuple):
        return tuple(
            _snapshot_value(item) for item in cast("tuple[object, ...]", value)
        )
    return value


def is_point_coordinate_type(value_type: Scalar) -> bool:
    """Return whether a point value belongs to the dataset coordinate domain."""

    return isinstance(
        value_type.atom,
        Bool | Int | Float | String | Quantity | Entity,
    )


__all__ = [
    "CompilerPointDomainExpr",
    "MaterializedPoint",
    "MaterializedPointDomain",
    "PointCardinality",
    "PointDomain",
    "PointDomainEvaluationError",
    "PointDomainValueError",
    "PointDomainVerificationError",
    "PointDomainVerificationIssue",
    "PointRowNormalizer",
    "VerifiedPointDomain",
    "VerifiedPointDomainRelation",
    "is_point_coordinate_type",
    "materialize_point_domain",
    "materialize_point_domain_ordinals",
    "verify_point_domain",
]
