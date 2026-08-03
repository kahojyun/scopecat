# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false
# pyright: reportUnnecessaryTypeIgnoreComment=false
"""Notebook-facing labeled views over durable measurement records."""

from __future__ import annotations

import json
import math
import operator
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast, overload, override

from scopecat.kernel.quantity import Quantity
from scopecat.measurements.traces import Trace, measurement_traces
from scopecat.records.artifact import RunContentEntry
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDType,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
    MeasurementValue,
    MeasurementVariable,
)

if TYPE_CHECKING:
    import pandas as pd  # pyright: ignore[reportMissingImports]
    import pyarrow as pa  # pyright: ignore[reportMissingImports]
    import xarray as xr  # pyright: ignore[reportMissingImports]

type NativeScalar = bool | int | float | complex | str
type NativeValue = NativeScalar | tuple[NativeValue, ...] | None
type GroupKey = NativeScalar | None
type PointIndexer = int | slice | Sequence[int] | Sequence[bool]
type PointCondition = PointMask | Sequence[bool]
type SelectionMethod = Literal["exact", "nearest"]
type PandasLayout = Literal["points", "long"]


class _PandasFrameFactory(Protocol):
    def __call__(self, data: object = ...) -> pd.DataFrame: ...


class _PandasModule(Protocol):
    DataFrame: _PandasFrameFactory


class _ArrowModule(Protocol):
    def table(self, data: Mapping[str, Sequence[object]]) -> pa.Table: ...


class _XarrayDatasetFactory(Protocol):
    def __call__(
        self,
        data_vars: Mapping[str, object] = ...,
        coords: Mapping[str, object] = ...,
        attrs: Mapping[str, object] = ...,
    ) -> xr.Dataset: ...


class _XarrayModule(Protocol):
    Dataset: _XarrayDatasetFactory


class _NumpyModule(Protocol):
    float64: object
    int64: object
    complex128: object
    bool_: object
    object_: object

    def asarray(self, value: object, *, dtype: object = ...) -> object: ...

    def empty(self, shape: Sequence[int], *, dtype: object = ...) -> object: ...


@dataclass(frozen=True, slots=True)
class _RaggedXarrayValues:
    values: object
    parent_points: object
    row_sizes: object
    local_indices: tuple[object, ...]
    local_extents: tuple[object, ...]


class PointMask(Sequence[bool]):
    """A point-aligned boolean selection returned by variable comparisons."""

    __slots__ = ("_dataset", "_values")

    def __init__(self, dataset: Dataset, values: Sequence[bool]) -> None:
        self._dataset = dataset
        self._values = tuple(values)

    @overload
    def __getitem__(self, index: int) -> bool: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[bool, ...]: ...

    @override
    def __getitem__(self, index: int | slice) -> bool | tuple[bool, ...]:
        return self._values[index]

    @override
    def __len__(self) -> int:
        return len(self._values)

    @override
    def __iter__(self) -> Iterator[bool]:
        return iter(self._values)

    def __and__(self, other: PointMask) -> PointMask:
        self._require_same_dataset(other)
        return PointMask(
            self._dataset,
            tuple(left and right for left, right in zip(self, other, strict=True)),
        )

    def __or__(self, other: PointMask) -> PointMask:
        self._require_same_dataset(other)
        return PointMask(
            self._dataset,
            tuple(left or right for left, right in zip(self, other, strict=True)),
        )

    def __invert__(self) -> PointMask:
        return PointMask(self._dataset, tuple(not value for value in self))

    def __bool__(self) -> bool:
        raise TypeError("a PointMask has no single truth value; pass it to where()")

    @override
    def __repr__(self) -> str:
        return f"PointMask({self._values!r})"

    def belongs_to(self, dataset: Dataset) -> bool:
        return self._dataset is dataset

    def _require_same_dataset(self, other: PointMask) -> None:
        if self._dataset is not other._dataset:
            raise ValueError("cannot combine point masks from different dataset views")


class Variable:
    """One labeled coordinate or observable aligned to a :class:`Dataset`."""

    __slots__ = ("_dataset", "_definition")

    def __init__(self, dataset: Dataset, definition: MeasurementVariable) -> None:
        self._dataset = dataset
        self._definition = definition

    @property
    def id(self) -> str:
        return self._definition.id

    @property
    def role(self) -> Literal["coordinate", "observable"]:
        return self._definition.role

    @property
    def dtype(self) -> MeasurementDType:
        return self._definition.dtype

    @property
    def unit(self) -> str | None:
        return self._definition.unit

    @property
    def dims(self) -> tuple[str, ...]:
        return tuple(self._definition.dims)

    @property
    def shape(self) -> tuple[int | None, ...]:
        return tuple(self._dataset.dims[dim] for dim in self.dims)

    @property
    def label(self) -> str | None:
        return self._definition.label

    @property
    def recording_group_id(self) -> str | None:
        return self._definition.recording_group_id

    @property
    def metadata(self) -> Mapping[str, object]:
        return MappingProxyType(dict(self._definition.metadata))

    @property
    def definition(self) -> MeasurementVariable:
        """Return the durable schema definition for low-level inspection."""

        return self._definition

    @property
    def raw_values(self) -> tuple[MeasurementValue, ...]:
        field = "coordinates" if self.role == "coordinate" else "observables"
        return tuple(
            getattr(record, field)[self.id] for record in self._dataset.records
        )

    @property
    def values(self) -> tuple[NativeValue, ...]:
        """Return Python-native values, using ``None`` for unavailable points."""

        return tuple(_native_value(value) for value in self.raw_values)

    @property
    def availability(
        self,
    ) -> tuple[MeasurementUnavailableReason | None, ...]:
        return tuple(
            value.reason if isinstance(value, MeasurementUnavailable) else None
            for value in self.raw_values
        )

    def is_available(self) -> PointMask:
        return PointMask(
            self._dataset,
            tuple(reason is None for reason in self.availability),
        )

    def is_unavailable(
        self,
        reason: MeasurementUnavailableReason | None = None,
    ) -> PointMask:
        if reason is None:
            selected = tuple(value is not None for value in self.availability)
        else:
            selected = tuple(value == reason for value in self.availability)
        return PointMask(self._dataset, selected)

    def __getitem__(self, index: int | slice) -> NativeValue | tuple[NativeValue, ...]:
        return self.values[index]

    def __lt__(self, other: object) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], bool]", operator.lt)
        )

    def __le__(self, other: object) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], bool]", operator.le)
        )

    @override
    def __eq__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, other: object
    ) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], bool]", operator.eq)
        )

    @override
    def __ne__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, other: object
    ) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], bool]", operator.ne)
        )

    def __gt__(self, other: object) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], bool]", operator.gt)
        )

    def __ge__(self, other: object) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], bool]", operator.ge)
        )

    @override
    def __repr__(self) -> str:
        unit = "" if self.unit is None else f", unit={self.unit!r}"
        return f"Variable(id={self.id!r}, role={self.role!r}, dims={self.dims!r}{unit})"

    def _compare(
        self,
        other: object,
        comparison: Callable[[object, object], bool],
    ) -> PointMask:
        self.require_point_scalar()
        query = _selection_value(other, self)
        selected = tuple(
            False if value is None else comparison(value, query)
            for value in self.values
        )
        return PointMask(self._dataset, selected)

    def require_point_scalar(self) -> None:
        if self.dims != ("point",):
            raise ValueError(
                f"variable {self.id!r} has dimensions {self.dims!r}; "
                "point predicates require a scalar variable"
            )


@dataclass(frozen=True, slots=True, init=False)
class Dataset:
    """A labeled, sliceable measurement dataset for notebook workflows.

    The durable Pydantic dataset remains available through :attr:`raw`; this
    facade adds labeled variables and ecosystem adapters without changing the
    persisted representation.
    """

    _raw: MeasurementDataset
    entry: RunContentEntry
    _variables: Mapping[str, Variable] = field(init=False, repr=False)

    def __init__(self, raw: MeasurementDataset, entry: RunContentEntry) -> None:
        object.__setattr__(self, "_raw", raw)
        object.__setattr__(self, "entry", entry)
        self.__post_init__()

    def __post_init__(self) -> None:
        variables = {
            definition.id: Variable(self, definition)
            for definition in self._raw.dataset_schema.variables
        }
        object.__setattr__(self, "_variables", MappingProxyType(variables))

    @property
    def raw(self) -> MeasurementDataset:
        """Return the selected durable record model as an explicit escape hatch."""

        return self._raw

    @property
    def schema(self) -> MeasurementDatasetSchema:
        return self._raw.dataset_schema

    @property
    def records(self) -> tuple[MeasurementRecord, ...]:
        return tuple(self._raw.records)

    @property
    def metadata(self) -> Mapping[str, object]:
        return MappingProxyType(dict(self._raw.metadata))

    @property
    def dims(self) -> Mapping[str, int | None]:
        return MappingProxyType(
            {dimension.id: dimension.size for dimension in self.schema.dimensions}
        )

    @property
    def variables(self) -> Mapping[str, Variable]:
        return self._variables

    @property
    def coords(self) -> Mapping[str, Variable]:
        return MappingProxyType(
            {
                variable_id: variable
                for variable_id, variable in self.variables.items()
                if variable.role == "coordinate"
            }
        )

    @property
    def data_vars(self) -> Mapping[str, Variable]:
        return MappingProxyType(
            {
                variable_id: variable
                for variable_id, variable in self.variables.items()
                if variable.role == "observable"
            }
        )

    def __getitem__(self, variable_id: str) -> Variable:
        try:
            return self.variables[variable_id]
        except KeyError as error:
            raise KeyError(
                f"measurement dataset has no variable {variable_id!r}"
            ) from error

    def __len__(self) -> int:
        return len(self.records)

    def __iter__(self) -> Iterator[str]:
        return iter(self.variables)

    @override
    def __repr__(self) -> str:
        coordinates = ", ".join(self.coords)
        observables = ", ".join(self.data_vars)
        return (
            f"Dataset(id={self.schema.dataset_id!r}, points={len(self)}, "
            f"coords=[{coordinates}], data_vars=[{observables}])"
        )

    def isel(
        self,
        indexers: Mapping[str, PointIndexer] | None = None,
        /,
        **indexer_kwargs: PointIndexer,
    ) -> Self:
        """Select point rows by position while preserving the point dimension."""

        selected = _merge_indexers(indexers, indexer_kwargs)
        if set(selected) != {"point"}:
            unknown = sorted(set(selected) - {"point"})
            if unknown:
                raise ValueError(
                    "isel currently supports the point dimension; unknown "
                    f"dimensions: {', '.join(unknown)}"
                )
            raise ValueError("isel requires a point indexer")
        indices = _point_indices(selected["point"], size=len(self))
        return self._select_indices(indices)

    def sel(
        self,
        indexers: Mapping[str, object] | None = None,
        /,
        *,
        method: SelectionMethod | None = None,
        tolerance: float | Quantity | None = None,
        **indexer_kwargs: object,
    ) -> Self:
        """Select point rows by scalar coordinates or logical point identity.

        Exact selection keeps every matching row, including repeated coordinate
        values. ``method="nearest"`` accepts one numeric coordinate and keeps all
        equally near rows.
        """

        selected = _merge_indexers(indexers, indexer_kwargs)
        if not selected:
            raise ValueError("sel requires at least one coordinate indexer")
        selected_method = "exact" if method is None else method
        if selected_method not in {"exact", "nearest"}:
            raise ValueError("sel method must be 'exact' or 'nearest'")
        if selected_method == "nearest":
            if len(selected) != 1 or "point" in selected:
                raise ValueError(
                    "nearest selection requires exactly one scalar coordinate"
                )
            variable_id, query = next(iter(selected.items()))
            variable = self._require_scalar_coordinate(variable_id)
            normalized = _selection_value(query, variable)
            indices = _nearest_indices(
                variable,
                normalized,
                tolerance=_selection_tolerance(tolerance, variable),
            )
        else:
            if tolerance is not None:
                raise ValueError("sel tolerance is only valid with method='nearest'")
            mask = [True] * len(self)
            for variable_id, query in selected.items():
                if variable_id == "point":
                    matches = _point_identity_matches(self.records, query)
                else:
                    variable = self._require_scalar_coordinate(variable_id)
                    normalized = _selection_value(query, variable)
                    matches = tuple(
                        value is not None and value == normalized
                        for value in variable.values
                    )
                mask = [
                    current and matches[index] for index, current in enumerate(mask)
                ]
            indices = tuple(index for index, keep in enumerate(mask) if keep)
        if not indices:
            rendered = ", ".join(f"{key}={value!r}" for key, value in selected.items())
            raise KeyError(f"no measurement points match {rendered}")
        return self._select_indices(indices)

    def where(
        self,
        condition: PointCondition | Callable[[Dataset], PointCondition],
    ) -> Self:
        """Keep rows selected by a point mask or a callable producing one."""

        selected = condition(self) if callable(condition) else condition
        if isinstance(selected, PointMask):
            if not selected.belongs_to(self):
                raise ValueError("point mask belongs to a different dataset view")
            mask = tuple(selected)
        else:
            mask = tuple(selected)
        if len(mask) != len(self):
            raise ValueError(f"point mask has length {len(mask)}; expected {len(self)}")
        if any(type(value) is not bool for value in mask):
            raise TypeError("point mask values must be bool")
        return self._select_indices(
            tuple(index for index, keep in enumerate(mask) if keep)
        )

    def groupby(self, variable_id: str) -> Mapping[GroupKey, Self]:
        """Group point rows by a scalar variable, preserving first-seen order."""

        variable = self[variable_id]
        variable.require_point_scalar()
        positions: dict[GroupKey, list[int]] = {}
        for position, value in enumerate(variable.values):
            key = cast("GroupKey", value)
            positions.setdefault(key, []).append(position)
        return MappingProxyType(
            {
                key: self._select_indices(group_positions)
                for key, group_positions in positions.items()
            }
        )

    def traces(
        self,
        observable: str | None = None,
        *,
        coordinate: str | None = None,
        group: str | None = None,
    ) -> tuple[Trace, ...]:
        return measurement_traces(
            self.raw,
            observable,
            coordinate=coordinate,
            group=group,
        )

    def to_xarray(self) -> xr.Dataset:
        """Convert to an xarray Dataset while retaining Scopecat schema attrs."""

        xr_module = cast("_XarrayModule", _optional_module("xarray"))
        np_module = cast("_NumpyModule", _optional_module("numpy"))
        coords: dict[str, object] = {
            "point": (
                ("point",),
                np_module.asarray(
                    tuple(record.point_index for record in self.records),
                    dtype=np_module.int64,
                ),
                {"long_name": "original measurement point index"},
            )
        }
        if "logical_point_id" not in self.variables and any(
            record.logical_point_id is not None for record in self.records
        ):
            coords["logical_point_id"] = (
                ("point",),
                np_module.asarray(
                    tuple(record.logical_point_id for record in self.records),
                    dtype=np_module.object_,
                ),
                {"long_name": "Scopecat logical point id"},
            )
        data_vars: dict[str, object] = {}
        for variable in self.variables.values():
            target = coords if variable.role == "coordinate" else data_vars
            if _variable_is_ragged(variable):
                observation_dim = _ragged_observation_dim(variable.id)
                ragged = _xarray_ragged_values(
                    variable,
                    np_module,
                    records=self.records,
                )
                target[variable.id] = (
                    (observation_dim,),
                    ragged.values,
                    {
                        **_variable_attrs(variable),
                        "scopecat_ragged_representation": "indexed_observation",
                    },
                )
                coords[_ragged_parent_name(variable.id)] = (
                    (observation_dim,),
                    ragged.parent_points,
                    {
                        "long_name": f"parent point position for {variable.id}",
                        "scopecat_role": "ragged_parent_point",
                        "source_variable": variable.id,
                    },
                )
                coords[_ragged_row_size_name(variable.id)] = (
                    ("point",),
                    ragged.row_sizes,
                    {
                        "long_name": f"point-local observation count for {variable.id}",
                        "scopecat_role": "ragged_row_size",
                        "source_variable": variable.id,
                    },
                )
                for local_axis, dimension_id in enumerate(variable.dims[1:]):
                    coords[_ragged_local_index_name(variable.id, dimension_id)] = (
                        (observation_dim,),
                        ragged.local_indices[local_axis],
                        {
                            "long_name": (
                                f"point-local {dimension_id} index for {variable.id}"
                            ),
                            "scopecat_role": "ragged_local_index",
                            "source_variable": variable.id,
                            "source_dimension": dimension_id,
                        },
                    )
                    coords[_ragged_local_extent_name(variable.id, dimension_id)] = (
                        ("point",),
                        ragged.local_extents[local_axis],
                        {
                            "long_name": (
                                f"point-local {dimension_id} extent for {variable.id}"
                            ),
                            "scopecat_role": "ragged_local_extent",
                            "source_variable": variable.id,
                            "source_dimension": dimension_id,
                        },
                    )
            else:
                target[variable.id] = (
                    variable.dims,
                    _xarray_values(variable, np_module),
                    _variable_attrs(variable),
                )
            if any(reason is not None for reason in variable.availability):
                data_vars[_unavailable_reason_name(variable.id)] = (
                    ("point",),
                    np_module.asarray(
                        variable.availability,
                        dtype=np_module.object_,
                    ),
                    {
                        "long_name": f"unavailable reason for {variable.id}",
                        "scopecat_role": "availability",
                        "source_variable": variable.id,
                    },
                )
        return xr_module.Dataset(
            data_vars=data_vars,
            coords=coords,
            attrs=_dataset_attrs(self),
        )

    def to_arrow(self) -> pa.Table:
        """Convert to a point-row Arrow table with nested point-local arrays."""

        pa_module = cast("_ArrowModule", _optional_module("pyarrow"))
        columns: dict[str, Sequence[object]] = {
            "point_index": tuple(record.point_index for record in self.records),
            "logical_point_id": tuple(
                record.logical_point_id for record in self.records
            ),
        }
        for variable in self.variables.values():
            columns[variable.id] = tuple(
                _arrow_value(value) for value in variable.raw_values
            )
            if any(reason is not None for reason in variable.availability):
                columns[_unavailable_reason_name(variable.id)] = variable.availability
        table = pa_module.table(columns)
        metadata = dict(table.schema.metadata or {})
        metadata.update(
            {
                b"scopecat.dataset_id": self.schema.dataset_id.encode(),
                b"scopecat.schema": self.schema.model_dump_json(by_alias=True).encode(),
                b"scopecat.metadata": json.dumps(
                    dict(self.metadata), separators=(",", ":"), sort_keys=True
                ).encode(),
            }
        )
        return table.replace_schema_metadata(metadata)

    def to_pandas(self, *, layout: PandasLayout = "points") -> pd.DataFrame:
        """Convert to a point-row or universal long-form pandas DataFrame."""

        pd_module = cast("_PandasModule", _optional_module("pandas"))
        if layout == "points":
            frame = pd_module.DataFrame(self._point_columns())
        elif layout == "long":
            frame = pd_module.DataFrame(self._long_rows())
        else:
            raise ValueError("pandas layout must be 'points' or 'long'")
        frame.attrs["scopecat"] = {
            "dataset_id": self.schema.dataset_id,
            "schema": self.schema.model_dump(mode="json", by_alias=True),
            "metadata": dict(self.metadata),
            "layout": layout,
        }
        return frame

    def _require_scalar_coordinate(self, variable_id: str) -> Variable:
        try:
            variable = self.coords[variable_id]
        except KeyError as error:
            raise KeyError(
                f"measurement dataset has no coordinate {variable_id!r}"
            ) from error
        variable.require_point_scalar()
        return variable

    def _select_indices(self, indices: Sequence[int]) -> Self:
        selected_records = [self._raw.records[index] for index in indices]
        dimensions = [
            dimension.model_copy(update={"size": len(selected_records)})
            if dimension.id == "point"
            else dimension.model_copy(deep=True)
            for dimension in self.schema.dimensions
        ]
        schema = self.schema.model_copy(
            update={"dimensions": dimensions},
            deep=True,
        )
        raw = MeasurementDataset(
            schema=schema,
            records=selected_records,
            metadata=self._raw.metadata.copy(),
        )
        return type(self)(raw, self.entry)

    def _point_columns(self) -> Mapping[str, Sequence[object]]:
        columns: dict[str, Sequence[object]] = {
            "point_index": tuple(record.point_index for record in self.records),
            "logical_point_id": tuple(
                record.logical_point_id for record in self.records
            ),
        }
        for variable in self.variables.values():
            columns[variable.id] = variable.values
            if any(reason is not None for reason in variable.availability):
                columns[_unavailable_reason_name(variable.id)] = variable.availability
        return columns

    def _long_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for record_position, record in enumerate(self.records):
            for variable in self.variables.values():
                value = variable.raw_values[record_position]
                reason = (
                    value.reason if isinstance(value, MeasurementUnavailable) else None
                )
                if isinstance(value, MeasurementArray):
                    flattened = _flatten_native_array(_native_value(value))
                else:
                    flattened = (((), _native_value(value)),)
                for local_index, native in flattened:
                    rows.append(
                        {
                            "point_index": record.point_index,
                            "logical_point_id": record.logical_point_id,
                            "variable": variable.id,
                            "role": variable.role,
                            "unit": variable.unit,
                            "local_index": local_index or None,
                            "value": native,
                            "unavailable_reason": reason,
                        }
                    )
        return rows


def _native_value(value: MeasurementValue) -> NativeValue:
    if isinstance(value, MeasurementUnavailable):
        return None
    if isinstance(value, MeasurementScalar):
        return cast("NativeValue", _native_leaf(value.value))
    return cast("NativeValue", _native_leaf(value.values))


def _native_leaf(value: object) -> object:
    if isinstance(value, ComplexComponents):
        return complex(value.real, value.imag)
    if isinstance(value, tuple):
        selected = cast("tuple[object, ...]", value)
        return tuple(_native_leaf(item) for item in selected)
    return value


def _arrow_value(value: MeasurementValue) -> object:
    if isinstance(value, MeasurementUnavailable):
        return None
    if isinstance(value, MeasurementScalar):
        return _arrow_leaf(value.value)
    return _arrow_leaf(value.values)


def _arrow_leaf(value: object) -> object:
    if isinstance(value, ComplexComponents):
        return {"real": value.real, "imag": value.imag}
    if isinstance(value, tuple):
        selected = cast("tuple[object, ...]", value)
        return [_arrow_leaf(item) for item in selected]
    return value


def _flatten_native_array(
    value: NativeValue,
    prefix: tuple[int, ...] = (),
) -> tuple[tuple[tuple[int, ...], NativeValue], ...]:
    if not isinstance(value, tuple):
        return ((prefix, value),)
    flattened: list[tuple[tuple[int, ...], NativeValue]] = []
    for index, item in enumerate(value):
        flattened.extend(_flatten_native_array(item, (*prefix, index)))
    return tuple(flattened)


def _merge_indexers[T](
    indexers: Mapping[str, T] | None,
    kwargs: Mapping[str, T],
) -> dict[str, T]:
    selected = {} if indexers is None else dict(indexers)
    duplicates = set(selected) & set(kwargs)
    if duplicates:
        raise ValueError(
            "indexers were provided twice: " + ", ".join(sorted(duplicates))
        )
    selected.update(kwargs)
    return selected


def _point_indices(indexer: PointIndexer, *, size: int) -> tuple[int, ...]:
    if isinstance(indexer, slice):
        return tuple(range(size)[indexer])
    if isinstance(indexer, int) and not isinstance(indexer, bool):
        return (_normalize_index(indexer, size=size),)
    if isinstance(indexer, bool):
        raise TypeError("point indexer must not be a single bool")
    selected = tuple(indexer)
    if selected and all(type(value) is bool for value in selected):
        if len(selected) != size:
            raise ValueError(
                f"point boolean indexer has length {len(selected)}; expected {size}"
            )
        return tuple(index for index, keep in enumerate(selected) if keep)
    if any(isinstance(value, bool) for value in selected):
        raise TypeError("point indexer cannot mix bool and integer values")
    return tuple(_normalize_index(int(value), size=size) for value in selected)


def _normalize_index(index: int, *, size: int) -> int:
    selected = index + size if index < 0 else index
    if selected < 0 or selected >= size:
        raise IndexError(f"point index {index} is out of range for {size} points")
    return selected


def _selection_value(value: object, variable: Variable) -> object:
    if isinstance(value, Quantity):
        if variable.unit is None:
            raise ValueError(
                f"coordinate {variable.id!r} is unitless; select it with a raw value"
            )
        return value.to(variable.unit).value
    if isinstance(value, MeasurementScalar):
        native = _native_value(value)
        if value.unit is None:
            return native
        if variable.unit is None:
            raise ValueError(
                f"coordinate {variable.id!r} is unitless; selected value has a unit"
            )
        if not isinstance(native, int | float) or isinstance(native, bool):
            raise TypeError("unit-bearing coordinate selectors must be numeric")
        return Quantity(float(native), value.unit).to(variable.unit).value
    return value


def _selection_tolerance(
    tolerance: float | Quantity | None,
    variable: Variable,
) -> float | None:
    if tolerance is None:
        return None
    selected = _selection_value(tolerance, variable)
    if not isinstance(selected, int | float) or isinstance(selected, bool):
        raise TypeError("nearest-selection tolerance must be numeric")
    numeric = float(selected)
    if numeric < 0:
        raise ValueError("nearest-selection tolerance must not be negative")
    return numeric


def _nearest_indices(
    variable: Variable,
    query: object,
    *,
    tolerance: float | None,
) -> tuple[int, ...]:
    if not isinstance(query, int | float) or isinstance(query, bool):
        raise TypeError("nearest selection requires a numeric coordinate value")
    candidates: list[tuple[int, float]] = []
    for index, value in enumerate(variable.values):
        if not isinstance(value, int | float) or isinstance(value, bool):
            if value is None:
                continue
            raise TypeError("nearest selection requires a numeric coordinate")
        distance = abs(float(value) - float(query))
        candidates.append((index, distance))
    if not candidates:
        return ()
    nearest = min(distance for _, distance in candidates)
    if tolerance is not None and nearest > tolerance:
        return ()
    return tuple(
        index
        for index, distance in candidates
        if math.isclose(distance, nearest, rel_tol=1e-12, abs_tol=0.0)
    )


def _point_identity_matches(
    records: Sequence[MeasurementRecord],
    query: object,
) -> tuple[bool, ...]:
    if isinstance(query, str):
        return tuple(record.logical_point_id == query for record in records)
    if isinstance(query, int) and not isinstance(query, bool):
        return tuple(record.point_index == query for record in records)
    raise TypeError("point selection requires a logical point id or point index")


def _xarray_values(variable: Variable, np_module: _NumpyModule) -> object:
    fixed_shape = tuple(cast("int", extent) for extent in variable.shape)
    dtype = {
        "float64": np_module.float64,
        "int64": np_module.int64,
        "complex128": np_module.complex128,
        "bool": np_module.bool_,
        "string": np_module.object_,
    }[variable.dtype]
    if any(reason is not None for reason in variable.availability):
        if variable.dtype == "float64":
            fill: object = math.nan
        elif variable.dtype == "complex128":
            fill = complex(math.nan, math.nan)
        else:
            fill = None
            dtype = np_module.object_
        local_shape = fixed_shape[1:]
        values = tuple(
            _filled_value(local_shape, fill) if value is None else value
            for value in variable.values
        )
    else:
        values = variable.values
    if not values:
        return np_module.empty(fixed_shape, dtype=dtype)
    return np_module.asarray(values, dtype=dtype)


def _variable_is_ragged(variable: Variable) -> bool:
    return any(extent is None for extent in variable.shape[1:])


def _xarray_ragged_values(
    variable: Variable,
    np_module: _NumpyModule,
    *,
    records: Sequence[MeasurementRecord],
) -> _RaggedXarrayValues:
    """Flatten point-local arrays without constructing a NumPy object array."""

    dtype = {
        "float64": np_module.float64,
        "int64": np_module.int64,
        "complex128": np_module.complex128,
        "bool": np_module.bool_,
        "string": np_module.object_,
    }[variable.dtype]
    fill: object
    if variable.dtype == "float64":
        fill = math.nan
    elif variable.dtype == "complex128":
        fill = complex(math.nan, math.nan)
    elif variable.dtype == "int64":
        fill = 0
    elif variable.dtype == "bool":
        fill = False
    else:
        fill = ""

    flattened_values: list[object] = []
    parent_points: list[int] = []
    row_sizes: list[int] = []
    local_indices: list[list[int]] = [[] for _dimension_id in variable.dims[1:]]
    local_extents: list[list[int]] = [[] for _dimension_id in variable.dims[1:]]
    for record, raw_value in zip(records, variable.raw_values, strict=True):
        if isinstance(raw_value, MeasurementScalar):
            raise ValueError(
                f"ragged variable {variable.id!r} must contain point-local arrays"
            )
        local_shape = tuple(raw_value.shape)
        if len(local_shape) != len(variable.dims) - 1:
            raise ValueError(
                f"ragged variable {variable.id!r} value rank {len(local_shape)} "
                f"does not match {len(variable.dims) - 1} local dimensions"
            )
        for axis, extent in enumerate(local_shape):
            local_extents[axis].append(extent)
        native = (
            _filled_value(local_shape, fill)
            if isinstance(raw_value, MeasurementUnavailable)
            else _native_value(raw_value)
        )
        flattened = _flatten_native_array(cast("NativeValue", native))
        row_sizes.append(len(flattened))
        for local_index, value in flattened:
            flattened_values.append(value)
            parent_points.append(record.point_index)
            for axis, index in enumerate(local_index):
                local_indices[axis].append(index)

    values = (
        np_module.asarray(tuple(flattened_values), dtype=dtype)
        if flattened_values
        else np_module.empty((0,), dtype=dtype)
    )
    return _RaggedXarrayValues(
        values=values,
        parent_points=np_module.asarray(tuple(parent_points), dtype=np_module.int64),
        row_sizes=np_module.asarray(tuple(row_sizes), dtype=np_module.int64),
        local_indices=tuple(
            np_module.asarray(tuple(indices), dtype=np_module.int64)
            for indices in local_indices
        ),
        local_extents=tuple(
            np_module.asarray(tuple(extents), dtype=np_module.int64)
            for extents in local_extents
        ),
    )


def _ragged_observation_dim(variable_id: str) -> str:
    return f"{variable_id}__observation"


def _ragged_parent_name(variable_id: str) -> str:
    return f"{variable_id}__parent_point"


def _ragged_row_size_name(variable_id: str) -> str:
    return f"{variable_id}__row_size"


def _ragged_local_index_name(variable_id: str, dimension_id: str) -> str:
    return f"{variable_id}__{dimension_id}_index"


def _ragged_local_extent_name(variable_id: str, dimension_id: str) -> str:
    return f"{variable_id}__{dimension_id}_extent"


def _filled_value(shape: Sequence[int], fill: object) -> object:
    if not shape:
        return fill
    return tuple(_filled_value(shape[1:], fill) for _ in range(shape[0]))


def _variable_attrs(variable: Variable) -> dict[str, object]:
    attrs: dict[str, object] = {
        "scopecat_role": variable.role,
        "scopecat_dtype": variable.dtype,
        "scopecat_dims": variable.dims,
    }
    if variable.unit is not None:
        attrs["units"] = variable.unit
    if variable.label is not None:
        attrs["long_name"] = variable.label
    if variable.recording_group_id is not None:
        attrs["scopecat_recording_group_id"] = variable.recording_group_id
    attrs.update(variable.metadata)
    return attrs


def _dataset_attrs(dataset: Dataset) -> dict[str, object]:
    return {
        "scopecat_dataset_id": dataset.schema.dataset_id,
        "scopecat_format_version": dataset.schema.format_version,
        **dict(dataset.metadata),
    }


def _unavailable_reason_name(variable_id: str) -> str:
    return f"{variable_id}__unavailable_reason"


def _optional_module(name: str) -> object:
    try:
        return import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        raise ModuleNotFoundError(
            f"{name} is required for this conversion; install scopecat[data]"
        ) from error


__all__ = ["Dataset", "PointMask", "Variable"]
