"""Validate the deliberately small scan source language."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.authoring._scan_intents import (
    AroundScanSource,
    AxisSpec,
    CartesianScan,
    Scan,
    iter_scan_axes,
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

    axes: tuple[AxisSpec, ...]


def verify_scans(
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object] | None = None,
    input_types: Mapping[str, ValueType] | None = None,
) -> VerifiedScans:
    """Validate targets and require every dynamic scan source to be closed."""

    indexed_axes = _index_scan_axes(scans)
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
    expected_types = input_types or {}
    bound_input_ids = frozenset((inputs or {}).keys())
    for axis, path in indexed_axes:
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
                        path,
                    )
                )

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

    return VerifiedScans(axes=axes)


def _index_scan_axes(
    scans: Sequence[Scan],
) -> tuple[tuple[AxisSpec, ScanPath], ...]:
    axes: list[tuple[AxisSpec, ScanPath]] = []
    for root_index, scan in enumerate(scans):
        children = iter_scan_axes(scan)
        for axis_index, axis in enumerate(children):
            path = (
                (root_index, "scans", axis_index)
                if isinstance(scan, CartesianScan)
                else (root_index,)
            )
            if not isinstance(axis.target.value_type, Scalar):
                msg = "scan target must carry a scalar value type"
                raise TypeError(msg)
            axes.append((axis, path))
    return tuple(axes)


def _scan_source(
    axis: AxisSpec,
) -> tuple[ValueRef | None, ScanPath, str]:
    if axis.overlay is not None:
        return axis.overlay.lookup, (), "parameter scan key"
    source = axis.source
    if isinstance(source, AroundScanSource) and isinstance(source.center, ValueRef):
        return source.center, ("center",), "scan center"
    return None, (), "scan source"
