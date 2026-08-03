"""Validate the deliberately small scan source language."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.program.point_domain import PointDomainLayout
from scopecat.program.scans import (
    AroundScanSource,
    AxisSpec,
    PointRowsSpec,
    Scan,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
    internal_value_ref_scalar_input_ids,
)

type ScanPath = tuple[str | int, ...]


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
class VerifiedScanDomain:
    """Validated axes plus their explicit composition semantics."""

    axes: tuple[AxisSpec, ...]
    layout: PointDomainLayout


def verify_scans(
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object] | None = None,
) -> tuple[AxisSpec, ...]:
    """Validate targets and require every dynamic scan source to be closed."""

    return verify_scan_domain(scans, inputs=inputs).axes


def verify_scan_domain(
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object] | None = None,
) -> VerifiedScanDomain:
    """Validate one product-grid or point-cloud domain declaration."""

    point_rows = tuple(scan for scan in scans if isinstance(scan, PointRowsSpec))
    if point_rows and len(scans) != 1:
        raise ScanValidationError(
            (
                ScanValidationIssue(
                    "point_domain_layout_mixed",
                    "point rows define the complete domain and cannot be combined "
                    "with scan axes",
                    (),
                ),
            )
        )
    if point_rows:
        [selected_rows] = point_rows
        indexed_axes = tuple(
            (axis, ("columns", index)) for index, axis in enumerate(selected_rows.axes)
        )
        layout: PointDomainLayout = "point_cloud"
    else:
        indexed_axes = _index_scan_axes(scans)
        layout = "product_grid"
    axes = tuple(axis for axis, _path in indexed_axes)
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
    bound_input_ids = frozenset((inputs or {}).keys())
    for axis, path in indexed_axes:
        source, source_path, context = _scan_source(axis)
        if source is None:
            continue
        if internal_value_ref_requires_execution(source):
            issues.append(
                ScanValidationIssue(
                    "value_requires_execution",
                    f"{context} cannot depend on an external operation",
                    (*path, *source_path),
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
                    (*path, *source_path),
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
                    (*path, *source_path),
                )
            )

    if issues:
        raise ScanValidationError(issues)

    return VerifiedScanDomain(axes=axes, layout=layout)


def _index_scan_axes(
    scans: Sequence[Scan],
) -> tuple[tuple[AxisSpec, ScanPath], ...]:
    return tuple((cast("AxisSpec", scan), (index,)) for index, scan in enumerate(scans))


def _scan_source(
    axis: AxisSpec,
) -> tuple[ValueRef | None, ScanPath, str]:
    if axis.parameter_lookup is not None:
        return axis.parameter_lookup, (), "parameter scan key"
    source = axis.source
    if isinstance(source, AroundScanSource) and isinstance(source.center, ValueRef):
        return source.center, ("center",), "scan center"
    return None, (), "scan source"
