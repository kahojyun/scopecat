"""Validate the deliberately small scan source language."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from scopecat.authoring._scan_intents import (
    CartesianScanIntent,
    CenteredParameterScanIntent,
    CenteredPointScanIntent,
    ExplicitParameterScanIntent,
    Scan,
    ScanLeafIntent,
    iter_scan_leaves,
    scan_point_id,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
    internal_value_ref_scalar_input_ids,
)
from scopecat.kernel.value_type_compatibility import require_assignable
from scopecat.kernel.value_types import Scalar, ValueType
from scopecat.kernel.value_validation import ValueValidationError

type ScanPath = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class ScanAxis:
    """One uniquely provided axis in declaration order."""

    id: str
    value_type: Scalar
    path: ScanPath
    leaf: ScanLeafIntent = field(repr=False)


@dataclass(frozen=True, slots=True)
class ScanValidationIssue:
    code: str
    message: str
    path: ScanPath


class ScanValidationError(ValueError):
    def __init__(self, issues: Sequence[ScanValidationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


@dataclass(frozen=True, slots=True)
class VerifiedScans:
    """Flat Cartesian scan axes accepted by the compiler."""

    axes: tuple[ScanAxis, ...]


def verify_scans(
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object] | None = None,
    input_types: Mapping[str, ValueType] | None = None,
) -> VerifiedScans:
    """Validate targets and require every dynamic scan source to be closed."""

    axes = _index_scan_axes(scans)
    duplicate_ids = sorted(
        axis_id
        for axis_id, count in Counter(axis.id for axis in axes).items()
        if count > 1
    )
    if duplicate_ids:
        raise ScanValidationError(
            (
                ScanValidationIssue(
                    "scan_axis_duplicate",
                    "duplicate scan axis: " + ", ".join(duplicate_ids),
                    (),
                ),
            )
        )

    issues: list[ScanValidationIssue] = []
    expected_types = input_types or {}
    bound_input_ids = frozenset((inputs or {}).keys())
    for axis in axes:
        expected = expected_types.get(axis.id)
        if expected is not None:
            try:
                require_assignable(
                    axis.value_type,
                    expected,
                    path=("scans", axis.id),
                )
            except ValueValidationError as error:
                issues.append(
                    ScanValidationIssue(
                        "module_input_type_mismatch",
                        str(error),
                        axis.path,
                    )
                )

        source, source_path, context = _scan_source(axis.leaf)
        if source is None:
            continue
        if internal_value_ref_requires_execution(source):
            issues.append(
                ScanValidationIssue(
                    "value_requires_execution",
                    f"{context} cannot depend on an external operation",
                    (*axis.path, *source_path),
                )
            )
        dependencies = internal_value_ref_point_dependencies(source)
        if dependencies:
            dependency_ids = ", ".join(
                sorted(dependency.id for dependency in dependencies)
            )
            issues.append(
                ScanValidationIssue(
                    "scan_point_dependency_unsupported",
                    f"scan axis {axis.id!r} source depends on scanned point: "
                    f"{dependency_ids}",
                    (*axis.path, *source_path),
                )
            )
        unbound_inputs = sorted(
            internal_value_ref_scalar_input_ids(source) - bound_input_ids
        )
        if unbound_inputs:
            issues.append(
                ScanValidationIssue(
                    "scan_source_input_unbound",
                    f"scan axis {axis.id!r} source uses unbound input: "
                    + ", ".join(unbound_inputs),
                    (*axis.path, *source_path),
                )
            )

    if issues:
        raise ScanValidationError(issues)

    return VerifiedScans(axes=axes)


def _index_scan_axes(scans: Sequence[Scan]) -> tuple[ScanAxis, ...]:
    axes: list[ScanAxis] = []
    for root_index, scan in enumerate(scans):
        leaves = iter_scan_leaves(scan)
        for leaf_index, leaf in enumerate(leaves):
            path = (
                (root_index, "scans", leaf_index)
                if isinstance(scan, CartesianScanIntent)
                else (root_index,)
            )
            value_type = leaf.target.value_type
            if not isinstance(value_type, Scalar):
                msg = "scan target must carry a scalar value type"
                raise TypeError(msg)
            axes.append(
                ScanAxis(
                    id=scan_point_id(leaf),
                    value_type=value_type,
                    path=path,
                    leaf=leaf,
                )
            )
    return tuple(axes)


def _scan_source(
    scan: ScanLeafIntent,
) -> tuple[ValueRef | None, ScanPath, str]:
    if isinstance(scan, CenteredPointScanIntent) and isinstance(scan.center, ValueRef):
        return scan.center, ("center",), "scan center"
    if isinstance(scan, ExplicitParameterScanIntent | CenteredParameterScanIntent):
        return scan.lookup, (), "parameter scan key"
    return None, (), "scan source"
