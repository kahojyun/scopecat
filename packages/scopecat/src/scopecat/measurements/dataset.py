# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false
# pyright: reportUnnecessaryTypeIgnoreComment=false
# pyright: reportPrivateUsage=false
"""Notebook-facing labeled views over durable measurement records."""

from __future__ import annotations

import json
import math
import operator
from collections.abc import Callable, Iterator, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from importlib import import_module
from itertools import product as cartesian_product
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast, overload, override

import numpy as np
import pyarrow as pa
import xarray as xr

from scopecat.kernel.frozen import thaw_json_value
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.arrow_values import measurement_values_to_arrow_array
from scopecat.measurements.traces import Trace, measurement_traces
from scopecat.records.artifact import RunContentEntry
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementArrayData,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDType,
    MeasurementProductGridPointDomain,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
    MeasurementValue,
    MeasurementVariable,
)

if TYPE_CHECKING:
    import pandas as pd  # pyright: ignore[reportMissingImports]

type NativeScalar = bool | int | float | complex | str
type NativeValue = NativeScalar | MeasurementArrayData | None
type GroupKey = NativeScalar | None
type DimensionIndexer = int | slice | Sequence[int] | Sequence[bool]
type PointIndexer = DimensionIndexer
type PointCondition = PointMask | xr.DataArray | Sequence[bool]
type SelectionMethod = Literal["exact", "nearest"]
type PandasLayout = Literal["points", "long"]
type XarrayLayout = Literal["points", "grid"]


class _PandasFrameFactory(Protocol):
    def __call__(self, data: object = ...) -> pd.DataFrame: ...


class _PandasModule(Protocol):
    DataFrame: _PandasFrameFactory


@dataclass(frozen=True, slots=True)
class _RaggedXarrayLayout:
    parent_point_indices: tuple[int, ...]
    row_sizes: tuple[int, ...]
    local_indices: tuple[tuple[int, ...], ...]
    local_extents: tuple[tuple[int | None, ...], ...]


@dataclass(frozen=True, slots=True)
class _RaggedXarrayValues:
    values: object
    valid: object
    unavailable_reasons: object
    layout: _RaggedXarrayLayout


@dataclass(frozen=True, slots=True)
class _RaggedAlignmentKey:
    recording_group_id: str | None
    variable_id: str | None
    local_dimensions: tuple[str, ...]


class PointMask(Sequence[bool]):
    """A point-aligned Xarray boolean selection tied to one dataset view."""

    __slots__ = ("_data", "_dataset")

    def __init__(
        self,
        dataset: Dataset,
        values: xr.DataArray | Sequence[bool],
    ) -> None:
        self._dataset = dataset
        data = (
            values
            if isinstance(values, xr.DataArray)
            else xr.DataArray(
                np.asarray(values, dtype=np.bool_),
                dims=("point",),
                coords={"point": dataset._xarray.coords["point"]},
            )
        )
        if data.dims != ("point",) or data.sizes["point"] != len(dataset):
            raise ValueError("point masks must align exactly with the point dimension")
        self._data = data.astype(np.bool_).copy(deep=True)

    @property
    def xarray(self) -> xr.DataArray:
        """Return an independent copy of the labeled boolean array."""

        return self._data.copy(deep=True)

    @overload
    def __getitem__(self, index: int) -> bool: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[bool, ...]: ...

    @override
    def __getitem__(self, index: int | slice) -> bool | tuple[bool, ...]:
        return self._values[index]

    @override
    def __len__(self) -> int:
        return self._data.sizes["point"]

    @override
    def __iter__(self) -> Iterator[bool]:
        return iter(self._values)

    def __and__(self, other: PointMask) -> PointMask:
        self._require_same_dataset(other)
        return PointMask(self._dataset, self._data & other._data)

    def __or__(self, other: PointMask) -> PointMask:
        self._require_same_dataset(other)
        return PointMask(self._dataset, self._data | other._data)

    def __invert__(self) -> PointMask:
        return PointMask(self._dataset, ~self._data)

    def __bool__(self) -> bool:
        raise TypeError("a PointMask has no single truth value; pass it to where()")

    @override
    def __repr__(self) -> str:
        return f"PointMask({self._values!r})"

    @property
    def _values(self) -> tuple[bool, ...]:
        return tuple(cast("list[bool]", self._data.values.tolist()))

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
        return self._definition.metadata

    @property
    def definition(self) -> MeasurementVariable:
        """Return the deeply immutable durable schema definition."""

        return self._definition

    @property
    def xarray(self) -> xr.DataArray:
        """Return an independent Xarray copy of this variable."""

        return self._dataset._xarray[self.id].copy(deep=True)

    @property
    def raw_values(self) -> tuple[MeasurementValue, ...]:
        """Return the deeply immutable durable values."""

        return self._raw_values

    @property
    def _raw_values(self) -> tuple[MeasurementValue, ...]:
        field = "coordinates" if self.role == "coordinate" else "observables"
        return tuple(
            getattr(record, field)[self.id] for record in self._dataset._records
        )

    @property
    def values(self) -> tuple[NativeValue, ...]:
        """Return native scalars or read-only ndarrays; unavailable points are None."""

        return tuple(_native_value(value) for value in self._raw_values)

    @property
    def availability(
        self,
    ) -> tuple[MeasurementUnavailableReason | None, ...]:
        return tuple(
            value.reason if isinstance(value, MeasurementUnavailable) else None
            for value in self._raw_values
        )

    def is_available(self) -> PointMask:
        source = self._dataset._xarray
        reason_name = _unavailable_reason_name(self.id)
        reason = source.get(reason_name)
        if reason is None:
            return PointMask(
                self._dataset,
                xr.ones_like(source.coords["point"], dtype=np.bool_),
            )
        return PointMask(self._dataset, reason.isnull())

    def is_unavailable(
        self,
        reason: MeasurementUnavailableReason | None = None,
    ) -> PointMask:
        source = self._dataset._xarray
        reason_name = _unavailable_reason_name(self.id)
        availability = source.get(reason_name)
        if availability is None:
            selected = xr.zeros_like(
                source.coords["point"],
                dtype=np.bool_,
            )
        elif reason is None:
            selected = availability.notnull()
        else:
            selected = availability == reason
        return PointMask(self._dataset, selected)

    def __getitem__(self, index: int | slice) -> NativeValue | tuple[NativeValue, ...]:
        return self.values[index]

    def __lt__(self, other: object) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], object]", operator.lt)
        )

    def __le__(self, other: object) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], object]", operator.le)
        )

    @override
    def __eq__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, other: object
    ) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], object]", operator.eq)
        )

    @override
    def __ne__(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, other: object
    ) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], object]", operator.ne)
        )

    def __gt__(self, other: object) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], object]", operator.gt)
        )

    def __ge__(self, other: object) -> PointMask:
        return self._compare(
            other, cast("Callable[[object, object], object]", operator.ge)
        )

    @override
    def __repr__(self) -> str:
        unit = "" if self.unit is None else f", unit={self.unit!r}"
        return f"Variable(id={self.id!r}, role={self.role!r}, dims={self.dims!r}{unit})"

    def _compare(
        self,
        other: object,
        comparison: Callable[[object, object], object],
    ) -> PointMask:
        self.require_point_scalar()
        query = _selection_value(other, self)
        selected = cast(
            "xr.DataArray",
            comparison(self._dataset._xarray[self.id], query),
        )
        return PointMask(self._dataset, selected.fillna(False))

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
    _entry: RunContentEntry
    _view_dimensions: Mapping[str, int | None] = field(init=False, repr=False)
    _variables: Mapping[str, Variable] = field(init=False, repr=False)
    _xarray: xr.Dataset = field(init=False, repr=False)

    def __init__(
        self,
        raw: MeasurementDataset,
        entry: RunContentEntry,
        *,
        view_dimensions: Mapping[str, int | None] | None = None,
    ) -> None:
        object.__setattr__(self, "_raw", raw)
        object.__setattr__(self, "_entry", entry.model_copy(deep=True))
        dimensions = {
            dimension.id: dimension.size
            for dimension in self._raw.dataset_schema.dimensions
        }
        dimensions["point"] = len(self._raw.records)
        if view_dimensions is not None:
            unknown = set(view_dimensions) - set(dimensions)
            if unknown:
                raise ValueError(
                    "dataset view references unknown dimensions: "
                    + ", ".join(sorted(unknown))
                )
            dimensions.update(view_dimensions)
            dimensions["point"] = len(self._raw.records)
        object.__setattr__(
            self,
            "_view_dimensions",
            MappingProxyType(dimensions),
        )
        self.__post_init__()

    def __post_init__(self) -> None:
        variables = {
            definition.id: Variable(self, definition)
            for definition in self._raw.dataset_schema.variables
        }
        object.__setattr__(self, "_variables", MappingProxyType(variables))
        object.__setattr__(self, "_xarray", self._build_xarray())

    @property
    def entry(self) -> RunContentEntry:
        """Return detached run-entry provenance for this snapshot."""

        return self._entry.model_copy(deep=True)

    @property
    def raw(self) -> MeasurementDataset:
        """Return the deeply immutable durable snapshot."""

        return self._raw

    @property
    def schema(self) -> MeasurementDatasetSchema:
        return self._schema

    @property
    def records(self) -> tuple[MeasurementRecord, ...]:
        return self._records

    @property
    def metadata(self) -> Mapping[str, object]:
        return self._raw.metadata

    @property
    def xarray(self) -> xr.Dataset:
        """Return an independent copy of the cached Xarray snapshot."""

        return self._xarray.copy(deep=True)

    @property
    def _schema(self) -> MeasurementDatasetSchema:
        return self._raw.dataset_schema

    @property
    def _records(self) -> tuple[MeasurementRecord, ...]:
        return cast("tuple[MeasurementRecord, ...]", self._raw.records)

    @property
    def point_indices(self) -> tuple[int, ...]:
        """Return durable point indices in this view's row order."""

        return tuple(record.point_index for record in self._records)

    @property
    def logical_point_ids(self) -> tuple[str | None, ...]:
        """Return logical point identities in this view's row order."""

        return tuple(record.logical_point_id for record in self._records)

    @property
    def dims(self) -> Mapping[str, int | None]:
        """Return dimensions of this view, independent of the planned schema."""

        return self._view_dimensions

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
        return len(self._records)

    def __iter__(self) -> Iterator[str]:
        return iter(self.variables)

    @override
    def __repr__(self) -> str:
        coordinates = ", ".join(self.coords)
        observables = ", ".join(self.data_vars)
        return (
            f"Dataset(id={self._schema.dataset_id!r}, points={len(self)}, "
            f"coords=[{coordinates}], data_vars=[{observables}])"
        )

    def isel(
        self,
        indexers: Mapping[str, PointIndexer] | None = None,
        /,
        **indexer_kwargs: PointIndexer,
    ) -> Self:
        """Select fixed dimensions by position while preserving every dimension.

        Integer indexers select a one-element extent rather than dropping the
        dimension. Variable-length dimensions require :meth:`isel_ragged`,
        whose indexer is applied independently inside each point-local value.
        """

        selected = _merge_indexers(indexers, indexer_kwargs)
        if not selected:
            raise ValueError("isel requires at least one dimension indexer")
        unknown = sorted(set(selected) - set(self.dims))
        if unknown:
            raise ValueError(
                "isel references unknown dimensions: " + ", ".join(unknown)
            )
        ragged = sorted(
            dimension_id for dimension_id in selected if self.dims[dimension_id] is None
        )
        if ragged:
            raise ValueError(
                "isel cannot apply one global indexer to variable-length "
                f"dimensions {', '.join(ragged)}; use isel_ragged() with a "
                "recording group or variable"
            )

        selected_xarray = self._xarray.isel(
            {
                dimension_id: _preserving_xarray_indexer(indexer)
                for dimension_id, indexer in selected.items()
            }
        )
        point_indexer = selected.get("point")
        result = (
            self
            if point_indexer is None
            else self._select_indices(_point_positions(self, selected_xarray))
        )
        local_indices = {
            dimension_id: _selected_dimension_positions(
                selected_xarray,
                dimension_id,
            )
            for dimension_id in selected
            if dimension_id != "point"
        }
        return result._select_fixed_local_dimensions(local_indices)

    def isel_ragged(
        self,
        indexers: Mapping[str, DimensionIndexer] | None = None,
        /,
        *,
        group: str | None = None,
        variable: str | None = None,
        **indexer_kwargs: DimensionIndexer,
    ) -> Self:
        """Select samples independently inside each point-local ragged value.

        Use ``group=`` to keep a recorded coordinate/observable bundle aligned,
        or ``variable=`` for one ungrouped variable. Integer indexers preserve a
        one-element local dimension, matching :meth:`isel`.
        """

        selected = _merge_indexers(indexers, indexer_kwargs)
        if not selected:
            raise ValueError("isel_ragged requires at least one dimension indexer")
        if (group is None) == (variable is None):
            raise ValueError("isel_ragged requires exactly one of group= or variable=")
        unknown = sorted(set(selected) - set(self.dims))
        if unknown:
            raise ValueError(
                "isel_ragged references unknown dimensions: " + ", ".join(unknown)
            )
        fixed = sorted(
            dimension_id
            for dimension_id in selected
            if self.dims[dimension_id] is not None
        )
        if fixed:
            raise ValueError(
                "isel_ragged only accepts variable-length dimensions; use isel() "
                f"for {', '.join(fixed)}"
            )

        if variable is not None:
            try:
                selected_variable = self[variable]
            except KeyError as error:
                raise ValueError(
                    f"unknown measurement variable {variable!r}"
                ) from error
            if selected_variable.recording_group_id is not None:
                raise ValueError(
                    f"variable {variable!r} belongs to recording group "
                    f"{selected_variable.recording_group_id!r}; select that group "
                    "to keep its variables aligned"
                )
            target_variables = (selected_variable,)
        else:
            target_variables = tuple(
                candidate
                for candidate in self.variables.values()
                if candidate.recording_group_id == group
            )
            if not target_variables:
                raise ValueError(
                    f"measurement dataset has no recording group {group!r}"
                )
        target_ids = {
            candidate.id
            for candidate in target_variables
            if set(selected) & set(candidate.dims[1:])
        }
        unused = sorted(
            dimension_id
            for dimension_id in selected
            if not any(dimension_id in candidate.dims for candidate in target_variables)
        )
        if unused:
            target = (
                f"variable {variable!r}" if variable is not None else f"group {group!r}"
            )
            raise ValueError(
                f"isel_ragged dimensions {', '.join(unused)} are not used by {target}"
            )
        return self._select_ragged_local_dimensions(
            selected,
            target_variable_ids=target_ids,
        )

    def sel(
        self,
        indexers: Mapping[str, object] | None = None,
        /,
        *,
        method: SelectionMethod | None = None,
        tolerance: float | Quantity | None = None,
        **indexer_kwargs: object,
    ) -> Self:
        """Select point rows through Xarray's coordinate indexes."""

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
        elif tolerance is not None:
            raise ValueError("sel tolerance is only valid with method='nearest'")

        selected_xarray = self._xarray
        for variable_id, query in selected.items():
            if variable_id == "point" and isinstance(query, str):
                coordinate_id = "logical_point_id"
                normalized = query
                selected_tolerance = None
            elif variable_id == "point":
                coordinate_id = "point"
                normalized = query
                selected_tolerance = None
            else:
                variable = self._require_scalar_coordinate(variable_id)
                coordinate_id = variable_id
                normalized = _selection_value(query, variable)
                selected_tolerance = _selection_tolerance(tolerance, variable)
            if coordinate_id not in selected_xarray.xindexes:
                selected_xarray = selected_xarray.set_xindex(coordinate_id)
            selected_xarray = selected_xarray.sel(
                {coordinate_id: normalized},
                method=None if selected_method == "exact" else selected_method,
                tolerance=selected_tolerance,
            )
            if "point" not in selected_xarray.dims:
                selected_xarray = selected_xarray.expand_dims("point")
        return self._select_indices(_point_positions(self, selected_xarray))

    def where(
        self,
        condition: PointCondition | Callable[[xr.Dataset], xr.DataArray],
    ) -> Self:
        """Keep point rows selected by an Xarray-aligned boolean condition."""

        if callable(condition):
            source = self.xarray
            selected = condition(source)
        else:
            source = self._xarray
            selected = condition
        if isinstance(selected, PointMask):
            if not selected.belongs_to(self):
                raise ValueError("point mask belongs to a different dataset view")
            mask = selected._data
        elif isinstance(selected, xr.DataArray):
            mask = selected
        else:
            mask = xr.DataArray(
                np.asarray(selected, dtype=np.bool_),
                dims=("point",),
                coords={"point": source.coords["point"]},
            )
        if mask.dims != ("point",) or mask.sizes["point"] != len(self):
            raise ValueError(
                "where condition must align exactly with the point dimension"
            )
        selected_xarray = source.where(mask.astype(np.bool_), drop=True)
        return self._select_indices(
            _point_positions(self, selected_xarray),
        )

    def groupby(self, variable_id: str) -> Mapping[GroupKey, Self]:
        """Group point rows with Xarray's labeled grouping semantics."""

        variable = self[variable_id]
        variable.require_point_scalar()
        groups = cast(
            "Mapping[object, Sequence[int] | slice]",
            cast("object", self._xarray.groupby(variable_id).groups),
        )
        return MappingProxyType(
            {
                _native_group_key(key): self._select_indices(
                    _group_positions(group_positions, size=len(self))
                )
                for key, group_positions in groups.items()
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
            self._raw,
            observable,
            coordinate=coordinate,
            group=group,
        )

    def to_xarray(self, *, layout: XarrayLayout = "points") -> xr.Dataset:
        """Return a point-row or complete product-grid Xarray snapshot."""

        if layout == "points":
            return self._xarray.copy(deep=True)
        if layout == "grid":
            return self._product_grid_xarray()
        raise ValueError("Xarray layout must be 'points' or 'grid'")

    def _product_grid_xarray(self) -> xr.Dataset:
        domain = self._schema.point_domain
        if not isinstance(domain, MeasurementProductGridPointDomain):
            raise ValueError("grid Xarray layout requires a product-grid point domain")

        axis_ids = tuple(axis.id for axis in domain.axes)
        local_dimensions = set(self.dims) - {"point"}
        conflicts = sorted(set(axis_ids) & ({"point"} | local_dimensions))
        if conflicts:
            raise ValueError(
                "product-grid axes conflict with measurement dimensions: "
                + ", ".join(conflicts)
            )

        axis_shape = tuple(axis.size for axis in domain.axes)
        cardinality = math.prod(axis_shape)
        point_indices = self.point_indices
        if len(self) != cardinality or sorted(point_indices) != list(
            range(cardinality)
        ):
            raise ValueError(
                "grid Xarray layout requires every product-grid point exactly once"
            )
        ordered_positions = tuple(
            position
            for position, _point_index in sorted(
                enumerate(point_indices),
                key=operator.itemgetter(1),
            )
        )
        source = self._xarray.isel(point=list(ordered_positions))

        axis_coordinates: dict[str, object] = {}
        for axis_index, axis in enumerate(domain.axes):
            variable = self.variables.get(axis.id)
            if variable is not None:
                if variable.role != "coordinate" or variable.dims != ("point",):
                    raise ValueError(
                        f"product-grid axis {axis.id!r} conflicts with a non-scalar "
                        "measurement variable"
                    )
                expected = _product_axis_flat_values(
                    domain,
                    axis_index=axis_index,
                    variable=variable,
                )
                if not _array_values_equal(source[axis.id].values, expected):
                    raise ValueError(
                        f"measurement coordinate {axis.id!r} does not match its "
                        "product-grid axis"
                    )
                attrs = {
                    **_variable_attrs(variable),
                    "scopecat_product_grid_axis": True,
                }
            else:
                if axis.id in source.variables:
                    raise ValueError(
                        f"product-grid axis {axis.id!r} conflicts with an Xarray "
                        "variable"
                    )
                attrs = _product_axis_attrs(axis.values)
            axis_coordinates[axis.id] = (
                (axis.id,),
                _product_axis_values(axis.values, variable=variable),
                attrs,
            )

        coords: dict[str, object] = dict(axis_coordinates)
        data_vars: dict[str, object] = {}
        for raw_name, array in source.coords.items():
            name = cast("str", raw_name)
            if name in axis_coordinates:
                continue
            coords[name] = _reshape_point_data_array(
                array,
                axis_ids=axis_ids,
                axis_shape=axis_shape,
            )
        for raw_name, array in source.data_vars.items():
            name = cast("str", raw_name)
            if name in axis_coordinates:
                raise ValueError(
                    f"product-grid axis {name!r} conflicts with an Xarray data variable"
                )
            data_vars[name] = _reshape_point_data_array(
                array,
                axis_ids=axis_ids,
                axis_shape=axis_shape,
            )

        return xr.Dataset(
            data_vars=data_vars,
            coords=coords,
            attrs={
                **deepcopy(dict(source.attrs)),
                "scopecat_xarray_layout": "product_grid",
            },
        )

    def _build_xarray(self) -> xr.Dataset:
        """Materialize the private canonical Xarray snapshot once."""

        coords: dict[str, object] = {
            "point": (
                ("point",),
                np.asarray(
                    tuple(record.point_index for record in self._records),
                    dtype=np.int64,
                ),
                {
                    "long_name": "durable measurement point_index",
                    "scopecat_role": "point_index",
                    "scopecat_identity": "durable_point_index",
                },
            )
        }
        for dimension in self._schema.dimensions:
            view_size = self.dims[dimension.id]
            if (
                dimension.id != "point"
                and view_size is not None
                and dimension.id not in self.variables
            ):
                coords[dimension.id] = (
                    (dimension.id,),
                    np.arange(view_size, dtype=np.int64),
                    {
                        "long_name": f"positional index for {dimension.id}",
                        "scopecat_role": "dimension_index",
                    },
                )
        if "logical_point_id" not in self.variables and any(
            record.logical_point_id is not None for record in self._records
        ):
            coords["logical_point_id"] = (
                ("point",),
                np.asarray(
                    tuple(record.logical_point_id for record in self._records),
                    dtype=np.object_,
                ),
                {"long_name": "Scopecat logical point id"},
            )
        data_vars: dict[str, object] = {}
        ragged_layouts: dict[_RaggedAlignmentKey, _RaggedXarrayLayout] = {}
        for variable in self.variables.values():
            if not _variable_is_ragged(variable):
                continue
            alignment = _ragged_alignment_key(variable)
            variable_layout = _ragged_xarray_layout(
                variable,
                records=self._records,
            )
            existing_layout = ragged_layouts.get(alignment)
            if existing_layout is None:
                ragged_layouts[alignment] = variable_layout
                continue
            try:
                ragged_layouts[alignment] = _merge_ragged_xarray_layouts(
                    existing_layout,
                    variable_layout,
                    records=self._records,
                )
            except ValueError as error:
                owner = (
                    f"recording group {alignment.recording_group_id!r}"
                    if alignment.recording_group_id is not None
                    else f"variable {variable.id!r}"
                )
                raise ValueError(
                    f"ragged values in {owner} do not share one point-local "
                    f"{alignment.local_dimensions!r} layout"
                ) from error
        emitted_ragged_layouts: set[_RaggedAlignmentKey] = set()
        for variable in self.variables.values():
            target = coords if variable.role == "coordinate" else data_vars
            availability = variable.availability
            if _variable_is_ragged(variable):
                alignment = _ragged_alignment_key(variable)
                alignment_id = _ragged_alignment_id(alignment)
                observation_dim = _ragged_observation_dim(alignment_id)
                ragged = _xarray_ragged_values(
                    variable,
                    layout=ragged_layouts[alignment],
                )
                target[variable.id] = (
                    (observation_dim,),
                    ragged.values,
                    {
                        **_variable_attrs(variable),
                        "scopecat_ragged_representation": "indexed_observation",
                        "scopecat_ragged_alignment": alignment_id,
                    },
                )
                data_vars[_ragged_valid_name(variable.id)] = (
                    (observation_dim,),
                    ragged.valid,
                    {
                        "long_name": f"valid observations for {variable.id}",
                        "scopecat_role": "ragged_observation_validity",
                        "source_variable": variable.id,
                    },
                )
                if any(reason is not None for reason in availability):
                    data_vars[_ragged_unavailable_reason_name(variable.id)] = (
                        (observation_dim,),
                        ragged.unavailable_reasons,
                        {
                            "long_name": (
                                "unavailable reason for each observation of "
                                f"{variable.id}"
                            ),
                            "scopecat_role": ("ragged_observation_unavailable_reason"),
                            "source_variable": variable.id,
                        },
                    )
                if alignment not in emitted_ragged_layouts:
                    emitted_ragged_layouts.add(alignment)
                    source_attrs = _ragged_alignment_attrs(alignment)
                    coords[_ragged_parent_point_index_name(alignment_id)] = (
                        (observation_dim,),
                        np.asarray(
                            ragged.layout.parent_point_indices,
                            dtype=np.int64,
                        ),
                        {
                            "long_name": (
                                "durable measurement point_index owning each "
                                f"{alignment_id} observation"
                            ),
                            "scopecat_role": "ragged_parent_point_index",
                            "scopecat_parent_identity": "durable_point_index",
                            **source_attrs,
                        },
                    )
                    coords[_ragged_row_size_name(alignment_id)] = (
                        ("point",),
                        np.asarray(
                            ragged.layout.row_sizes,
                            dtype=np.int64,
                        ),
                        {
                            "long_name": (
                                f"point-local observation count for {alignment_id}"
                            ),
                            "scopecat_role": "ragged_row_size",
                            **source_attrs,
                        },
                    )
                    for local_axis, dimension_id in enumerate(variable.dims[1:]):
                        coords[_ragged_local_index_name(alignment_id, dimension_id)] = (
                            (observation_dim,),
                            np.asarray(
                                ragged.layout.local_indices[local_axis],
                                dtype=np.int64,
                            ),
                            {
                                "long_name": (
                                    f"point-local {dimension_id} index for "
                                    f"{alignment_id}"
                                ),
                                "scopecat_role": "ragged_local_index",
                                "source_dimension": dimension_id,
                                **source_attrs,
                            },
                        )
                        coords[
                            _ragged_local_extent_name(alignment_id, dimension_id)
                        ] = (
                            ("point",),
                            np.asarray(
                                ragged.layout.local_extents[local_axis],
                                dtype=(
                                    np.object_
                                    if any(
                                        extent is None
                                        for extent in ragged.layout.local_extents[
                                            local_axis
                                        ]
                                    )
                                    else np.int64
                                ),
                            ),
                            {
                                "long_name": (
                                    f"point-local {dimension_id} extent for "
                                    f"{alignment_id}"
                                ),
                                "scopecat_role": "ragged_local_extent",
                                "source_dimension": dimension_id,
                                **source_attrs,
                            },
                        )
            else:
                target[variable.id] = (
                    variable.dims,
                    _xarray_values(variable),
                    _variable_attrs(variable),
                )
            if any(reason is not None for reason in availability):
                data_vars[_unavailable_reason_name(variable.id)] = (
                    ("point",),
                    np.asarray(
                        availability,
                        dtype=np.object_,
                    ),
                    {
                        "long_name": f"unavailable reason for {variable.id}",
                        "scopecat_role": "availability",
                        "source_variable": variable.id,
                    },
                )
        return xr.Dataset(
            data_vars=data_vars,
            coords=coords,
            attrs=_dataset_attrs(self),
        )

    def to_arrow(self) -> pa.Table:
        """Convert to a point-row Arrow table with nested point-local arrays."""

        columns: dict[str, pa.Array] = {
            "point_index": pa.array(
                (record.point_index for record in self._records),
                type=pa.int64(),
            ),
            "logical_point_id": pa.array(
                (record.logical_point_id for record in self._records),
                type=pa.string(),
            ),
        }
        for variable in self.variables.values():
            columns[variable.id] = measurement_values_to_arrow_array(
                variable._raw_values,
                dtype=variable.dtype,
                shape=variable.shape[1:],
            )
            if any(reason is not None for reason in variable.availability):
                columns[_unavailable_reason_name(variable.id)] = pa.array(
                    variable.availability,
                    type=pa.string(),
                )
        table = pa.table(columns)
        metadata = dict(table.schema.metadata or {})
        metadata.update(
            {
                b"scopecat.dataset_id": self._schema.dataset_id.encode(),
                b"scopecat.schema": self._schema.model_dump_json().encode(),
                b"scopecat.metadata": _stable_json(self.metadata).encode(),
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
            "dataset_id": self._schema.dataset_id,
            "schema": self._schema.model_dump(mode="json"),
            "metadata": thaw_json_value(self.metadata),
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
        raw = MeasurementDataset(
            dataset_schema=self._schema,
            records=tuple(selected_records),
            metadata=self._raw.metadata,
        )
        return type(self)(
            raw,
            self._entry,
            view_dimensions={**self.dims, "point": len(selected_records)},
        )

    def _select_fixed_local_dimensions(
        self,
        indices_by_dimension: Mapping[str, tuple[int, ...]],
    ) -> Self:
        if not indices_by_dimension:
            return self
        variables = {variable.id: variable for variable in self.variables.values()}
        records = [
            _slice_record_local_values(
                record,
                variables=variables,
                target_variable_ids=set(variables),
                indices_for=lambda _record, variable, _value: {
                    dimension_id: indices
                    for dimension_id, indices in indices_by_dimension.items()
                    if dimension_id in variable.dims[1:]
                },
            )
            for record in self._records
        ]
        dimensions = {
            **self.dims,
            **{
                dimension_id: len(indices)
                for dimension_id, indices in indices_by_dimension.items()
            },
        }
        return self._copy_with(records=records, view_dimensions=dimensions)

    def _select_ragged_local_dimensions(
        self,
        indexers_by_dimension: Mapping[str, DimensionIndexer],
        *,
        target_variable_ids: set[str],
    ) -> Self:
        variables = {variable.id: variable for variable in self.variables.values()}

        def indices_for(
            record: MeasurementRecord,
            variable: Variable,
            value: MeasurementValue,
        ) -> Mapping[str, tuple[int, ...]]:
            local_shape = _measurement_local_shape(value)
            selected: dict[str, tuple[int, ...]] = {}
            for local_axis, dimension_id in enumerate(variable.dims[1:]):
                indexer = indexers_by_dimension.get(dimension_id)
                if indexer is None:
                    continue
                try:
                    extent = local_shape[local_axis]
                    if extent is None:
                        raise ValueError(
                            f"cannot index dimension {dimension_id!r}: unavailable "
                            "value has an unknown point-local extent"
                        )
                    selected[dimension_id] = _dimension_indices(
                        indexer,
                        size=extent,
                        label=dimension_id,
                    )
                except (IndexError, TypeError, ValueError) as error:
                    raise type(error)(
                        f"point_index {record.point_index}, variable "
                        f"{variable.id!r}: {error}"
                    ) from error
            return selected

        records = [
            _slice_record_local_values(
                record,
                variables=variables,
                target_variable_ids=target_variable_ids,
                indices_for=indices_for,
            )
            for record in self._records
        ]
        return self._copy_with(
            records=records,
            view_dimensions=self.dims,
        )

    def _copy_with(
        self,
        *,
        records: Sequence[MeasurementRecord],
        view_dimensions: Mapping[str, int | None],
    ) -> Self:
        raw = MeasurementDataset(
            dataset_schema=self._schema,
            records=tuple(records),
            metadata=self._raw.metadata,
        )
        return type(self)(raw, self._entry, view_dimensions=view_dimensions)

    def _point_columns(self) -> Mapping[str, Sequence[object]]:
        columns: dict[str, Sequence[object]] = {
            "point_index": tuple(record.point_index for record in self._records),
            "logical_point_id": tuple(
                record.logical_point_id for record in self._records
            ),
        }
        for variable in self.variables.values():
            columns[variable.id] = variable.values
            if any(reason is not None for reason in variable.availability):
                columns[_unavailable_reason_name(variable.id)] = variable.availability
        return columns

    def _long_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for record_position, record in enumerate(self._records):
            for variable in self.variables.values():
                value = variable._raw_values[record_position]
                reason = (
                    value.reason if isinstance(value, MeasurementUnavailable) else None
                )
                if isinstance(value, MeasurementArray):
                    flattened = _flatten_native_array(value.values)
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
    return value.values


def _native_leaf(value: object) -> object:
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, list | tuple):
        return tuple(_native_leaf(item) for item in value)
    return value


def _reshape_point_data_array(
    array: xr.DataArray,
    *,
    axis_ids: tuple[str, ...],
    axis_shape: tuple[int, ...],
) -> object:
    attrs = deepcopy(dict(array.attrs))
    if "point" not in array.dims:
        return (array.dims, np.array(array.values, copy=True), attrs)

    remaining_dims = tuple(dim for dim in array.dims if dim != "point")
    ordered = array.transpose("point", *remaining_dims)
    remaining_shape = tuple(ordered.sizes[dim] for dim in remaining_dims)
    values = np.asarray(ordered.values).reshape((*axis_shape, *remaining_shape))
    return ((*axis_ids, *remaining_dims), values, attrs)


def _product_axis_values(
    values: Sequence[MeasurementScalar | None],
    *,
    variable: Variable | None,
) -> np.ndarray:
    native = tuple(
        None if value is None else _native_leaf(value.value) for value in values
    )
    if variable is None:
        return np.asarray(native, dtype=np.object_ if not native else None)
    return np.asarray(
        native,
        dtype=_xarray_dtype(
            variable.dtype,
            nullable=any(value is None for value in values),
        ),
    )


def _product_axis_flat_values(
    domain: MeasurementProductGridPointDomain,
    *,
    axis_index: int,
    variable: Variable,
) -> np.ndarray:
    axis = domain.axes[axis_index]
    values = _product_axis_values(axis.values, variable=variable)
    repeated = np.repeat(
        values,
        math.prod(item.size for item in domain.axes[axis_index + 1 :]),
    )
    return np.tile(
        repeated,
        math.prod(item.size for item in domain.axes[:axis_index]),
    )


def _product_axis_attrs(
    values: Sequence[MeasurementScalar | None],
) -> dict[str, object]:
    attrs: dict[str, object] = {
        "scopecat_role": "point_domain_axis",
        "scopecat_product_grid_axis": True,
    }
    available = tuple(value for value in values if value is not None)
    units = {value.unit for value in available}
    dtypes = {value.dtype for value in available}
    if len(units) == 1:
        [unit] = units
        if unit is not None:
            attrs["units"] = unit
    if len(dtypes) == 1:
        [dtype] = dtypes
        attrs["scopecat_dtype"] = dtype
    return attrs


def _array_values_equal(left: np.ndarray, right: np.ndarray) -> bool:
    try:
        return bool(np.array_equal(left, right, equal_nan=True))
    except TypeError:
        return bool(np.array_equal(left, right))


def _flatten_native_array(
    value: MeasurementArrayData,
) -> tuple[tuple[tuple[int, ...], NativeValue], ...]:
    return tuple(
        (tuple(index), cast("NativeValue", _native_leaf(item)))
        for index, item in np.ndenumerate(value)
    )


def _slice_record_local_values(
    record: MeasurementRecord,
    *,
    variables: Mapping[str, Variable],
    target_variable_ids: set[str],
    indices_for: Callable[
        [MeasurementRecord, Variable, MeasurementValue],
        Mapping[str, tuple[int, ...]],
    ],
) -> MeasurementRecord:
    coordinates = dict(record.coordinates)
    observables = dict(record.observables)
    for variable_id, variable in variables.items():
        if variable_id not in target_variable_ids:
            continue
        values = coordinates if variable.role == "coordinate" else observables
        value = values[variable_id]
        selected = indices_for(record, variable, value)
        if selected:
            values[variable_id] = _slice_measurement_value(
                value,
                local_dimensions=variable.dims[1:],
                indices_by_dimension=selected,
            )
    return record.model_copy(
        update={
            "coordinates": coordinates,
            "observables": observables,
        },
    )


def _measurement_local_shape(value: MeasurementValue) -> tuple[int | None, ...]:
    if isinstance(value, MeasurementScalar):
        return ()
    return tuple(value.shape)


def _slice_measurement_value(
    value: MeasurementValue,
    *,
    local_dimensions: Sequence[str],
    indices_by_dimension: Mapping[str, tuple[int, ...]],
) -> MeasurementValue:
    if isinstance(value, MeasurementScalar):
        raise ValueError("cannot apply a local dimension indexer to a scalar value")
    shape = tuple(value.shape)
    indices_by_axis = {
        local_dimensions.index(dimension_id): indices
        for dimension_id, indices in indices_by_dimension.items()
    }
    selected_shape = tuple(
        len(indices_by_axis[axis]) if axis in indices_by_axis else extent
        for axis, extent in enumerate(shape)
    )
    if isinstance(value, MeasurementUnavailable):
        return MeasurementUnavailable.create(
            reason=value.reason,
            dtype=value.dtype,
            unit=value.unit,
            shape=selected_shape,
            metadata=value.metadata,
        )
    selected_values = value.values
    for axis, indices in sorted(indices_by_axis.items()):
        selected_values = np.take(selected_values, indices, axis=axis)
    return MeasurementArray.create(
        dtype=value.dtype,
        unit=value.unit,
        values=selected_values,
        metadata=value.metadata,
    )


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


def _preserving_xarray_indexer(indexer: DimensionIndexer) -> object:
    """Use Xarray indexing while retaining durable dataset dimensions."""

    if isinstance(indexer, bool):
        raise TypeError("dimension indexers must not be a single bool")
    if isinstance(indexer, int):
        return [indexer]
    if isinstance(indexer, slice):
        return indexer
    selected = tuple(indexer)
    if not selected:
        return np.empty((0,), dtype=np.int64)
    return list(selected)


def _point_positions(dataset: Dataset, selected: xr.Dataset) -> tuple[int, ...]:
    positions = {
        record.point_index: position for position, record in enumerate(dataset._records)
    }
    point_indices = cast(
        "list[int]",
        selected.coords["point"].values.tolist(),
    )
    return tuple(positions[point_index] for point_index in point_indices)


def _selected_dimension_positions(
    selected: xr.Dataset,
    dimension_id: str,
) -> tuple[int, ...]:
    return tuple(
        cast(
            "list[int]",
            selected.coords[dimension_id].values.tolist(),
        )
    )


def _group_positions(
    positions: Sequence[int] | slice,
    *,
    size: int,
) -> tuple[int, ...]:
    if isinstance(positions, slice):
        return tuple(range(size)[positions])
    return tuple(positions)


def _native_group_key(value: object) -> GroupKey:
    if isinstance(value, np.generic):
        value = value.item()
    return cast("GroupKey", value)


def _dimension_indices(
    indexer: DimensionIndexer,
    *,
    size: int,
    label: str,
) -> tuple[int, ...]:
    if isinstance(indexer, slice):
        return tuple(range(size)[indexer])
    if isinstance(indexer, int) and not isinstance(indexer, bool):
        return (_normalize_index(indexer, size=size, label=label),)
    if isinstance(indexer, bool):
        raise TypeError(f"{label} indexer must not be a single bool")
    selected = tuple(indexer)
    if selected and all(type(value) is bool for value in selected):
        if len(selected) != size:
            raise ValueError(
                f"{label} boolean indexer has length {len(selected)}; expected {size}"
            )
        return tuple(index for index, keep in enumerate(selected) if keep)
    if any(isinstance(value, bool) for value in selected):
        raise TypeError(f"{label} indexer cannot mix bool and integer values")
    return tuple(
        _normalize_index(int(value), size=size, label=label) for value in selected
    )


def _normalize_index(index: int, *, size: int, label: str) -> int:
    selected = index + size if index < 0 else index
    if selected < 0 or selected >= size:
        raise IndexError(f"{label} index {index} is out of range for extent {size}")
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


def _xarray_values(variable: Variable) -> object:
    fixed_shape = tuple(cast("int", extent) for extent in variable.shape)
    raw_values = variable._raw_values
    has_unavailable = any(
        isinstance(value, MeasurementUnavailable) for value in raw_values
    )
    dtype = _xarray_dtype(variable.dtype, nullable=has_unavailable)
    if not raw_values:
        return np.empty(fixed_shape, dtype=dtype)

    local_shape = fixed_shape[1:]
    if not local_shape:
        values: list[object] = []
        for value in raw_values:
            if isinstance(value, MeasurementUnavailable):
                values.append(_xarray_nullable_fill(variable.dtype))
            else:
                values.append(cast("MeasurementScalar", value).value)
        return np.asarray(values, dtype=dtype)

    arrays: list[np.ndarray] = []
    for value in raw_values:
        if isinstance(value, MeasurementUnavailable):
            arrays.append(
                np.full(
                    local_shape,
                    _xarray_nullable_fill(variable.dtype),
                    dtype=dtype,
                )
            )
        else:
            arrays.append(cast("MeasurementArray", value).values)
    return np.stack(arrays, axis=0).astype(dtype, copy=False)


def _variable_is_ragged(variable: Variable) -> bool:
    return any(extent is None for extent in variable.shape[1:])


def _xarray_ragged_values(
    variable: Variable,
    *,
    layout: _RaggedXarrayLayout,
) -> _RaggedXarrayValues:
    """Flatten point-local arrays without constructing a NumPy object array."""

    raw_values = variable._raw_values
    dtype = _xarray_dtype(variable.dtype, nullable=False)
    chunks: list[np.ndarray[tuple[int], np.dtype[np.generic]]] = []
    valid_chunks: list[np.ndarray[tuple[int], np.dtype[np.bool_]]] = []
    reason_chunks: list[np.ndarray[tuple[int], np.dtype[np.object_]]] = []
    for row_size, raw_value in zip(
        layout.row_sizes,
        raw_values,
        strict=True,
    ):
        if isinstance(raw_value, MeasurementScalar):
            raise ValueError(
                f"ragged variable {variable.id!r} must contain point-local arrays"
            )
        if isinstance(raw_value, MeasurementUnavailable):
            chunks.append(np.full(row_size, _xarray_fill(variable.dtype), dtype=dtype))
            valid_chunks.append(np.zeros(row_size, dtype=np.bool_))
            reason_chunks.append(np.full(row_size, raw_value.reason, dtype=np.object_))
        else:
            flattened = raw_value.values.reshape(-1)
            if flattened.size != row_size:
                raise ValueError(
                    f"ragged variable {variable.id!r} contributes "
                    f"{flattened.size} values to a {row_size}-observation row"
                )
            chunks.append(flattened)
            valid_chunks.append(np.ones(row_size, dtype=np.bool_))
            reason_chunks.append(np.full(row_size, None, dtype=np.object_))

    values = _concatenate_or_empty(chunks, dtype=dtype)
    valid = _concatenate_or_empty(valid_chunks, dtype=np.dtype(np.bool_))
    unavailable_reasons = _concatenate_or_empty(
        reason_chunks,
        dtype=np.dtype(np.object_),
    )
    return _RaggedXarrayValues(
        values=values,
        valid=valid,
        unavailable_reasons=unavailable_reasons,
        layout=layout,
    )


def _xarray_dtype(
    dtype: MeasurementDType,
    *,
    nullable: bool,
) -> np.dtype[np.generic]:
    if nullable and dtype in {"int64", "bool", "string"}:
        return np.dtype(np.object_)
    return {
        "float64": np.dtype(np.float64),
        "int64": np.dtype(np.int64),
        "complex128": np.dtype(np.complex128),
        "bool": np.dtype(np.bool_),
        "string": np.dtype(np.str_),
    }[dtype]


def _xarray_fill(dtype: MeasurementDType) -> object:
    if dtype == "float64":
        return math.nan
    if dtype == "complex128":
        return complex(math.nan, math.nan)
    if dtype == "int64":
        return 0
    if dtype == "bool":
        return False
    return ""


def _xarray_nullable_fill(dtype: MeasurementDType) -> object:
    if dtype in {"int64", "bool", "string"}:
        return None
    return _xarray_fill(dtype)


def _concatenate_or_empty(
    chunks: Sequence[np.ndarray],
    *,
    dtype: np.dtype[np.generic],
) -> np.ndarray:
    if not chunks:
        return np.empty((0,), dtype=dtype)
    return np.concatenate(chunks).astype(dtype, copy=False)


def _ragged_xarray_layout(
    variable: Variable,
    *,
    records: Sequence[MeasurementRecord],
) -> _RaggedXarrayLayout:
    local_extents: list[list[int | None]] = [[] for _dimension_id in variable.dims[1:]]
    for raw_value in variable._raw_values:
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
    return _ragged_layout_from_extents(
        tuple(tuple(extents) for extents in local_extents),
        records=records,
    )


def _merge_ragged_xarray_layouts(
    left: _RaggedXarrayLayout,
    right: _RaggedXarrayLayout,
    *,
    records: Sequence[MeasurementRecord],
) -> _RaggedXarrayLayout:
    merged_axes: list[tuple[int | None, ...]] = []
    for left_axis, right_axis in zip(
        left.local_extents,
        right.local_extents,
        strict=True,
    ):
        merged_axis: list[int | None] = []
        for left_extent, right_extent in zip(left_axis, right_axis, strict=True):
            if (
                left_extent is not None
                and right_extent is not None
                and left_extent != right_extent
            ):
                raise ValueError("ragged point-local extents differ")
            merged_axis.append(left_extent if left_extent is not None else right_extent)
        merged_axes.append(tuple(merged_axis))
    return _ragged_layout_from_extents(tuple(merged_axes), records=records)


def _ragged_layout_from_extents(
    local_extents: tuple[tuple[int | None, ...], ...],
    *,
    records: Sequence[MeasurementRecord],
) -> _RaggedXarrayLayout:
    parent_points: list[int] = []
    row_sizes: list[int] = []
    local_indices: list[list[int]] = [[] for _axis in local_extents]
    for point_position, record in enumerate(records):
        local_shape = tuple(
            axis_extents[point_position] for axis_extents in local_extents
        )
        if any(extent is None for extent in local_shape):
            row_sizes.append(0)
            continue
        concrete_shape = cast("tuple[int, ...]", local_shape)
        indices = tuple(
            cartesian_product(*(range(extent) for extent in concrete_shape))
        )
        row_sizes.append(len(indices))
        for local_index in indices:
            parent_points.append(record.point_index)
            for axis, index in enumerate(local_index):
                local_indices[axis].append(index)
    return _RaggedXarrayLayout(
        parent_point_indices=tuple(parent_points),
        row_sizes=tuple(row_sizes),
        local_indices=tuple(tuple(indices) for indices in local_indices),
        local_extents=local_extents,
    )


def _ragged_alignment_key(variable: Variable) -> _RaggedAlignmentKey:
    group = variable.recording_group_id
    return _RaggedAlignmentKey(
        recording_group_id=group,
        variable_id=variable.id if group is None else None,
        local_dimensions=variable.dims[1:],
    )


def _ragged_alignment_id(alignment: _RaggedAlignmentKey) -> str:
    owner = alignment.recording_group_id or cast("str", alignment.variable_id)
    return "__".join((owner, *alignment.local_dimensions))


def _ragged_alignment_attrs(
    alignment: _RaggedAlignmentKey,
) -> dict[str, object]:
    attrs: dict[str, object] = {
        "source_dimensions": alignment.local_dimensions,
    }
    if alignment.recording_group_id is not None:
        attrs["source_recording_group_id"] = alignment.recording_group_id
    else:
        attrs["source_variable"] = cast("str", alignment.variable_id)
    return attrs


def _ragged_observation_dim(alignment_id: str) -> str:
    return f"{alignment_id}__observation"


def _ragged_parent_point_index_name(alignment_id: str) -> str:
    return f"{alignment_id}__parent_point_index"


def _ragged_row_size_name(variable_id: str) -> str:
    return f"{variable_id}__row_size"


def _ragged_local_index_name(variable_id: str, dimension_id: str) -> str:
    return f"{variable_id}__{dimension_id}_index"


def _ragged_local_extent_name(variable_id: str, dimension_id: str) -> str:
    return f"{variable_id}__{dimension_id}_extent"


def _ragged_valid_name(variable_id: str) -> str:
    return f"{variable_id}__observation_valid"


def _ragged_unavailable_reason_name(variable_id: str) -> str:
    return f"{variable_id}__observation_unavailable_reason"


def _variable_attrs(variable: Variable) -> dict[str, object]:
    attrs: dict[str, object] = {
        "scopecat_role": variable.role,
        "scopecat_dtype": variable.dtype,
        "scopecat_dims_json": _stable_json(variable.dims),
        "scopecat_metadata_json": _stable_json(variable.metadata),
    }
    if variable.unit is not None:
        attrs["units"] = variable.unit
    if variable.label is not None:
        attrs["long_name"] = variable.label
    if variable.recording_group_id is not None:
        attrs["scopecat_recording_group_id"] = variable.recording_group_id
    return attrs


def _dataset_attrs(dataset: Dataset) -> dict[str, object]:
    return {
        "scopecat_dataset_id": dataset._schema.dataset_id,
        "scopecat_format_version": dataset._schema.format_version,
        "scopecat_entry_id": dataset._entry.id,
        "scopecat_entry_role": dataset._entry.role,
        "scopecat_entry_kind": dataset._entry.kind,
        "scopecat_content_hash": dataset._entry.content_hash,
        "scopecat_schema_json": _stable_json(dataset._schema.model_dump(mode="json")),
        "scopecat_metadata_json": _stable_json(dataset._raw.metadata),
    }


def _stable_json(value: object) -> str:
    return json.dumps(
        thaw_json_value(value),
        separators=(",", ":"),
        sort_keys=True,
    )


def _unavailable_reason_name(variable_id: str) -> str:
    return f"{variable_id}__unavailable_reason"


def _optional_module(name: str) -> object:
    try:
        return import_module(name)
    except ModuleNotFoundError as error:
        if error.name != name:
            raise
        raise ModuleNotFoundError(
            f"{name} is required for this conversion; install scopecat[pandas]"
        ) from error


__all__ = ["Dataset", "PointMask", "Variable"]
