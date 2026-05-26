"""Thin SDK-style view model for read-only handoff package use.

This candidate sits above the existing read view. It tests package/measurement
lookup, pandas/numpy-friendly adapters, and plot-spec metadata without
committing to final SDK names or adding hard dataframe dependencies.
"""

from __future__ import annotations

import copy
import importlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from implementation_candidates.handoff_package_read_view import (
    HandoffPackageReadView,
    HandoffPlotSeries,
    HandoffTable,
    MeasurementReadView,
    open_handoff_package_view,
)

_EXPECTED_POLICY = {
    "sdk_view_authority": "read_only_handoff_package_read_view",
    "package_open": "delegated_to_handoff_package_read_view",
    "measurement_lookup": "record_id_or_position_index",
    "table_access": "string_key_or_position_index",
    "dataframe_adapter": "optional_pandas",
    "array_adapter": "optional_numpy",
    "primary_plot": "first_declared_plot_candidate",
    "saved_plot_views": "declared_plot_candidates",
    "plot_rendering": "not_performed",
    "fit_execution": "not_performed",
    "analysis_writeback": "not_performed",
    "package_acceptance": "not_performed",
    "storage_import": "not_performed",
    "schema_inference": "not_performed",
    "scan_shape_inference": "not_performed",
    "gui_component_model": "not_defined",
    "stable_public_api": "not_defined",
}


def _dependency(name: str, provided: Any | None) -> Any:
    if provided is not None:
        return provided
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        raise RuntimeError(f"{name} is required for this adapter") from exc


def _position_index(size: int, key: int, *, kind: str) -> int:
    if key < 0 or key >= size:
        raise IndexError(f"{kind} position out of range")
    return key


def _column_key(columns: tuple[str, ...], key: str | int) -> str:
    if isinstance(key, int) and not isinstance(key, bool):
        return columns[_position_index(len(columns), key, kind="column")]
    if isinstance(key, str):
        if key not in columns:
            raise KeyError(key)
        return key
    raise TypeError("column key must be a string name or integer position")


@dataclass(frozen=True)
class SdkColumn:
    """Column metadata for Python and GUI-facing table/plot use."""

    name: str
    label: str
    role: str
    unit: str | None
    position: int

    @classmethod
    def from_declared(cls, column: dict[str, Any], *, position: int) -> SdkColumn:
        return cls(
            name=column["name"],
            label=column["label"],
            role=column["role"],
            unit=column.get("unit"),
            position=position,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "role": self.role,
            "unit": self.unit,
            "position": self.position,
        }


@dataclass(frozen=True)
class SdkTable:
    """Notebook-friendly table wrapper with optional pandas conversion."""

    _table: HandoffTable
    _columns: tuple[SdkColumn, ...]
    source: str
    role: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "_columns", tuple(self._columns))
        if tuple(column.name for column in self._columns) != self._table.columns:
            raise ValueError("SDK table column metadata must match table columns")

    @classmethod
    def from_handoff_table(
        cls,
        table: HandoffTable,
        *,
        declared_columns: tuple[SdkColumn, ...],
        source: str,
        role: str,
    ) -> SdkTable:
        declared_by_name = {column.name: column for column in declared_columns}
        columns = []
        for position, name in enumerate(table.columns):
            if name in declared_by_name:
                declared = declared_by_name[name]
                columns.append(
                    SdkColumn(
                        name=declared.name,
                        label=declared.label,
                        role=declared.role,
                        unit=declared.unit,
                        position=position,
                    )
                )
                continue
            columns.append(
                SdkColumn(
                    name=name,
                    label=name,
                    role="undeclared",
                    unit=None,
                    position=position,
                )
            )
        return cls(
            _table=table,
            _columns=tuple(columns),
            source=source,
            role=role,
        )

    @property
    def columns(self) -> tuple[SdkColumn, ...]:
        return tuple(self._columns)

    @property
    def column_names(self) -> tuple[str, ...]:
        return self._table.columns

    @property
    def row_count(self) -> int:
        return self._table.row_count

    @property
    def rows(self) -> tuple[dict[str, str], ...]:
        return self._table.rows

    def column(self, key: str | int) -> tuple[str, ...]:
        return self._table.column(_column_key(self.column_names, key))

    def row(self, index: int) -> dict[str, str]:
        return self._table.row(index)

    def to_records(self) -> list[dict[str, str]]:
        return self._table.to_records()

    def to_pandas(self, *, pandas_module: Any | None = None) -> Any:
        pandas = _dependency("pandas", pandas_module)
        frame = pandas.DataFrame.from_records(
            self.to_records(),
            columns=list(self.column_names),
        )
        if hasattr(frame, "attrs"):
            frame.attrs["scopecat"] = {
                "source": self.source,
                "role": self.role,
                "columns": [column.as_dict() for column in self.columns],
                "schema_inference": "not_performed",
            }
        return frame

    def __getitem__(self, key: str | int) -> tuple[str, ...]:
        return self.column(key)

    def __iter__(self) -> Iterator[dict[str, str]]:
        return iter(self.rows)

    def __len__(self) -> int:
        return self.row_count


@dataclass(frozen=True)
class SdkPlotSpec:
    """Declared plot view over table columns, suitable for notebooks and GUI use."""

    plot_id: str
    label: str
    kind: str
    source: str
    columns: tuple[SdkColumn, ...]
    _records: tuple[tuple[str, ...], ...]
    is_primary: bool
    position: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "columns", tuple(self.columns))
        object.__setattr__(self, "_records", tuple(tuple(record) for record in self._records))
        if self.kind not in {"xy", "iq_scatter", "heatmap"}:
            raise ValueError("SDK plot kind is unsupported")
        if self.kind == "heatmap" and len(self.columns) != 3:
            raise ValueError("SDK heatmap plot requires x, y, and z columns")
        if self.kind != "heatmap" and len(self.columns) != 2:
            raise ValueError("SDK non-heatmap plot requires x and y columns")
        for record in self._records:
            if len(record) != len(self.columns):
                raise ValueError("SDK plot records must match plot columns")
            if any(not isinstance(value, str) for value in record):
                raise ValueError("SDK plot values must be strings")

    @classmethod
    def from_series(
        cls,
        *,
        measurement_record_id: str,
        measurement_label: str,
        position: int,
        series: HandoffPlotSeries,
        columns_by_name: dict[str, SdkColumn],
    ) -> SdkPlotSpec:
        x_column = columns_by_name[series.x_name]
        y_column = columns_by_name[series.y_name]
        return cls(
            plot_id=f"{measurement_record_id}-plot-{position}",
            label=measurement_label
            if position == 0
            else f"{measurement_label} view {position + 1}",
            kind=_plot_kind(x_column, y_column),
            source=series.source,
            columns=(x_column, y_column),
            _records=tuple((point["x"], point["y"]) for point in series.points),
            is_primary=position == 0,
            position=position,
        )

    @classmethod
    def from_long_table(
        cls,
        *,
        plot_id: str,
        label: str,
        source: str,
        table: SdkTable,
        x: str,
        y: str,
        z: str,
        is_primary: bool,
        position: int,
    ) -> SdkPlotSpec:
        columns_by_name = {column.name: column for column in table.columns}
        plot_columns = (
            columns_by_name[x],
            columns_by_name[y],
            columns_by_name[z],
        )
        records = tuple((row[x], row[y], row[z]) for row in table.rows)
        return cls(
            plot_id=plot_id,
            label=label,
            kind="heatmap",
            source=source,
            columns=plot_columns,
            _records=records,
            is_primary=is_primary,
            position=position,
        )

    @property
    def x_column(self) -> SdkColumn:
        return self.columns[0]

    @property
    def y_column(self) -> SdkColumn:
        return self.columns[1]

    @property
    def z_column(self) -> SdkColumn | None:
        if len(self.columns) == 3:
            return self.columns[2]
        return None

    @property
    def points(self) -> tuple[dict[str, str], ...]:
        column_names = tuple(column.name for column in self.columns)
        return tuple(dict(zip(column_names, record, strict=True)) for record in self._records)

    def to_records(self) -> list[dict[str, str]]:
        return list(self.points)

    def to_pandas(self, *, pandas_module: Any | None = None) -> Any:
        pandas = _dependency("pandas", pandas_module)
        frame = pandas.DataFrame.from_records(
            self.to_records(),
            columns=[column.name for column in self.columns],
        )
        if hasattr(frame, "attrs"):
            frame.attrs["scopecat"] = self.as_dict()
        return frame

    def to_numpy(self, *, numpy_module: Any | None = None) -> tuple[Any, ...]:
        numpy = _dependency("numpy", numpy_module)
        return tuple(
            numpy.asarray(tuple(record[position] for record in self._records))
            for position, _column in enumerate(self.columns)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "plot_id": self.plot_id,
            "label": self.label,
            "kind": self.kind,
            "source": self.source,
            "is_primary": self.is_primary,
            "position": self.position,
            "x_column": self.x_column.as_dict(),
            "y_column": self.y_column.as_dict(),
            "z_column": self.z_column.as_dict() if self.z_column is not None else None,
            "rendering": "not_performed",
            "fit_execution": "not_performed",
        }


def _plot_kind(x_column: SdkColumn, y_column: SdkColumn) -> str:
    roles = {x_column.role, y_column.role}
    if {"iq_i", "iq_q"}.issubset(roles) or {"i_quadrature", "q_quadrature"}.issubset(roles):
        return "iq_scatter"
    return "xy"


@dataclass(frozen=True)
class SdkPlotCollection:
    """Collection of declared saved plot views for one measurement."""

    _plots: tuple[SdkPlotSpec, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_plots", tuple(self._plots))

    @property
    def available(self) -> tuple[str, ...]:
        return tuple(plot.plot_id for plot in self._plots)

    @property
    def primary(self) -> SdkPlotSpec:
        if not self._plots:
            raise KeyError("primary")
        for plot in self._plots:
            if plot.is_primary:
                return plot
        return self._plots[0]

    def __getitem__(self, key: str | int) -> SdkPlotSpec:
        if isinstance(key, int) and not isinstance(key, bool):
            return self._plots[_position_index(len(self._plots), key, kind="plot")]
        if isinstance(key, str):
            for plot in self._plots:
                if plot.plot_id == key:
                    return plot
            raise KeyError(key)
        raise TypeError("plot key must be a plot id or integer position")

    def __iter__(self) -> Iterator[SdkPlotSpec]:
        return iter(self._plots)

    def __len__(self) -> int:
        return len(self._plots)


@dataclass(frozen=True)
class SdkMeasurement:
    """SDK-style measurement object for notebook and GUI discovery."""

    _measurement: MeasurementReadView

    @property
    def measurement_record_id(self) -> str:
        return self._measurement.measurement_record_id

    @property
    def label(self) -> str:
        return self._measurement.label

    @property
    def experiment_type(self) -> str:
        return self._measurement.experiment_type

    @property
    def target(self) -> str:
        return self._measurement.target

    @property
    def columns(self) -> tuple[SdkColumn, ...]:
        return tuple(
            SdkColumn.from_declared(column, position=position)
            for position, column in enumerate(self._measurement.declared_preview_columns)
        )

    @property
    def primary(self) -> SdkTable:
        return SdkTable.from_handoff_table(
            self._measurement.primary_table(),
            declared_columns=self.columns,
            source=self._measurement.primary_package_path,
            role="primary",
        )

    @property
    def preview(self) -> SdkTable:
        return SdkTable.from_handoff_table(
            self._measurement.preview_table(),
            declared_columns=self.columns,
            source=self._measurement.primary_package_path,
            role="preview",
        )

    @property
    def plots(self) -> SdkPlotCollection:
        columns_by_name = {column.name: column for column in self.columns}
        return SdkPlotCollection(
            tuple(
                SdkPlotSpec.from_series(
                    measurement_record_id=self.measurement_record_id,
                    measurement_label=self.label,
                    position=position,
                    series=series,
                    columns_by_name=columns_by_name,
                )
                for position, series in enumerate(self._measurement.plot_series())
            )
        )

    @property
    def linked_context(self) -> tuple[dict[str, Any], ...]:
        return self._measurement.linked_context

    @property
    def findings(self) -> tuple[dict[str, Any], ...]:
        return self._measurement.findings

    @property
    def analysis_results(self) -> tuple[Any, ...]:
        return ()

    @property
    def fits(self) -> tuple[Any, ...]:
        return ()


@dataclass(frozen=True)
class SdkMeasurementCollection:
    """Record-id and position-index access to measurements."""

    _measurements: tuple[SdkMeasurement, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_measurements", tuple(self._measurements))

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(measurement.measurement_record_id for measurement in self._measurements)

    def __getitem__(self, key: str | int) -> SdkMeasurement:
        if isinstance(key, int) and not isinstance(key, bool):
            return self._measurements[
                _position_index(len(self._measurements), key, kind="measurement")
            ]
        if isinstance(key, str):
            for measurement in self._measurements:
                if measurement.measurement_record_id == key:
                    return measurement
            raise KeyError(key)
        raise TypeError("measurement key must be a record id or integer position")

    def __iter__(self) -> Iterator[SdkMeasurement]:
        return iter(self._measurements)

    def __len__(self) -> int:
        return len(self._measurements)


@dataclass(frozen=True)
class HandoffPackageSdkView:
    """Thin package object for read-only SDK-style handoff package use."""

    _read_view: HandoffPackageReadView

    @property
    def package_id(self) -> str:
        return self._read_view.package_id

    @property
    def display_name(self) -> str:
        return self._read_view.display_name

    @property
    def preview_classification(self) -> str:
        return self._read_view.preview_classification

    @property
    def sdk_view_policy(self) -> dict[str, str]:
        return copy.deepcopy(_EXPECTED_POLICY)

    @property
    def measurements(self) -> SdkMeasurementCollection:
        return SdkMeasurementCollection(
            tuple(SdkMeasurement(measurement) for measurement in self._read_view.measurements)
        )

    @property
    def measurement_ids(self) -> tuple[str, ...]:
        return self.measurements.ids

    @property
    def linked_context(self) -> tuple[dict[str, Any], ...]:
        return self._read_view.linked_context

    @property
    def findings(self) -> tuple[dict[str, Any], ...]:
        return self._read_view.findings

    def measurement(self, key: str | int) -> SdkMeasurement:
        return self.measurements[key]

    def __getitem__(self, key: str | int) -> SdkMeasurement:
        return self.measurement(key)


def open_handoff_package_sdk_view(package_dir: Path) -> HandoffPackageSdkView:
    """Open a handoff package as a thin SDK-style read-only view."""

    return HandoffPackageSdkView(open_handoff_package_view(package_dir))
