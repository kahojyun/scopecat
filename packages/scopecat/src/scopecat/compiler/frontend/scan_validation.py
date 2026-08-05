"""Validate one complete point domain and its axis sources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.kernel.point_identity import PointDomainLayout
from scopecat.program.scans import (
    AroundScanSource,
    AxisSpec,
    PointDomainSpec,
    PointsSpec,
)
from scopecat.program.value_refs import (
    ValueRef,
    internal_value_ref_point_dependencies,
    internal_value_ref_requires_execution,
    internal_value_ref_scalar_input_ids,
)

type ScanPath = tuple[str | int, ...]


@dataclass(frozen=True, slots=True)
class PointDomainValidationIssue:
    code: str
    message: str
    path: ScanPath


class PointDomainValidationError(ValueError):
    def __init__(self, issues: Sequence[PointDomainValidationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("; ".join(issue.message for issue in self.issues))


@dataclass(frozen=True, slots=True)
class VerifiedPointDomain:
    """Validated axes plus their explicit composition semantics."""

    axes: tuple[AxisSpec, ...]
    layout: PointDomainLayout


def verify_point_domain(
    domain: PointDomainSpec,
    *,
    inputs: Mapping[str, object] | None = None,
) -> VerifiedPointDomain:
    """Validate one product-grid or point-cloud domain declaration."""

    if isinstance(domain, PointsSpec):
        indexed_axes = tuple(
            (axis, ("columns", index)) for index, axis in enumerate(domain.axes)
        )
        layout: PointDomainLayout = "point_cloud"
    else:
        indexed_axes = tuple(
            (axis, ("axes", index)) for index, axis in enumerate(domain.axes)
        )
        layout = "product_grid"
    axes = tuple(axis for axis, _path in indexed_axes)

    issues: list[PointDomainValidationIssue] = []
    bound_input_ids = frozenset((inputs or {}).keys())
    for axis, path in indexed_axes:
        source, source_path, context = _scan_source(axis)
        if source is None:
            continue
        if internal_value_ref_requires_execution(source):
            issues.append(
                PointDomainValidationIssue(
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
                PointDomainValidationIssue(
                    "axis_point_dependency_unsupported",
                    f"axis {axis.id!r} source depends on scanned point: "
                    f"{dependency_ids}",
                    (*path, *source_path),
                )
            )
        unbound_inputs = sorted(
            internal_value_ref_scalar_input_ids(source) - bound_input_ids
        )
        if unbound_inputs:
            issues.append(
                PointDomainValidationIssue(
                    "axis_source_input_unbound",
                    f"axis {axis.id!r} source uses unbound input: "
                    + ", ".join(unbound_inputs),
                    (*path, *source_path),
                )
            )

    if issues:
        raise PointDomainValidationError(issues)

    return VerifiedPointDomain(axes=axes, layout=layout)


def _scan_source(
    axis: AxisSpec,
) -> tuple[ValueRef | None, ScanPath, str]:
    if axis.overlay is not None:
        return axis.overlay, (), "parameter overlay key"
    source = axis.source
    if isinstance(source, AroundScanSource) and isinstance(source.center, ValueRef):
        return source.center, ("center",), "axis center"
    return None, (), "axis source"
