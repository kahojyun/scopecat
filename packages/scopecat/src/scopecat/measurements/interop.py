# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false
"""Adapter-neutral measurement projections and ecosystem exports."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from importlib import import_module
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast

import numpy as np
import pyarrow as pa
import xarray as xr

from scopecat.kernel.frozen import thaw_json_value
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.arrow_values import measurement_values_to_arrow_array
from scopecat.program.measurement_types import MeasurementDType, MeasurementVariableRole
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDatasetSchema,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementValue,
)

if TYPE_CHECKING:
    import pandas as pd

type ProjectionDiagnostics = Literal["none", "reason", "full"]


class _PolarsModule(Protocol):
    def from_arrow(self, data: pa.Table) -> object: ...


class _ProjectionVariable(Protocol):
    @property
    def id(self) -> str: ...

    @property
    def dtype(self) -> MeasurementDType: ...

    @property
    def unit(self) -> str | None: ...

    @property
    def dims(self) -> tuple[str, ...]: ...

    @property
    def shape(self) -> tuple[int | None, ...]: ...

    @property
    def role(self) -> MeasurementVariableRole: ...

    @property
    def recording_group_id(self) -> str | None: ...

    @property
    def label(self) -> str | None: ...

    @property
    def raw_values(self) -> tuple[MeasurementValue, ...]: ...


class _ProjectionDataset(Protocol):
    @property
    def schema(self) -> MeasurementDatasetSchema: ...

    @property
    def metadata(self) -> Mapping[str, object]: ...

    @property
    def point_indices(self) -> tuple[int, ...]: ...

    @property
    def logical_point_ids(self) -> tuple[str | None, ...]: ...

    def __getitem__(self, variable_id: str) -> _ProjectionVariable: ...

    def to_xarray(self) -> xr.Dataset: ...


@dataclass(frozen=True, slots=True)
class ProjectionField:
    """One stable external column bound to a durable measurement variable."""

    name: str
    variable_id: str
    dtype: MeasurementDType
    unit: str | None
    dims: tuple[str, ...]
    role: MeasurementVariableRole
    source_path: tuple[str, ...] | None = None
    recording_group_id: str | None = None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectionSchema:
    """Runtime semantic schema retained when data enters an ecosystem library."""

    dataset_id: str
    fields: tuple[ProjectionField, ...]
    diagnostics: ProjectionDiagnostics = "none"
    include_identity: bool = True


@dataclass(frozen=True, slots=True)
class MeasurementDataProjection:
    """A semantic selection that exports native Arrow, Xarray, and frames."""

    dataset: _ProjectionDataset
    schema: ProjectionSchema

    def with_units(self, **units: str) -> Self:
        """Return a projection with explicit output units for named fields."""

        unknown = set(units) - {field.name for field in self.schema.fields}
        if unknown:
            raise KeyError("projection has no fields: " + ", ".join(sorted(unknown)))
        selected: list[ProjectionField] = []
        for field in self.schema.fields:
            target = units.get(field.name)
            if target is None or target == field.unit:
                selected.append(field)
                continue
            if field.unit is None:
                raise TypeError(f"projection field {field.name!r} is not unit-bearing")
            Quantity(1.0, field.unit).to(target)
            dtype: MeasurementDType = (
                "float64" if field.dtype == "int64" else field.dtype
            )
            selected.append(replace(field, dtype=dtype, unit=target))
        return replace(self, schema=replace(self.schema, fields=tuple(selected)))

    def with_diagnostics(self, diagnostics: ProjectionDiagnostics) -> Self:
        """Choose a stable unavailable-value representation for every field."""

        if diagnostics not in {"none", "reason", "full"}:
            raise ValueError("projection diagnostics must be none, reason, or full")
        _validate_external_names(
            self.schema.fields,
            diagnostics=diagnostics,
            include_identity=self.schema.include_identity,
        )
        return replace(self, schema=replace(self.schema, diagnostics=diagnostics))

    def with_identity(self, include: bool = True) -> Self:
        """Choose whether tabular exports include durable point identity columns."""

        _validate_external_names(
            self.schema.fields,
            diagnostics=self.schema.diagnostics,
            include_identity=include,
        )
        return replace(self, schema=replace(self.schema, include_identity=include))

    def to_arrow(self) -> pa.Table:
        """Materialize the canonical point-row Arrow representation."""

        arrays: list[pa.Array] = []
        arrow_fields: list[pa.Field] = []
        if self.schema.include_identity:
            arrays.extend(
                (
                    pa.array(self.dataset.point_indices, type=pa.int64()),
                    pa.array(self.dataset.logical_point_ids, type=pa.string()),
                )
            )
            arrow_fields.extend(
                (
                    pa.field(
                        "point_index",
                        pa.int64(),
                        nullable=False,
                        metadata={b"scopecat.role": b"point_identity"},
                    ),
                    pa.field(
                        "logical_point_id",
                        pa.string(),
                        metadata={b"scopecat.role": b"logical_point_identity"},
                    ),
                )
            )
        for field in self.schema.fields:
            variable = self.dataset[field.variable_id]
            values = _projected_values(variable, field)
            array = measurement_values_to_arrow_array(
                values,
                dtype=field.dtype,
                shape=variable.shape[1:],
            )
            arrays.append(array)
            arrow_fields.append(
                pa.field(
                    field.name,
                    array.type,
                    metadata=_field_metadata(field),
                )
            )
            if self.schema.diagnostics != "none":
                reasons, metadata = _unavailable_columns(variable.raw_values)
                arrays.append(pa.array(reasons, type=pa.string()))
                arrow_fields.append(
                    pa.field(
                        f"{field.name}__unavailable_reason",
                        pa.string(),
                        metadata={
                            b"scopecat.role": b"availability",
                            b"scopecat.source": field.name.encode(),
                        },
                    )
                )
                if self.schema.diagnostics == "full":
                    arrays.append(pa.array(metadata, type=pa.large_string()))
                    arrow_fields.append(
                        pa.field(
                            f"{field.name}__unavailable_metadata",
                            pa.large_string(),
                            metadata={
                                b"scopecat.role": b"availability_metadata",
                                b"scopecat.source": field.name.encode(),
                            },
                        )
                    )
        schema = pa.schema(
            arrow_fields,
            metadata={
                b"scopecat.dataset_id": self.schema.dataset_id.encode(),
                b"scopecat.projection": _stable_json(asdict(self.schema)).encode(),
                b"scopecat.schema": self.dataset.schema.model_dump_json().encode(),
                b"scopecat.metadata": _stable_json(self.dataset.metadata).encode(),
            },
        )
        return pa.Table.from_arrays(arrays, schema=schema)

    def to_record_batch_reader(
        self, *, max_chunksize: int = 1024
    ) -> pa.RecordBatchReader:
        """Expose this materialized projection as bounded Arrow record batches."""

        if max_chunksize <= 0:
            raise ValueError("record batch max_chunksize must be positive")
        table = self.to_arrow()
        return pa.RecordBatchReader.from_batches(
            table.schema,
            table.to_batches(max_chunksize=max_chunksize),
        )

    def to_xarray(self) -> xr.Dataset:
        """Project aliases and units while preserving Xarray dimension semantics."""

        source = self.dataset.to_xarray()
        point = source.coords["point"]
        coords: dict[str, object] = {
            "point": (point.dims, point.values.copy(), dict(point.attrs))
        }
        if self.schema.include_identity and "logical_point_id" in source.coords:
            logical_point_id = source.coords["logical_point_id"]
            coords["logical_point_id"] = (
                logical_point_id.dims,
                logical_point_id.values.copy(),
                dict(logical_point_id.attrs),
            )
        data_vars: dict[str, object] = {}
        for field in self.schema.fields:
            variable = self.dataset[field.variable_id]
            array = source[field.variable_id].copy(deep=True)
            if field.unit != variable.unit:
                if variable.unit is None or field.unit is None:
                    raise AssertionError("projection unit conversion lost its source")
                scale = Quantity(1.0, variable.unit).to(field.unit).value
                array = array * scale
            attrs = dict(array.attrs)
            if field.unit is None:
                attrs.pop("units", None)
            else:
                attrs["units"] = field.unit
            attrs["scopecat_source_variable"] = field.variable_id
            target = coords if field.role == "coordinate" else data_vars
            target[field.name] = (array.dims, array.values, attrs)
            if self.schema.diagnostics != "none":
                reasons, metadata = _unavailable_columns(variable.raw_values)
                data_vars[f"{field.name}__unavailable_reason"] = (
                    ("point",),
                    np.asarray(reasons, dtype=np.object_),
                    {"scopecat_role": "availability", "source_variable": field.name},
                )
                if self.schema.diagnostics == "full":
                    data_vars[f"{field.name}__unavailable_metadata"] = (
                        ("point",),
                        np.asarray(metadata, dtype=np.object_),
                        {
                            "scopecat_role": "availability_metadata",
                            "source_variable": field.name,
                        },
                    )
        return xr.Dataset(
            data_vars=data_vars,
            coords=coords,
            attrs={
                "scopecat_dataset_id": self.schema.dataset_id,
                "scopecat_projection_json": _stable_json(asdict(self.schema)),
            },
        )

    def to_pandas(self) -> pd.DataFrame:
        """Convert through Arrow so tabular adapters share one mapping contract."""

        return cast("pd.DataFrame", self.to_arrow().to_pandas())

    def to_polars(self) -> object:
        """Convert through Arrow without making Polars a core dependency."""

        module = cast("_PolarsModule", _optional_module("polars", extra="polars"))
        return module.from_arrow(self.to_arrow())


def bind_projection(
    dataset: _ProjectionDataset,
    fields: Sequence[tuple[str, _ProjectionVariable, tuple[str, ...] | None]],
) -> MeasurementDataProjection:
    """Bind explicit external names to already validated dataset variables."""

    selected = tuple(
        ProjectionField(
            name=name,
            variable_id=variable.id,
            dtype=variable.dtype,
            unit=variable.unit,
            dims=variable.dims,
            role=variable.role,
            source_path=source_path,
            recording_group_id=variable.recording_group_id,
            label=variable.label,
        )
        for name, variable, source_path in fields
    )
    if not selected:
        raise ValueError("measurement projections require at least one field")
    _validate_external_names(selected, diagnostics="none", include_identity=True)
    return MeasurementDataProjection(
        dataset=dataset,
        schema=ProjectionSchema(dataset_id=dataset.schema.dataset_id, fields=selected),
    )


def _projected_values(
    variable: _ProjectionVariable,
    field: ProjectionField,
) -> Sequence[MeasurementValue]:
    if field.unit == variable.unit and field.dtype == variable.dtype:
        return variable.raw_values
    if variable.unit is None or field.unit is None:
        raise AssertionError(
            "projection unit conversion requires source and target units"
        )
    scale = Quantity(1.0, variable.unit).to(field.unit).value
    selected: list[MeasurementValue] = []
    for value in variable.raw_values:
        if isinstance(value, MeasurementUnavailable):
            selected.append(
                value.model_copy(update={"dtype": field.dtype, "unit": field.unit})
            )
        elif isinstance(value, MeasurementScalar):
            selected.append(
                MeasurementScalar.create(
                    value=cast("int | float | complex", value.value) * scale,
                    dtype=field.dtype,
                    unit=field.unit,
                    metadata=value.metadata,
                )
            )
        else:
            array = value
            selected.append(
                MeasurementArray.create(
                    values=np.asarray(
                        array.values,
                        dtype=(
                            np.complex128 if field.dtype == "complex128" else np.float64
                        ),
                    )
                    * scale,
                    dtype=field.dtype,
                    unit=field.unit,
                    metadata=array.metadata,
                )
            )
    return selected


def _unavailable_columns(
    values: Sequence[MeasurementValue],
) -> tuple[tuple[str | None, ...], tuple[str | None, ...]]:
    reasons: list[str | None] = []
    metadata: list[str | None] = []
    for value in values:
        if isinstance(value, MeasurementUnavailable):
            reasons.append(value.reason)
            metadata.append(_stable_json(value.metadata))
        else:
            reasons.append(None)
            metadata.append(None)
    return tuple(reasons), tuple(metadata)


def _field_metadata(field: ProjectionField) -> dict[bytes, bytes]:
    metadata = {
        b"scopecat.variable_id": field.variable_id.encode(),
        b"scopecat.dtype": field.dtype.encode(),
        b"scopecat.role": field.role.encode(),
        b"scopecat.dims": _stable_json(field.dims).encode(),
    }
    if field.unit is not None:
        metadata[b"units"] = field.unit.encode()
    if field.source_path is not None:
        metadata[b"scopecat.result_path"] = "/".join(field.source_path).encode()
    if field.recording_group_id is not None:
        metadata[b"scopecat.recording_group_id"] = field.recording_group_id.encode()
    if field.label is not None:
        metadata[b"long_name"] = field.label.encode()
    return metadata


def _validate_external_names(
    fields: Sequence[ProjectionField],
    *,
    diagnostics: ProjectionDiagnostics,
    include_identity: bool,
) -> None:
    names = [field.name for field in fields]
    if any(not name for name in names):
        raise ValueError("projection field names must be non-empty")
    generated = list(names)
    if include_identity:
        generated.extend(("point_index", "logical_point_id"))
    if diagnostics != "none":
        generated.extend(f"{name}__unavailable_reason" for name in names)
    if diagnostics == "full":
        generated.extend(f"{name}__unavailable_metadata" for name in names)
    if len(generated) != len(set(generated)):
        raise ValueError("projection field and generated column names must be unique")


def _stable_json(value: object) -> str:
    return json.dumps(
        thaw_json_value(value),
        separators=(",", ":"),
        sort_keys=True,
    )


def _optional_module(name: str, *, extra: str) -> object:
    try:
        return import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        raise ModuleNotFoundError(
            f"{name} is required for this conversion; install scopecat[{extra}]"
        ) from error


__all__ = [
    "MeasurementDataProjection",
    "ProjectionDiagnostics",
    "ProjectionField",
    "ProjectionSchema",
]
