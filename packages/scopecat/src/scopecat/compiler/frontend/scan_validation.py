"""Validate the deliberately small scan source language."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import cast

from scopecat.authoring._scan_intents import (
    AroundScanSource,
    AxisSpec,
    Scan,
)
from scopecat.authoring._value_refs import (
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


def verify_scans(
    scans: Sequence[Scan],
    *,
    inputs: Mapping[str, object] | None = None,
) -> tuple[AxisSpec, ...]:
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

    return axes


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
