"""Route-local read-only handoff package projections."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any

from scopecat.handoff.tables import HandoffPlotSeries, HandoffTable


@dataclass(frozen=True)
class HandoffMeasurement:
    """Route-local projection of one opened handoff package measurement."""

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

    @property
    def primary_table(self) -> HandoffTable:
        table = self._measurement["primary_table"]
        return HandoffTable.from_records(table["columns"], table["rows"])

    @property
    def preview_table(self) -> HandoffTable:
        declared_columns = [
            column["name"] for column in self._measurement["declared_preview"]["declared_columns"]
        ]
        return HandoffTable.from_records(
            declared_columns,
            self._measurement["preview_data"]["preview_rows"],
        )

    @property
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
        for series in self.plot_series:
            if series.x_name == x and series.y_name == y:
                return series
        raise KeyError(f"{x}:{y}")


@dataclass(frozen=True)
class HandoffPackage:
    """Read-only route projection for a Scopecat-authored handoff package."""

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
    def measurements(self) -> tuple[HandoffMeasurement, ...]:
        return tuple(
            HandoffMeasurement(measurement, self._summary)
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

    def measurement(self, measurement_record_id: str) -> HandoffMeasurement:
        for measurement in self.measurements:
            if measurement.measurement_record_id == measurement_record_id:
                return measurement
        raise KeyError(measurement_record_id)

    def as_open_summary(self) -> dict[str, Any]:
        return copy.deepcopy(self._summary)
