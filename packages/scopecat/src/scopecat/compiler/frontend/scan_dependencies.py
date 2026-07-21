"""Config-free dependency proofs for authored point scans.

Scan composition is ordered, so declaration order remains observable for
independent axes.  This pass changes that order only when an explicit point
dependency requires it.  Cartesian groups are associative scheduling regions;
zip branches remain positional and may not depend on one another.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.authoring._scan_intents import (
    ParameterScanIntent,
    PointScanIntent,
    Scan,
    ScanGroupIntent,
    ScanLeafIntent,
    iter_scan_leaves,
    scan_point_id,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_value_ref_input_id,
    internal_value_ref_point_dependencies,
    internal_value_ref_scalar_input_ids,
)
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import Scalar, ValueType

type ScanPath = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class ScanAxis:
    """One uniquely provided axis in declaration order."""

    id: str
    value_type: Scalar
    path: ScanPath
    declaration_ordinal: int


@dataclass(frozen=True, slots=True)
class ScanDependencyEdge:
    """A point value that must exist before one scan axis is generated."""

    producer_id: str
    consumer_id: str


@dataclass(frozen=True, slots=True)
class ScanDependencyIssue:
    """One authoring violation found while constructing the scan DAG."""

    code: str
    message: str
    path: ScanPath


class ScanDependencyError(ValueError):
    """The authored scans do not form a legal point-domain dependency graph."""

    def __init__(self, issues: Sequence[ScanDependencyIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


@dataclass(frozen=True, slots=True)
class VerifiedScanDependencyGraph:
    """A legal authored scan forest and its typed dependency edges.

    Scheduling is deliberately left to point-domain composition, where scans and
    the base domain can be ordered together instead of normalizing the scan forest
    once here and sorting the same top-level factors again later.
    """

    scans: tuple[Scan, ...]
    axes: tuple[ScanAxis, ...]
    edges: tuple[ScanDependencyEdge, ...]


def verify_scan_dependencies(
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object] | None = None,
    input_types: Mapping[str, ValueType] | None = None,
    external_point_types: Mapping[str, Scalar] | None = None,
) -> VerifiedScanDependencyGraph:
    """Verify point dependencies without choosing an execution schedule.

    ``inputs`` are invocation values already fixed for the run.  A free module
    input with the same id as a scan axis becomes a dependency on that axis;
    a fixed input remains a run-level literal.  ``external_point_types`` names
    coordinates supplied by an enclosing/base point source.
    """

    selected = tuple(scans)
    bound_input_ids = frozenset((inputs or {}).keys())
    expected_input_types = dict(input_types or {})
    external_types = dict(external_point_types or {})
    leaves = _scan_axes(selected)
    issues: list[ScanDependencyIssue] = []

    duplicate_ids = sorted(
        {
            axis_id
            for axis_id in (scan_point_id(leaf) for leaf, _path in leaves)
            if sum(
                scan_point_id(candidate) == axis_id
                for candidate, _candidate_path in leaves
            )
            > 1
        }
    )
    if duplicate_ids:
        issues.append(
            ScanDependencyIssue(
                "scan_axis_duplicate",
                "duplicate scan axis: " + ", ".join(duplicate_ids),
                (),
            )
        )
        raise ScanDependencyError(issues)

    axes = tuple(
        ScanAxis(
            id=scan_point_id(leaf),
            value_type=_scan_axis_type(leaf),
            path=path,
            declaration_ordinal=ordinal,
        )
        for ordinal, (leaf, path) in enumerate(leaves)
    )
    axes_by_id = {axis.id: axis for axis in axes}
    leaves_by_id = {scan_point_id(leaf): leaf for leaf, _path in leaves}
    ambiguous_providers = sorted(set(axes_by_id) & set(external_types))
    if ambiguous_providers:
        issues.extend(
            ScanDependencyIssue(
                "scan_dependency_provider_duplicate",
                f"point {axis_id!r} is provided by both a scan and the base "
                "point source",
                axes_by_id[axis_id].path,
            )
            for axis_id in ambiguous_providers
        )
        raise ScanDependencyError(issues)

    edges: list[ScanDependencyEdge] = []
    for axis in axes:
        leaf = leaves_by_id[axis.id]
        direct_types, free_input_types, free_input_ids = _scan_dependency_requirements(
            leaf
        )
        candidate_ids = set(direct_types)
        candidate_ids.update(free_input_ids - bound_input_ids)
        for dependency_id in sorted(
            candidate_ids,
            key=lambda item: (
                axes_by_id[item].declaration_ordinal if item in axes_by_id else -1,
                item,
            ),
        ):
            provider_type = (
                axes_by_id[dependency_id].value_type
                if dependency_id in axes_by_id
                else external_types.get(dependency_id)
            )
            required_type = direct_types.get(dependency_id)
            if required_type is None:
                selected_type = free_input_types.get(
                    dependency_id,
                    expected_input_types.get(dependency_id),
                )
                required_type = (
                    selected_type if isinstance(selected_type, Scalar) else None
                )
            if provider_type is None:
                issues.append(
                    ScanDependencyIssue(
                        "scan_dependency_missing",
                        f"scan axis {axis.id!r} depends on missing point "
                        f"{dependency_id!r}",
                        axis.path,
                    )
                )
                continue
            if required_type is None:
                issues.append(
                    ScanDependencyIssue(
                        "scan_dependency_type_unknown",
                        f"scan axis {axis.id!r} depends on point "
                        f"{dependency_id!r} without a scalar type",
                        axis.path,
                    )
                )
                continue
            if dependency_id == axis.id:
                issues.append(
                    ScanDependencyIssue(
                        "scan_dependency_self",
                        f"scan axis {axis.id!r} depends on itself",
                        axis.path,
                    )
                )
                continue
            if not is_assignable(
                provider_type,
                required_type,
            ):
                issues.append(
                    ScanDependencyIssue(
                        "scan_dependency_type_mismatch",
                        f"scan axis {axis.id!r} requires point {dependency_id!r} "
                        "with an incompatible value type",
                        axis.path,
                    )
                )
            edges.append(
                ScanDependencyEdge(
                    producer_id=dependency_id,
                    consumer_id=axis.id,
                )
            )

    dependencies = _axis_dependencies(edges, axes_by_id)
    issues.extend(_zip_dependency_issues(selected, dependencies, axes_by_id))
    cycle = _dependency_cycle(axes, dependencies)
    if cycle is not None:
        issues.append(
            ScanDependencyIssue(
                "scan_dependency_cycle",
                "scan dependency cycle: " + " -> ".join(cycle),
                axes_by_id[cycle[0]].path,
            )
        )
    if issues:
        raise ScanDependencyError(issues)

    return VerifiedScanDependencyGraph(
        scans=selected,
        axes=axes,
        edges=tuple(edges),
    )


def _scan_axes(scans: Sequence[Scan]) -> tuple[tuple[ScanLeafIntent, ScanPath], ...]:
    selected: list[tuple[ScanLeafIntent, ScanPath]] = []

    def visit(scan: Scan, path: ScanPath) -> None:
        if isinstance(scan, ScanGroupIntent):
            for index, child in enumerate(scan.scans):
                visit(child, (*path, "scans", index))
            return
        if not isinstance(scan, PointScanIntent | ParameterScanIntent):
            msg = "invalid scan handle"
            raise TypeError(msg)
        selected.append((scan, path))

    for index, scan in enumerate(scans):
        visit(scan, (index,))
    return tuple(selected)


def _scan_axis_type(scan: ScanLeafIntent) -> Scalar:
    value_type = scan.target.value_type
    if not isinstance(value_type, Scalar):
        msg = "scan target must carry a scalar value type"
        raise TypeError(msg)
    return value_type


def _scan_dependency_requirements(
    scan: ScanLeafIntent,
) -> tuple[dict[str, Scalar], dict[str, Scalar], frozenset[str]]:
    if not isinstance(scan, PointScanIntent) or not isinstance(scan.center, ValueRef):
        return {}, {}, frozenset()
    direct = {
        dependency.id: dependency.value_type
        for dependency in internal_value_ref_point_dependencies(scan.center)
    }
    direct_input_id = internal_value_ref_input_id(scan.center)
    direct_input_types = (
        {direct_input_id: scan.center.value_type}
        if direct_input_id is not None and isinstance(scan.center.value_type, Scalar)
        else {}
    )
    return (
        direct,
        direct_input_types,
        internal_value_ref_scalar_input_ids(scan.center),
    )


def _axis_dependencies(
    edges: Sequence[ScanDependencyEdge],
    axes_by_id: Mapping[str, ScanAxis],
) -> dict[str, set[str]]:
    dependencies = {axis_id: set[str]() for axis_id in axes_by_id}
    for edge in edges:
        if edge.producer_id in axes_by_id:
            dependencies[edge.consumer_id].add(edge.producer_id)
    return dependencies


def _zip_dependency_issues(
    scans: Sequence[Scan],
    dependencies: Mapping[str, set[str]],
    axes_by_id: Mapping[str, ScanAxis],
) -> tuple[ScanDependencyIssue, ...]:
    issues: list[ScanDependencyIssue] = []

    def visit(scan: Scan) -> None:
        if not isinstance(scan, ScanGroupIntent):
            return
        if scan.kind == "zip":
            branch_axes = [
                {scan_point_id(leaf) for leaf in iter_scan_leaves(child)}
                for child in scan.scans
            ]
            branch_by_axis = {
                axis_id: branch_index
                for branch_index, axis_ids in enumerate(branch_axes)
                for axis_id in axis_ids
            }
            for consumer_id, consumer_dependencies in dependencies.items():
                consumer_branch = branch_by_axis.get(consumer_id)
                if consumer_branch is None:
                    continue
                for producer_id in consumer_dependencies:
                    producer_branch = branch_by_axis.get(producer_id)
                    if (
                        producer_branch is not None
                        and producer_branch != consumer_branch
                    ):
                        issues.append(
                            ScanDependencyIssue(
                                "scan_zip_sibling_dependency",
                                f"zip scan axis {consumer_id!r} cannot depend on "
                                f"sibling axis {producer_id!r}",
                                axes_by_id[consumer_id].path,
                            )
                        )
        for child in scan.scans:
            visit(child)

    for scan in scans:
        visit(scan)
    return tuple(issues)


def _dependency_cycle(
    axes: Sequence[ScanAxis],
    dependencies: Mapping[str, set[str]],
) -> tuple[str, ...] | None:
    state: dict[str, int] = {}
    stack: list[str] = []
    ordinals = {axis.id: axis.declaration_ordinal for axis in axes}

    def visit(axis_id: str) -> tuple[str, ...] | None:
        state[axis_id] = 1
        stack.append(axis_id)
        for dependency_id in sorted(
            dependencies[axis_id],
            key=lambda item: (ordinals[item], item),
        ):
            if state.get(dependency_id, 0) == 0:
                cycle = visit(dependency_id)
                if cycle is not None:
                    return cycle
            elif state[dependency_id] == 1:
                start = stack.index(dependency_id)
                return (*stack[start:], dependency_id)
        stack.pop()
        state[axis_id] = 2
        return None

    for axis in axes:
        if state.get(axis.id, 0) == 0:
            cycle = visit(axis.id)
            if cycle is not None:
                return cycle
    return None
