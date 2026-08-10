# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false
"""Arrow-backed derived datasets crossing the analysis persistence boundary."""

from __future__ import annotations

from base64 import b64decode, b64encode
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from importlib import import_module
from typing import TYPE_CHECKING, Literal, Protocol, cast

import pyarrow as pa
import xarray as xr
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat.kernel.units import is_supported_unit
from scopecat.records._metadata import JsonMetadata, validate_json_metadata
from scopecat.records.analysis import AnalysisTable, AnalysisTableColumn

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl

DERIVED_DATASET_CODEC = "scopecat.derived-dataset.arrow-ipc.v1"
DERIVED_DATASET_MEDIA_TYPE = "application/vnd.apache.arrow.stream"

type DerivedDatasetRole = Literal["coordinate", "observable"]
type PandasIndexPolicy = Literal["auto", "columns", "drop"]


class _FrameModule(Protocol):
    DataFrame: type[object]


class _PolarsModule(_FrameModule, Protocol):
    def from_arrow(self, data: pa.Table) -> object: ...


class _PandasRangeIndex(Protocol):
    start: int
    step: int


class DerivedDatasetField(BaseModel):
    """One named Arrow column with the semantics needed outside its library."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    arrow_type: str
    nullable: bool
    role: DerivedDatasetRole = "observable"
    unit: str | None = None
    label: str | None = None
    attributes: JsonMetadata = Field(default_factory=dict)

    @field_validator("name", "arrow_type")
    @classmethod
    def validate_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("derived dataset field text must be non-empty")
        return value

    @field_validator("unit")
    @classmethod
    def validate_unit(cls, value: str | None) -> str | None:
        if value is not None and not is_supported_unit(value):
            raise ValueError(f"unsupported derived dataset unit: {value}")
        return value


class DerivedDatasetSchema(BaseModel):
    """Versioned semantic schema paired with an exact Arrow IPC schema."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    fields: tuple[DerivedDatasetField, ...]
    layout: Literal["table", "xarray_1d"] = "table"
    dimension: str | None = None
    attributes: JsonMetadata = Field(default_factory=dict)
    schema_id: Literal["scopecat.derived-dataset.v2"] = "scopecat.derived-dataset.v2"

    @field_validator("fields")
    @classmethod
    def validate_fields(
        cls,
        value: tuple[DerivedDatasetField, ...],
    ) -> tuple[DerivedDatasetField, ...]:
        if not value:
            raise ValueError("derived datasets require at least one field")
        names = tuple(field.name for field in value)
        if len(names) != len(set(names)):
            raise ValueError("derived dataset field names must be unique")
        return value

    @model_validator(mode="after")
    def validate_layout(self) -> DerivedDatasetSchema:
        if (self.layout == "xarray_1d") != (self.dimension is not None):
            raise ValueError(
                "xarray derived datasets require exactly one named dimension"
            )
        return self


class DerivedDatasetPayload(BaseModel):
    """Transport payload used while a derived dataset is being published."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_schema: DerivedDatasetSchema
    arrow_ipc_base64: str


@dataclass(frozen=True, slots=True)
class DerivedDataset:
    """A native-library result normalized for durable analysis reuse."""

    table: pa.Table
    schema: DerivedDatasetSchema

    @classmethod
    def from_arrow(
        cls,
        table: pa.Table,
        *,
        coordinates: Sequence[str] = (),
        units: Mapping[str, str] | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> DerivedDataset:
        """Normalize an Arrow table and bind its external field semantics."""

        selected = pa.Table.from_arrays(table.columns, schema=table.schema)
        return _bind_semantics(
            selected.combine_chunks(),
            coordinates=coordinates,
            units=units,
            labels=labels,
        )

    @classmethod
    def from_pandas(
        cls,
        frame: pd.DataFrame,
        *,
        coordinates: Sequence[str] = (),
        units: Mapping[str, str] | None = None,
        labels: Mapping[str, str] | None = None,
        index: PandasIndexPolicy = "auto",
    ) -> DerivedDataset:
        """Normalize a frame, retaining meaningful index levels as coordinates."""

        selected, index_coordinates = _pandas_columns(frame, policy=index)
        inherited = _pandas_semantics(frame)
        return _bind_semantics(
            pa.Table.from_pandas(selected, preserve_index=False),
            coordinates=coordinates,
            units=units,
            labels=labels,
            inherited_coordinates=(*index_coordinates, *inherited.coordinates),
            inherited_units=inherited.units,
            inherited_labels=inherited.labels,
        )

    @classmethod
    def from_polars(
        cls,
        frame: pl.DataFrame,
        *,
        coordinates: Sequence[str] = (),
        units: Mapping[str, str] | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> DerivedDataset:
        """Normalize one Polars frame through its native Arrow representation."""

        return cls.from_arrow(
            cast("pa.Table", frame.to_arrow()),
            coordinates=coordinates,
            units=units,
            labels=labels,
        )

    @classmethod
    def from_xarray(
        cls,
        dataset: xr.Dataset,
        *,
        coordinates: Sequence[str] = (),
        units: Mapping[str, str] | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> DerivedDataset:
        """Normalize an exactly reversible one-dimensional Xarray dataset."""

        dimension = _xarray_dimension(dataset)
        inherited_units: dict[str, str] = {}
        inherited_labels: dict[str, str] = {}
        field_attributes: dict[str, JsonMetadata] = {}
        for raw_name in dataset.variables:
            name = str(cast("object", raw_name))
            variable = dataset[raw_name]
            unit = cast("object | None", variable.attrs.get("units"))
            label = cast("object | None", variable.attrs.get("long_name"))
            if unit is not None:
                inherited_units[name] = str(unit)
            if label is not None:
                inherited_labels[name] = str(label)
            field_attributes[name] = _xarray_attributes(
                variable.attrs,
                owner=f"variable {name!r}",
            )
        names = tuple(
            dict.fromkeys(
                (
                    *(str(name) for name in dataset.coords),
                    *(str(name) for name in dataset.data_vars),
                )
            )
        )
        table = pa.table({name: pa.array(dataset[name].values) for name in names})
        return _bind_semantics(
            table,
            coordinates=coordinates or tuple(str(name) for name in dataset.coords),
            units={**inherited_units, **(units or {})},
            labels={**inherited_labels, **(labels or {})},
            layout="xarray_1d",
            dimension=dimension,
            attributes=_xarray_attributes(dataset.attrs, owner="dataset"),
            field_attributes=field_attributes,
        )

    @classmethod
    def from_payload(cls, payload: DerivedDatasetPayload) -> DerivedDataset:
        """Restore an uploaded derived dataset exactly."""

        try:
            encoded = b64decode(payload.arrow_ipc_base64, validate=True)
        except ValueError as error:
            raise ValueError("derived dataset Arrow IPC is invalid") from error
        return cls.from_arrow_ipc(encoded, schema=payload.dataset_schema)

    @classmethod
    def from_json_value(cls, value: JsonValue) -> DerivedDataset:
        """Restore the legacy JSON-safe transport representation."""

        return cls.from_payload(DerivedDatasetPayload.model_validate(value))

    @classmethod
    def from_arrow_ipc(
        cls,
        content: bytes,
        *,
        schema: DerivedDatasetSchema,
    ) -> DerivedDataset:
        """Restore persisted Arrow bytes against their semantic schema."""

        try:
            with pa.ipc.open_stream(content) as reader:
                table = reader.read_all()
        except (ValueError, pa.ArrowException) as error:
            raise ValueError("derived dataset Arrow IPC is invalid") from error
        expected = tuple(
            (field.name, field.arrow_type, field.nullable) for field in schema.fields
        )
        actual = tuple(
            (field.name, str(field.type), field.nullable) for field in table.schema
        )
        if actual != expected:
            raise ValueError("derived dataset semantic and Arrow schemas disagree")
        return cls(table=table, schema=schema)

    def to_arrow_ipc(self) -> bytes:
        """Encode exact Arrow values for content-addressed run storage."""

        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, self.table.schema) as writer:
            writer.write_table(self.table)
        return sink.getvalue().to_pybytes()

    def to_payload(self) -> DerivedDatasetPayload:
        """Encode the temporary daemon command payload used during publication."""

        return DerivedDatasetPayload(
            dataset_schema=self.schema,
            arrow_ipc_base64=b64encode(self.to_arrow_ipc()).decode("ascii"),
        )

    def to_json_value(self) -> JsonValue:
        """Encode the legacy JSON-safe transport representation."""

        return cast("JsonValue", self.to_payload().model_dump(mode="json"))

    def to_analysis_table(
        self,
        *,
        columns: Sequence[str] | None = None,
    ) -> AnalysisTable:
        """Create a bounded scalar presentation from explicitly selected columns."""

        fields = {field.name: field for field in self.schema.fields}
        selected_names = (
            tuple(self.table.column_names) if columns is None else tuple(columns)
        )
        if not selected_names:
            raise ValueError("analysis table requires at least one dataset column")
        if len(selected_names) != len(set(selected_names)):
            raise ValueError("analysis table dataset columns must be unique")
        unknown = set(selected_names) - set(self.table.column_names)
        if unknown:
            raise KeyError(
                "derived dataset has no columns: " + ", ".join(sorted(unknown))
            )
        selected = self.table.select(selected_names)
        return AnalysisTable.from_rows(
            cast("list[Mapping[str, object]]", selected.to_pylist()),
            columns=tuple(
                AnalysisTableColumn(
                    id=name,
                    label=fields[name].label,
                    unit=fields[name].unit,
                )
                for name in selected_names
            ),
        )

    def to_pandas(self) -> pd.DataFrame:
        """Return a normal pandas frame for further analysis."""

        _optional_module("pandas", extra="pandas")
        return cast("pd.DataFrame", self.table.to_pandas())

    def to_polars(self) -> pl.DataFrame:
        """Return a normal Polars frame for further analysis."""

        module = cast(
            "_PolarsModule",
            _optional_module("polars", extra="polars"),
        )
        return cast("pl.DataFrame", module.from_arrow(self.table))

    def to_xarray(self) -> xr.Dataset:
        """Restore a native Xarray dataset when its topology was preserved."""

        if self.schema.layout != "xarray_1d" or self.schema.dimension is None:
            raise ValueError("only Xarray-authored derived datasets can restore Xarray")
        dimension = self.schema.dimension
        coordinates: dict[str, object] = {}
        data_variables: dict[str, object] = {}
        for field in self.schema.fields:
            variable = (
                dimension,
                self.table[field.name].combine_chunks().to_numpy(zero_copy_only=False),
                dict(field.attributes),
            )
            if field.role == "coordinate":
                coordinates[field.name] = variable
            else:
                data_variables[field.name] = variable
        return xr.Dataset(
            data_vars=data_variables,
            coords=coordinates,
            attrs=dict(self.schema.attributes),
        )


def derived_dataset(
    data: object,
    *,
    coordinates: Sequence[str] = (),
    units: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
    index: PandasIndexPolicy = "auto",
) -> DerivedDataset:
    """Normalize an Arrow, pandas, Polars, or Xarray result for persistence."""

    if isinstance(data, DerivedDataset):
        if coordinates or units or labels or index != "auto":
            raise ValueError("an existing derived dataset already owns its schema")
        return data
    if isinstance(data, pa.Table):
        if index != "auto":
            raise ValueError("index policy only applies to pandas data")
        return DerivedDataset.from_arrow(
            data,
            coordinates=coordinates,
            units=units,
            labels=labels,
        )
    if isinstance(data, xr.Dataset):
        if index != "auto":
            raise ValueError("index policy only applies to pandas data")
        return DerivedDataset.from_xarray(
            data,
            coordinates=coordinates,
            units=units,
            labels=labels,
        )
    owner = type(data).__module__.partition(".")[0]
    if owner == "pandas":
        pandas = cast("_FrameModule", _optional_module("pandas", extra="pandas"))
        if not isinstance(data, pandas.DataFrame):
            raise TypeError("unsupported pandas derived dataset object")
        return DerivedDataset.from_pandas(
            cast("pd.DataFrame", data),
            coordinates=coordinates,
            units=units,
            labels=labels,
            index=index,
        )
    if owner == "polars":
        if index != "auto":
            raise ValueError("index policy only applies to pandas data")
        polars = cast("_PolarsModule", _optional_module("polars", extra="polars"))
        if not isinstance(data, polars.DataFrame):
            raise TypeError("unsupported Polars derived dataset object")
        return DerivedDataset.from_polars(
            cast("pl.DataFrame", data),
            coordinates=coordinates,
            units=units,
            labels=labels,
        )
    raise TypeError("derived_dataset requires Arrow, pandas, Polars, or Xarray data")


def _bind_semantics(
    table: pa.Table,
    *,
    coordinates: Sequence[str],
    units: Mapping[str, str] | None,
    labels: Mapping[str, str] | None,
    inherited_coordinates: Sequence[str] = (),
    inherited_units: Mapping[str, str] | None = None,
    inherited_labels: Mapping[str, str] | None = None,
    layout: Literal["table", "xarray_1d"] = "table",
    dimension: str | None = None,
    attributes: Mapping[str, object] | None = None,
    field_attributes: Mapping[str, JsonMetadata] | None = None,
) -> DerivedDataset:
    names = tuple(table.column_names)
    if not names or len(names) != len(set(names)):
        raise ValueError("derived dataset columns must be non-empty and unique")
    arrow_semantics = _arrow_semantics(table.schema)
    coordinate_names = tuple(
        dict.fromkeys(
            (*inherited_coordinates, *arrow_semantics.coordinates, *coordinates)
        )
    )
    selected_units = {
        **arrow_semantics.units,
        **(inherited_units or {}),
        **(units or {}),
    }
    selected_labels = {
        **arrow_semantics.labels,
        **(inherited_labels or {}),
        **(labels or {}),
    }
    configured = set(coordinate_names) | set(selected_units) | set(selected_labels)
    unknown = configured - set(names)
    if unknown:
        raise KeyError("derived dataset has no columns: " + ", ".join(sorted(unknown)))
    if len(coordinate_names) != len(set(coordinate_names)):
        raise ValueError("derived dataset coordinates must be unique")
    semantic_fields = tuple(
        DerivedDatasetField(
            name=field.name,
            arrow_type=str(field.type),
            nullable=field.nullable,
            role="coordinate" if field.name in coordinate_names else "observable",
            unit=selected_units.get(field.name),
            label=selected_labels.get(field.name),
            attributes={
                **(field_attributes or {}).get(field.name, {}),
                **(
                    {}
                    if selected_units.get(field.name) is None
                    else {"units": cast("JsonValue", selected_units[field.name])}
                ),
                **(
                    {}
                    if selected_labels.get(field.name) is None
                    else {"long_name": cast("JsonValue", selected_labels[field.name])}
                ),
            },
        )
        for field in table.schema
    )
    arrow_fields = tuple(
        field.with_metadata(
            {
                **(field.metadata or {}),
                b"scopecat.role": semantic.role.encode(),
                **({} if semantic.unit is None else {b"units": semantic.unit.encode()}),
                **(
                    {}
                    if semantic.label is None
                    else {b"long_name": semantic.label.encode()}
                ),
            }
        )
        for field, semantic in zip(table.schema, semantic_fields, strict=True)
    )
    schema = pa.schema(
        arrow_fields,
        metadata={b"scopecat.schema": b"scopecat.derived-dataset.v2"},
    )
    return DerivedDataset(
        table=pa.Table.from_arrays(table.columns, schema=schema),
        schema=DerivedDatasetSchema(
            fields=semantic_fields,
            layout=layout,
            dimension=dimension,
            attributes=validate_json_metadata(attributes or {}),
        ),
    )


def _xarray_dimension(dataset: xr.Dataset) -> str:
    if any(not isinstance(name, str) for name in dataset.sizes):
        raise TypeError("derived Xarray dimension names must be strings")
    if any(not isinstance(name, str) for name in dataset.variables):
        raise TypeError("derived Xarray variable names must be strings")
    dimensions = tuple(dataset.sizes)
    if len(dimensions) != 1:
        raise ValueError(
            "derived Xarray datasets require exactly one dimension; "
            "publish a deliberate tabular projection or preserve the native "
            "dataset as an analysis artifact"
        )
    dimension = cast("str", dimensions[0])
    index = dataset.indexes.get(dimension)
    if index is not None and cast("int", index.nlevels) != 1:
        raise ValueError(
            "derived Xarray datasets do not flatten multi-index dimensions; "
            "publish a deliberate projection or preserve the native dataset "
            "as an analysis artifact"
        )
    for raw_name in dataset.variables:
        name = cast("str", raw_name)
        if tuple(dataset[raw_name].dims) != (dimension,):
            raise ValueError(
                f"derived Xarray variable {name!r} must use dimension "
                f"{dimension!r} exactly; publish a deliberate projection or "
                "preserve the native dataset as an analysis artifact"
            )
    return dimension


def _xarray_attributes(
    value: Mapping[object, object],
    *,
    owner: str,
) -> JsonMetadata:
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"derived Xarray {owner} attributes require string keys")
    try:
        return validate_json_metadata(value)
    except ValueError as error:
        raise TypeError(
            f"derived Xarray {owner} attributes must be finite JSON values; "
            "preserve the native dataset as an analysis artifact"
        ) from error


@dataclass(frozen=True, slots=True)
class _InheritedSemantics:
    coordinates: tuple[str, ...] = ()
    units: Mapping[str, str] = dataclass_field(default_factory=dict)
    labels: Mapping[str, str] = dataclass_field(default_factory=dict)


def _arrow_semantics(schema: pa.Schema) -> _InheritedSemantics:
    coordinates: list[str] = []
    units: dict[str, str] = {}
    labels: dict[str, str] = {}
    for field in schema:
        metadata = field.metadata or {}
        if metadata.get(b"scopecat.role") == b"coordinate":
            coordinates.append(field.name)
        if (unit := metadata.get(b"units")) is not None:
            units[field.name] = unit.decode()
        if (label := metadata.get(b"long_name")) is not None:
            labels[field.name] = label.decode()
    return _InheritedSemantics(tuple(coordinates), units, labels)


def _pandas_columns(
    frame: pd.DataFrame,
    *,
    policy: PandasIndexPolicy,
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    if policy not in {"auto", "columns", "drop"}:
        raise ValueError("pandas index policy must be auto, columns, or drop")
    non_text_columns = tuple(
        column for column in frame.columns if not isinstance(column, str)
    )
    if non_text_columns:
        raise TypeError("derived dataset pandas columns must be strings")
    if policy == "drop":
        return frame, ()
    index = frame.index
    range_index = cast("_PandasRangeIndex", cast("object", index))
    is_implicit = (
        policy == "auto"
        and type(index).__name__ == "RangeIndex"
        and index.name is None
        and range_index.start == 0
        and range_index.step == 1
    )
    if is_implicit:
        return frame, ()
    index_names = cast("Sequence[object]", index.names)
    names = tuple(
        str(name)
        if name is not None
        else ("index" if index.nlevels == 1 else f"level_{i}")
        for i, name in enumerate(index_names)
    )
    frame_columns = cast("Sequence[object]", cast("object", frame.columns))
    conflicts = set(names) & {str(column) for column in frame_columns}
    if conflicts:
        raise ValueError(
            "pandas index names conflict with columns: " + ", ".join(sorted(conflicts))
        )
    selected = frame.copy(deep=False)
    selected.index = selected.index.set_names(names)
    return selected.reset_index(), names


def _pandas_semantics(frame: pd.DataFrame) -> _InheritedSemantics:
    value = frame.attrs.get("scopecat")
    if not isinstance(value, Mapping):
        return _InheritedSemantics()
    raw_fields = value.get("fields")
    if not isinstance(raw_fields, Sequence):
        return _InheritedSemantics()
    coordinates: list[str] = []
    units: dict[str, str] = {}
    labels: dict[str, str] = {}
    available = {str(column) for column in frame.columns}
    for raw_field in raw_fields:
        if not isinstance(raw_field, Mapping):
            continue
        name = raw_field.get("name")
        if not isinstance(name, str) or name not in available:
            continue
        if raw_field.get("role") == "coordinate":
            coordinates.append(name)
        if isinstance(unit := raw_field.get("unit"), str):
            units[name] = unit
        if isinstance(label := raw_field.get("label"), str):
            labels[name] = label
    return _InheritedSemantics(tuple(coordinates), units, labels)


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
    "DERIVED_DATASET_CODEC",
    "DERIVED_DATASET_MEDIA_TYPE",
    "DerivedDataset",
    "DerivedDatasetField",
    "DerivedDatasetPayload",
    "DerivedDatasetRole",
    "DerivedDatasetSchema",
    "PandasIndexPolicy",
    "derived_dataset",
]
