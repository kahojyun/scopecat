"""Reader-facing view objects for read-only handoff package use.

This candidate keeps package validation and file opening in the existing
handoff package opener. The objects here test whether the opened summary can be
consumed through natural reader actions without committing to a final SDK.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from implementation_candidates.handoff_package_opener import open_handoff_package


def _freeze_records(
    rows: list[dict[str, str]],
    columns: tuple[str, ...],
) -> tuple[tuple[str, ...], ...]:
    if not columns:
        raise ValueError("handoff table requires at least one column")
    if any(column == "" for column in columns):
        raise ValueError("handoff table requires non-empty columns")
    if len(set(columns)) != len(columns):
        raise ValueError("handoff table requires unique columns")
    expected = set(columns)
    frozen_rows = []
    for row in rows:
        if set(row) != expected:
            raise ValueError("handoff table rows must match columns")
        if any(not isinstance(row[column], str) for column in columns):
            raise ValueError("handoff table row values must be strings")
        frozen_rows.append(tuple(row[column] for column in columns))
    return tuple(frozen_rows)


@dataclass(frozen=True)
class HandoffTable:
    """Small table-like object for string CSV rows without dataframe semantics."""

    columns: tuple[str, ...]
    _rows: tuple[tuple[str, ...], ...]

    def __post_init__(self) -> None:
        if not self.columns:
            raise ValueError("handoff table requires at least one column")
        if any(not isinstance(column, str) or column == "" for column in self.columns):
            raise ValueError("handoff table requires non-empty string columns")
        if len(set(self.columns)) != len(self.columns):
            raise ValueError("handoff table requires unique columns")
        for row in self._rows:
            if len(row) != len(self.columns):
                raise ValueError("handoff table rows must match columns")
            if any(not isinstance(value, str) for value in row):
                raise ValueError("handoff table row values must be strings")

    @classmethod
    def from_records(cls, columns: list[str], rows: list[dict[str, str]]) -> HandoffTable:
        frozen_columns = tuple(columns)
        return cls(columns=frozen_columns, _rows=_freeze_records(rows, frozen_columns))

    @property
    def row_count(self) -> int:
        return len(self._rows)

    @property
    def rows(self) -> tuple[dict[str, str], ...]:
        return tuple(dict(zip(self.columns, row, strict=True)) for row in self._rows)

    def row(self, index: int) -> dict[str, str]:
        return dict(zip(self.columns, self._rows[index], strict=True))

    def column(self, name: str) -> tuple[str, ...]:
        try:
            index = self.columns.index(name)
        except ValueError as exc:
            raise KeyError(name) from exc
        return tuple(row[index] for row in self._rows)

    def to_records(self) -> list[dict[str, str]]:
        return list(self.rows)

    def __iter__(self) -> Iterator[dict[str, str]]:
        return iter(self.rows)

    def __len__(self) -> int:
        return self.row_count


@dataclass(frozen=True)
class HandoffPlotSeries:
    """Declared plot series as string-valued points."""

    source: str
    x_name: str
    y_name: str
    _points: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if not isinstance(self.source, str) or not self.source:
            raise ValueError("handoff plot series requires a source")
        if not isinstance(self.x_name, str) or not self.x_name:
            raise ValueError("handoff plot series requires an x column")
        if not isinstance(self.y_name, str) or not self.y_name:
            raise ValueError("handoff plot series requires a y column")
        for point in self._points:
            if len(point) != 2:
                raise ValueError("handoff plot series points must have x and y")
            if not isinstance(point[0], str) or not isinstance(point[1], str):
                raise ValueError("handoff plot series point values must be strings")

    @classmethod
    def from_points(
        cls,
        *,
        source: str,
        x_name: str,
        y_name: str,
        points: list[dict[str, str]],
    ) -> HandoffPlotSeries:
        frozen_points = []
        for point in points:
            if set(point) != {"x", "y"}:
                raise ValueError("handoff plot series points must have x and y")
            if not isinstance(point["x"], str) or not isinstance(point["y"], str):
                raise ValueError("handoff plot series point values must be strings")
            frozen_points.append((point["x"], point["y"]))
        return cls(
            source=source,
            x_name=x_name,
            y_name=y_name,
            _points=tuple(frozen_points),
        )

    @property
    def points(self) -> tuple[dict[str, str], ...]:
        return tuple({"x": x, "y": y} for x, y in self._points)

    @property
    def x(self) -> tuple[str, ...]:
        return tuple(point[0] for point in self._points)

    @property
    def y(self) -> tuple[str, ...]:
        return tuple(point[1] for point in self._points)

    def to_records(self) -> list[dict[str, str]]:
        return list(self.points)


@dataclass(frozen=True)
class MeasurementReadView:
    """Reader-facing view of one opened package measurement."""

    _measurement: dict[str, Any]
    _package_summary: dict[str, Any]

    @property
    def measurement_record_id(self) -> str:
        return self._measurement["measurement_record_id"]

    @property
    def label(self) -> str:
        return self._measurement["label"]

    @property
    def experiment_type(self) -> str:
        return self._measurement["experiment_type"]

    @property
    def target(self) -> str:
        return self._measurement["target"]

    @property
    def primary_package_path(self) -> str:
        return self._measurement["primary_data"]["package_path"]

    @property
    def declared_preview_columns(self) -> tuple[dict[str, str], ...]:
        return tuple(
            copy.deepcopy(column)
            for column in self._measurement["declared_preview"]["declared_columns"]
        )

    @property
    def declared_preview_shape(self) -> dict[str, Any]:
        return copy.deepcopy(self._measurement["declared_preview"]["data_shape"])

    @property
    def declared_preview_plot_candidates(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            copy.deepcopy(candidate)
            for candidate in self._measurement["declared_preview"]["plot_candidates"]
        )

    @property
    def integrity_check(self) -> str:
        return self._measurement["primary_data"]["integrity_check"]

    @property
    def findings(self) -> tuple[dict[str, Any], ...]:
        linked_context_ids = {
            item["link_id"]
            for item in self._package_summary["linked_context"]
            if self.measurement_record_id in item["linked_measurement_record_ids"]
        }
        findings = []
        seen = set()
        for finding in self._package_summary["manifest_preview_findings"]:
            is_direct = finding.get("measurement_record_id") == self.measurement_record_id
            is_linked_context = (
                finding.get("subject_type") == "linked_context"
                and finding.get("subject_id") in linked_context_ids
            )
            if not is_direct and not is_linked_context:
                continue
            key = (
                finding.get("finding"),
                finding.get("subject_type"),
                finding.get("subject_id"),
                finding.get("measurement_record_id"),
            )
            if key in seen:
                continue
            seen.add(key)
            findings.append(copy.deepcopy(finding))
        return tuple(findings)

    @property
    def linked_context(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            copy.deepcopy(item)
            for item in self._package_summary["linked_context"]
            if self.measurement_record_id in item["linked_measurement_record_ids"]
        )

    def primary_table(self) -> HandoffTable:
        table = self._measurement["primary_table"]
        return HandoffTable.from_records(table["columns"], table["rows"])

    def preview_table(self) -> HandoffTable:
        declared_columns = [
            column["name"] for column in self._measurement["declared_preview"]["declared_columns"]
        ]
        return HandoffTable.from_records(
            declared_columns,
            self._measurement["preview_data"]["preview_rows"],
        )

    def plot_series(self) -> tuple[HandoffPlotSeries, ...]:
        return tuple(
            HandoffPlotSeries.from_points(
                source=series["source"],
                x_name=series["x"],
                y_name=series["y"],
                points=series["points"],
            )
            for series in self._measurement["preview_data"]["plot_series"]
        )

    def plot_series_by_columns(self, *, x: str, y: str) -> HandoffPlotSeries:
        for series in self.plot_series():
            if series.x_name == x and series.y_name == y:
                return series
        raise KeyError(f"{x}:{y}")


@dataclass(frozen=True)
class HandoffPackageReadView:
    """Reader-facing view of a read-only opened handoff package."""

    _summary: dict[str, Any]

    @property
    def package_id(self) -> str:
        return self._summary["package"]["package_id"]

    @property
    def display_name(self) -> str:
        return self._summary["package"]["display_name"]

    @property
    def preview_classification(self) -> str:
        return self._summary["package"]["preview_classification"]

    @property
    def measurement_ids(self) -> tuple[str, ...]:
        return tuple(
            measurement["measurement_record_id"]
            for measurement in self._summary["selected_measurements"]
        )

    @property
    def measurements(self) -> tuple[MeasurementReadView, ...]:
        return tuple(
            MeasurementReadView(measurement, self._summary)
            for measurement in self._summary["selected_measurements"]
        )

    @property
    def linked_context(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["linked_context"])

    @property
    def findings(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["manifest_preview_findings"])

    @property
    def attention(self) -> tuple[dict[str, Any], ...]:
        return tuple(copy.deepcopy(item) for item in self._summary["attention"])

    def measurement(self, measurement_record_id: str) -> MeasurementReadView:
        for measurement in self.measurements:
            if measurement.measurement_record_id == measurement_record_id:
                return measurement
        raise KeyError(measurement_record_id)

    def as_open_summary(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)


def open_handoff_package_view(package_dir: Path) -> HandoffPackageReadView:
    """Open a package through the validated opener and return reader objects."""

    return HandoffPackageReadView(open_handoff_package(package_dir))
