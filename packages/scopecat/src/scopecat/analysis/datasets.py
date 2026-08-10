# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false
"""Arrow-backed derived datasets crossing the analysis persistence boundary."""

from __future__ import annotations

from base64 import b64decode, b64encode
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib import import_module
from typing import TYPE_CHECKING, Literal, Protocol, cast

import pyarrow as pa
import xarray as xr
from pydantic import BaseModel, ConfigDict, JsonValue, field_validator

from scopecat.kernel.units import is_supported_unit
from scopecat.records.analysis import AnalysisTable, AnalysisTableColumn

if TYPE_CHECKING:
    import pandas as pd
    import polars as pl

DERIVED_DATASET_CODEC = "scopecat.derived-dataset.arrow-ipc.v1"

type DerivedDatasetRole = Literal["coordinate", "observable"]


class _FrameModule(Protocol):
    DataFrame: type[object]


class _PolarsModule(_FrameModule, Protocol):
    def from_arrow(self, data: pa.Table) -> object: ...


class DerivedDatasetField(BaseModel):
    """One named Arrow column with the semantics needed outside its library."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    arrow_type: str
    nullable: bool
    role: DerivedDatasetRole = "observable"
    unit: str | None = None
    label: str | None = None

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
    schema_id: Literal["scopecat.derived-dataset.v1"] = "scopecat.derived-dataset.v1"

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


class _DerivedDatasetPayload(BaseModel):
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

        selected = pa.Table.from_arrays(table.columns, names=table.column_names)
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
    ) -> DerivedDataset:
        """Normalize one pandas frame without persisting its implicit index."""

        return cls.from_arrow(
            pa.Table.from_pandas(frame, preserve_index=False),
            coordinates=coordinates,
            units=units,
            labels=labels,
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
        """Flatten an explicitly selected Xarray result into observation rows."""

        frame = dataset.to_dataframe().reset_index()
        return cls.from_pandas(
            frame,
            coordinates=coordinates or tuple(str(name) for name in dataset.coords),
            units=units,
            labels=labels,
        )

    @classmethod
    def from_json_value(cls, value: JsonValue) -> DerivedDataset:
        """Restore a persisted derived dataset output exactly."""

        payload = _DerivedDatasetPayload.model_validate(value)
        try:
            encoded = b64decode(payload.arrow_ipc_base64, validate=True)
            with pa.ipc.open_stream(encoded) as reader:
                table = reader.read_all()
        except (ValueError, pa.ArrowException) as error:
            raise ValueError("derived dataset Arrow IPC is invalid") from error
        expected = tuple(
            (field.name, field.arrow_type, field.nullable)
            for field in payload.dataset_schema.fields
        )
        actual = tuple(
            (field.name, str(field.type), field.nullable) for field in table.schema
        )
        if actual != expected:
            raise ValueError("derived dataset semantic and Arrow schemas disagree")
        return cls(table=table, schema=payload.dataset_schema)

    def to_json_value(self) -> JsonValue:
        """Encode exact Arrow values plus a small semantic sidecar."""

        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, self.table.schema) as writer:
            writer.write_table(self.table)
        payload = _DerivedDatasetPayload(
            dataset_schema=self.schema,
            arrow_ipc_base64=b64encode(sink.getvalue().to_pybytes()).decode("ascii"),
        )
        return cast("JsonValue", payload.model_dump(mode="json"))

    def to_analysis_table(self) -> AnalysisTable:
        """Create the bounded scalar presentation used by table and figure outputs."""

        fields = {field.name: field for field in self.schema.fields}
        return AnalysisTable.from_rows(
            cast("list[Mapping[str, object]]", self.table.to_pylist()),
            columns=tuple(
                AnalysisTableColumn(
                    id=name,
                    label=fields[name].label,
                    unit=fields[name].unit,
                )
                for name in self.table.column_names
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


def derived_dataset(
    data: object,
    *,
    coordinates: Sequence[str] = (),
    units: Mapping[str, str] | None = None,
    labels: Mapping[str, str] | None = None,
) -> DerivedDataset:
    """Normalize an Arrow, pandas, Polars, or Xarray result for persistence."""

    if isinstance(data, DerivedDataset):
        if coordinates or units or labels:
            raise ValueError("an existing derived dataset already owns its schema")
        return data
    if isinstance(data, pa.Table):
        return DerivedDataset.from_arrow(
            data,
            coordinates=coordinates,
            units=units,
            labels=labels,
        )
    if isinstance(data, xr.Dataset):
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
        )
    if owner == "polars":
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
) -> DerivedDataset:
    names = tuple(table.column_names)
    if not names or len(names) != len(set(names)):
        raise ValueError("derived dataset columns must be non-empty and unique")
    coordinate_names = tuple(coordinates)
    configured = set(coordinate_names) | set(units or {}) | set(labels or {})
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
            unit=None if units is None else units.get(field.name),
            label=None if labels is None else labels.get(field.name),
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
        metadata={b"scopecat.schema": b"scopecat.derived-dataset.v1"},
    )
    return DerivedDataset(
        table=pa.Table.from_arrays(table.columns, schema=schema),
        schema=DerivedDatasetSchema(fields=semantic_fields),
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
    "DERIVED_DATASET_CODEC",
    "DerivedDataset",
    "DerivedDatasetField",
    "DerivedDatasetRole",
    "DerivedDatasetSchema",
    "derived_dataset",
]
