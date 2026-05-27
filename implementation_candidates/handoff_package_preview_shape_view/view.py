"""Declared preview plot-shape view over read-only handoff packages.

This candidate consumes manifest-declared preview metadata after the package
has been opened by the existing read view. It normalizes preview affordances
and plot bindings for reader/GUI review without reading additional files,
inferring scan shape, rendering plots, or accepting package import.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterator

from implementation_candidates.handoff_package_read_view import (
    HandoffPackageReadView,
    MeasurementReadView,
    open_handoff_package_view,
)

_EXPECTED_POLICY = {
    "shape_authority": "manifest_declared_preview_metadata",
    "package_open": "delegated_to_handoff_package_read_view",
    "scan_shape_owner": "measurement_record_declared_semantics",
    "table_shape_owner": "primary_data_item_physical_table",
    "preview_shape_owner": "declared_reader_projection",
    "file_observation": "not_performed",
    "trace_opening": "not_performed",
    "schema_inference": "not_performed",
    "scan_shape_inference": "not_performed",
    "storage_mapping": "not_defined",
    "plot_rendering": "not_performed",
    "dataframe_api": "not_defined",
    "array_api": "not_defined",
    "package_acceptance": "not_performed",
}

_PREVIEW_AFFORDANCES = {
    "declared_1d_table": "xy_series",
    "2d_grid_table": "heatmap_grid",
    "ragged_adaptive_table": "ragged_line_family",
    "ragged_observed_only_table": "ragged_observed_line_family",
    "trace_per_point_table": "trace_family",
    "fixed_vector_response_table": "component_pair_scatter",
    "complex_fixed_vector_response_table": "complex_component_pair_scatter",
}

_PLOT_REQUIREMENTS = {
    "declared_1d_table": ("xy_series", ("x", "y")),
    "2d_grid_table": ("heatmap_grid", ("x", "y", "z")),
    "ragged_adaptive_table": ("ragged_line_family", ("x", "series", "y")),
    "ragged_observed_only_table": (
        "ragged_observed_line_family",
        ("x", "series", "y"),
    ),
    "trace_per_point_table": ("trace_family", ("x", "series", "y", "trace_ref_column")),
    "fixed_vector_response_table": (
        "component_pair_scatter",
        ("x_component", "y_component", "vector_column"),
    ),
    "complex_fixed_vector_response_table": (
        "complex_component_pair_scatter",
        ("x_component", "y_component", "vector_column"),
    ),
}

_AXIS_ROLES = {"sweep_axis", "axis", "independent_axis"}


def _as_tuple(value: Any) -> tuple[Any, ...]:
    return tuple(value) if isinstance(value, (list, tuple)) else ()


def _columns_by_name(declared_columns: tuple[dict[str, Any], ...]) -> dict[str, dict[str, Any]]:
    return {column["name"]: column for column in declared_columns if isinstance(column, dict)}


def _column_summary(column: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": column["name"],
        "label": column["label"],
        "role": column["role"],
        "unit": column.get("unit"),
    }


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType(
            {copy.deepcopy(key): _freeze_json(item) for key, item in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    return copy.deepcopy(value)


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {copy.deepcopy(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return copy.deepcopy(value)


def _binding_issue(binding: str, value: Any, expected: str) -> dict[str, Any]:
    return {"binding": binding, "value": value, "expected": expected}


def _validate_declared_column_bindings(
    *,
    bindings: dict[str, Any],
    binding_keys: tuple[str, ...],
    declared_column_names: set[str],
) -> list[dict[str, Any]]:
    return [
        _binding_issue(key, bindings.get(key), "declared_column_name")
        for key in binding_keys
        if bindings.get(key) not in declared_column_names
    ]


def _vector_column_by_name(data_shape: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        column["name"]: column
        for column in _as_tuple(data_shape.get("vector_columns"))
        if isinstance(column, dict) and isinstance(column.get("name"), str)
    }


def _validate_shape_bindings(
    *,
    shape_kind: str,
    bindings: dict[str, Any],
    data_shape: dict[str, Any],
    declared_column_names: set[str],
) -> list[dict[str, Any]]:
    if shape_kind in {
        "declared_1d_table",
        "2d_grid_table",
        "ragged_adaptive_table",
        "ragged_observed_only_table",
    }:
        return _validate_declared_column_bindings(
            bindings=bindings,
            binding_keys=tuple(bindings),
            declared_column_names=declared_column_names,
        )
    if shape_kind == "trace_per_point_table":
        trace_schema = data_shape.get("trace_schema", {})
        issues = _validate_declared_column_bindings(
            bindings=bindings,
            binding_keys=("series", "trace_ref_column"),
            declared_column_names=declared_column_names,
        )
        expected_trace_ref = data_shape.get("trace_ref_column")
        if bindings.get("trace_ref_column") != expected_trace_ref:
            issues.append(
                _binding_issue(
                    "trace_ref_column",
                    bindings.get("trace_ref_column"),
                    "data_shape.trace_ref_column",
                )
            )
        if bindings.get("x") != trace_schema.get("independent_column"):
            issues.append(
                _binding_issue(
                    "x",
                    bindings.get("x"),
                    "data_shape.trace_schema.independent_column",
                )
            )
        if bindings.get("y") != trace_schema.get("response_column"):
            issues.append(
                _binding_issue(
                    "y",
                    bindings.get("y"),
                    "data_shape.trace_schema.response_column",
                )
            )
        return issues
    if shape_kind in {
        "fixed_vector_response_table",
        "complex_fixed_vector_response_table",
    }:
        issues = _validate_declared_column_bindings(
            bindings=bindings,
            binding_keys=("vector_column",),
            declared_column_names=declared_column_names,
        )
        vector_columns = _vector_column_by_name(data_shape)
        vector_column = vector_columns.get(bindings.get("vector_column"))
        if vector_column is None:
            issues.append(
                _binding_issue(
                    "vector_column",
                    bindings.get("vector_column"),
                    "data_shape.vector_columns.name",
                )
            )
            return issues
        components = set(_as_tuple(vector_column.get("components")))
        for key in ("x_component", "y_component"):
            if bindings.get(key) not in components:
                issues.append(
                    _binding_issue(key, bindings.get(key), "data_shape.vector_columns.components")
                )
        return issues
    return []


@dataclass(frozen=True)
class DeclaredPreviewPlotCandidate:
    """Normalized declared preview plot binding."""

    plot_kind: str
    source: str
    bindings: Mapping[str, Any]
    title: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "bindings", _freeze_json(self.bindings))

    @classmethod
    def from_candidate(
        cls,
        *,
        shape_kind: str,
        candidate: dict[str, Any],
        data_shape: dict[str, Any],
        declared_column_names: set[str],
    ) -> tuple[DeclaredPreviewPlotCandidate | None, dict[str, Any] | None]:
        if shape_kind not in _PLOT_REQUIREMENTS:
            return None, None
        plot_kind, required = _PLOT_REQUIREMENTS.get(shape_kind, ("unsupported_plot", ()))
        declared_plot_kind = candidate.get("plot_kind")
        if declared_plot_kind is not None and declared_plot_kind != plot_kind:
            return None, {
                "finding": "declared_preview_plot_kind_mismatch",
                "severity": "review",
                "shape_kind": shape_kind,
                "declared_plot_kind": declared_plot_kind,
                "expected_plot_kind": plot_kind,
                "does_not_claim": "plot_candidate_usable",
            }
        missing = [key for key in required if key not in candidate]
        if missing:
            return None, {
                "finding": "declared_preview_plot_binding_incomplete",
                "severity": "review",
                "shape_kind": shape_kind,
                "missing_bindings": missing,
                "does_not_claim": "plot_candidate_usable",
            }
        bindings = {key: copy.deepcopy(candidate[key]) for key in required}
        invalid_bindings = _validate_shape_bindings(
            shape_kind=shape_kind,
            bindings=bindings,
            data_shape=data_shape,
            declared_column_names=declared_column_names,
        )
        if invalid_bindings:
            return None, {
                "finding": "declared_preview_plot_binding_invalid",
                "severity": "review",
                "shape_kind": shape_kind,
                "invalid_bindings": invalid_bindings,
                "does_not_claim": "plot_candidate_usable",
            }
        return (
            cls(
                plot_kind=plot_kind,
                source=candidate.get("source", ""),
                bindings=bindings,
                title=candidate.get("title"),
            ),
            None,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "plot_kind": self.plot_kind,
            "source": self.source,
            "bindings": _thaw_json(self.bindings),
            "title": self.title,
            "rendering": "not_performed",
        }


@dataclass(frozen=True)
class DeclaredPreviewShape:
    """Reader-facing preview projection derived from declared metadata."""

    kind: str
    preview_affordance: str
    axis_order: tuple[str, ...]
    axis_columns: tuple[Mapping[str, Any], ...]
    response_columns: tuple[Mapping[str, Any], ...]
    declared_metadata_snapshot: Mapping[str, Any]
    plot_candidates: tuple[DeclaredPreviewPlotCandidate, ...]
    findings: tuple[Mapping[str, Any], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "axis_columns",
            tuple(_freeze_json(column) for column in self.axis_columns),
        )
        object.__setattr__(
            self,
            "response_columns",
            tuple(_freeze_json(column) for column in self.response_columns),
        )
        object.__setattr__(
            self,
            "declared_metadata_snapshot",
            _freeze_json(self.declared_metadata_snapshot),
        )
        object.__setattr__(
            self,
            "findings",
            tuple(_freeze_json(finding) for finding in self.findings),
        )

    @classmethod
    def from_declared_preview(
        cls,
        *,
        data_shape: dict[str, Any],
        declared_columns: tuple[dict[str, Any], ...],
        plot_candidates: tuple[dict[str, Any], ...],
    ) -> DeclaredPreviewShape:
        kind = data_shape.get("kind", "unsupported")
        preview_affordance = _PREVIEW_AFFORDANCES.get(kind, "unsupported_preview_affordance")
        axis_order = tuple(str(axis) for axis in _as_tuple(data_shape.get("axis_order")))
        by_name = _columns_by_name(declared_columns)
        declared_column_names = set(by_name)
        axis_columns = tuple(
            _column_summary(by_name[name])
            for name in axis_order
            if name in by_name and by_name[name].get("role") in _AXIS_ROLES
        )
        response_columns = tuple(
            _column_summary(column)
            for column in declared_columns
            if column.get("role") not in _AXIS_ROLES
        )
        normalized_candidates = []
        findings = []
        if preview_affordance == "unsupported_preview_affordance":
            findings.append(
                {
                    "finding": "declared_preview_affordance_unsupported",
                    "severity": "review",
                    "shape_kind": kind,
                    "does_not_claim": "preview_affordance_supported",
                }
            )
        for candidate in plot_candidates:
            normalized, finding = DeclaredPreviewPlotCandidate.from_candidate(
                shape_kind=kind,
                candidate=candidate,
                data_shape=data_shape,
                declared_column_names=declared_column_names,
            )
            if normalized is not None:
                normalized_candidates.append(normalized)
            if finding is not None:
                findings.append(finding)
        return cls(
            kind=kind,
            preview_affordance=preview_affordance,
            axis_order=axis_order,
            axis_columns=axis_columns,
            response_columns=response_columns,
            declared_metadata_snapshot={
                "kind": kind,
                "axis_order": list(axis_order),
                "source": "manifest_declared_preview_metadata",
                "stability": "debug_snapshot_not_final_schema",
            },
            plot_candidates=tuple(normalized_candidates),
            findings=tuple(findings),
        )

    @property
    def status(self) -> str:
        if self.preview_affordance == "unsupported_preview_affordance":
            return "unsupported_preview_affordance"
        if self.findings:
            return "declared_preview_affordance_needs_review"
        return "declared_preview_affordance_ready"

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "preview_affordance": self.preview_affordance,
            "status": self.status,
            "axis_order": list(self.axis_order),
            "axis_columns": [_thaw_json(column) for column in self.axis_columns],
            "response_columns": [_thaw_json(column) for column in self.response_columns],
            "declared_metadata_snapshot": _thaw_json(self.declared_metadata_snapshot),
            "plot_candidates": [candidate.as_dict() for candidate in self.plot_candidates],
            "findings": [_thaw_json(finding) for finding in self.findings],
            "schema_inference": "not_performed",
            "scan_shape_inference": "not_performed",
            "file_observation": "not_performed",
        }


@dataclass(frozen=True)
class PreviewShapeMeasurement:
    """Declared preview projection for one opened measurement."""

    _measurement: MeasurementReadView

    @property
    def measurement_record_id(self) -> str:
        return self._measurement.measurement_record_id

    @property
    def label(self) -> str:
        return self._measurement.label

    @property
    def preview_shape(self) -> DeclaredPreviewShape:
        return DeclaredPreviewShape.from_declared_preview(
            data_shape=self._measurement.declared_preview_shape,
            declared_columns=self._measurement.declared_preview_columns,
            plot_candidates=self._measurement.declared_preview_plot_candidates,
        )

    @property
    def findings(self) -> tuple[Mapping[str, Any], ...]:
        return (*self._measurement.findings, *self.preview_shape.findings)

    def as_dict(self) -> dict[str, Any]:
        return {
            "measurement_record_id": self.measurement_record_id,
            "label": self.label,
            "preview_projection": self.preview_shape.as_dict(),
            "findings": [_thaw_json(finding) for finding in self.findings],
        }


@dataclass(frozen=True)
class HandoffPackagePreviewShapeView:
    """Package-level declared preview projection."""

    _read_view: HandoffPackageReadView

    @property
    def package_id(self) -> str:
        return self._read_view.package_id

    @property
    def preview_shape_policy(self) -> dict[str, str]:
        return copy.deepcopy(_EXPECTED_POLICY)

    @property
    def measurements(self) -> tuple[PreviewShapeMeasurement, ...]:
        return tuple(
            PreviewShapeMeasurement(measurement) for measurement in self._read_view.measurements
        )

    @property
    def measurement_ids(self) -> tuple[str, ...]:
        return tuple(measurement.measurement_record_id for measurement in self.measurements)

    def measurement(self, measurement_record_id: str) -> PreviewShapeMeasurement:
        for measurement in self.measurements:
            if measurement.measurement_record_id == measurement_record_id:
                return measurement
        raise KeyError(measurement_record_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "preview_shape_policy": self.preview_shape_policy,
            "measurement_ids": list(self.measurement_ids),
            "measurements": [measurement.as_dict() for measurement in self.measurements],
        }

    def __iter__(self) -> Iterator[PreviewShapeMeasurement]:
        return iter(self.measurements)


def open_handoff_package_preview_shape_view(package_dir: Path) -> HandoffPackagePreviewShapeView:
    """Open a handoff package and expose declared preview projection facts."""

    return HandoffPackagePreviewShapeView(open_handoff_package_view(package_dir))
