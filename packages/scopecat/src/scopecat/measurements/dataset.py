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
from itertools import product as cartesian_product
from types import MappingProxyType
from typing import TYPE_CHECKING, Literal, Protocol, Self, cast, overload, override

import numpy as np
import pyarrow as pa
import xarray as xr

from scopecat.kernel.quantity import Quantity
from scopecat.measurements.traces import Trace, measurement_traces
from scopecat.records.artifact import RunContentEntry
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
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

type NativeScalar = bool | int | float | complex | str
type NativeValue = NativeScalar | tuple[NativeValue, ...] | None
type GroupKey = NativeScalar | None
type DimensionIndexer = int | slice | Sequence[int] | Sequence[bool]
type PointIndexer = DimensionIndexer
type PointCondition = PointMask | xr.DataArray | Sequence[bool]
type SelectionMethod = Literal["exact", "nearest"]
type PandasLayout = Literal["points", "long"]


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
        self._data = (
            values
            if isinstance(values, xr.DataArray)
            else xr.DataArray(
                np.asarray(values, dtype=np.bool_),
                dims=("point",),
                coords={"point": dataset.xarray.coords["point"]},
            )
        )
        if self._data.dims != ("point",) or self._data.sizes["point"] != len(dataset):
            raise ValueError("point masks must align exactly with the point dimension")
        self._data = self._data.astype(np.bool_)

    @property
    def xarray(self) -> xr.DataArray:
        """Return the native labeled boolean array."""

        return self._data

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
        return MappingProxyType(dict(self._definition.metadata))

    @property
    def definition(self) -> MeasurementVariable:
        """Return the durable schema definition for low-level inspection."""

        return self._definition

    @property
    def xarray(self) -> xr.DataArray:
        """Return this variable's native Xarray view."""

        return self._dataset.xarray[self.id]

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
        source = self._dataset.to_xarray()
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
        source = self._dataset.to_xarray()
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
            comparison(self.xarray, query),
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
    def xarray(self) -> xr.Dataset:
        """Return a fresh labeled snapshot of the current durable dataset."""

        return self.to_xarray()

    @property
    def point_indices(self) -> tuple[int, ...]:
        """Return durable point indices in this view's row order."""

        return tuple(record.point_index for record in self._raw.records)

    @property
    def logical_point_ids(self) -> tuple[str | None, ...]:
        """Return logical point identities in this view's row order."""

        return tuple(record.logical_point_id for record in self._raw.records)

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

        selected_xarray = self.xarray.isel(
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

        selected_xarray = self.xarray
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

        source = self.to_xarray()
        selected = condition(source) if callable(condition) else condition
        if isinstance(selected, PointMask):
            if not selected.belongs_to(self):
                raise ValueError("point mask belongs to a different dataset view")
            mask = selected.xarray
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
            cast("object", self.xarray.groupby(variable_id).groups),
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
            self.raw,
            observable,
            coordinate=coordinate,
            group=group,
        )

    def to_xarray(self) -> xr.Dataset:
        """Build an independent Xarray snapshot with Scopecat provenance."""

        return self._build_xarray()

    def _build_xarray(self) -> xr.Dataset:
        """Materialize a labeled snapshot from the current durable records."""

        coords: dict[str, object] = {
            "point": (
                ("point",),
                np.asarray(
                    tuple(record.point_index for record in self.records),
                    dtype=np.int64,
                ),
                {
                    "long_name": "durable measurement point_index",
                    "scopecat_role": "point_index",
                    "scopecat_identity": "durable_point_index",
                },
            )
        }
        for dimension in self.schema.dimensions:
            if (
                dimension.id != "point"
                and dimension.size is not None
                and dimension.id not in self.variables
            ):
                coords[dimension.id] = (
                    (dimension.id,),
                    np.arange(dimension.size, dtype=np.int64),
                    {
                        "long_name": f"positional index for {dimension.id}",
                        "scopecat_role": "dimension_index",
                    },
                )
        if "logical_point_id" not in self.variables and any(
            record.logical_point_id is not None for record in self.records
        ):
            coords["logical_point_id"] = (
                ("point",),
                np.asarray(
                    tuple(record.logical_point_id for record in self.records),
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
                records=self.records,
            )
            existing_layout = ragged_layouts.get(alignment)
            if existing_layout is None:
                ragged_layouts[alignment] = variable_layout
                continue
            try:
                ragged_layouts[alignment] = _merge_ragged_xarray_layouts(
                    existing_layout,
                    variable_layout,
                    records=self.records,
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
            if any(reason is not None for reason in variable.availability):
                data_vars[_unavailable_reason_name(variable.id)] = (
                    ("point",),
                    np.asarray(
                        variable.availability,
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
        table = pa.table(columns)
        metadata = dict(table.schema.metadata or {})
        metadata.update(
            {
                b"scopecat.dataset_id": self.schema.dataset_id.encode(),
                b"scopecat.schema": self.schema.model_dump_json().encode(),
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
            "schema": self.schema.model_dump(mode="json"),
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
            dataset_schema=schema,
            records=selected_records,
            metadata=self._raw.metadata.copy(),
        )
        return type(self)(raw, self.entry)

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
            for record in self.records
        ]
        dimensions = [
            dimension.model_copy(
                update={"size": len(indices_by_dimension[dimension.id])}
            )
            if dimension.id in indices_by_dimension
            else dimension.model_copy(deep=True)
            for dimension in self.schema.dimensions
        ]
        return self._copy_with(records=records, dimensions=dimensions)

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
            for record in self.records
        ]
        return self._copy_with(
            records=records,
            dimensions=[
                dimension.model_copy(deep=True) for dimension in self.schema.dimensions
            ],
        )

    def _copy_with(
        self,
        *,
        records: Sequence[MeasurementRecord],
        dimensions: Sequence[MeasurementDimension],
    ) -> Self:
        schema = self.schema.model_copy(
            update={"dimensions": list(dimensions)},
            deep=True,
        )
        raw = MeasurementDataset(
            dataset_schema=schema,
            records=list(records),
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
    return cast(
        "NativeValue",
        _native_leaf(cast("object", value.values.tolist())),
    )


def _native_leaf(value: object) -> object:
    if isinstance(value, list | tuple):
        return tuple(_native_leaf(item) for item in value)
    return value


def _arrow_value(value: MeasurementValue) -> object:
    if isinstance(value, MeasurementUnavailable):
        return None
    if isinstance(value, MeasurementScalar):
        return _arrow_leaf(value.value)
    return _arrow_leaf(cast("object", value.values.tolist()))


def _arrow_leaf(value: object) -> object:
    if isinstance(value, complex):
        return {"real": value.real, "imag": value.imag}
    if isinstance(value, list | tuple):
        return [_arrow_leaf(item) for item in value]
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
        deep=True,
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
            metadata=dict(value.metadata),
        )
    selected_values = value.values
    for axis, indices in sorted(indices_by_axis.items()):
        selected_values = np.take(selected_values, indices, axis=axis)
    return MeasurementArray.create(
        dtype=value.dtype,
        unit=value.unit,
        shape=cast("tuple[int, ...]", selected_shape),
        values=selected_values,
        metadata=dict(value.metadata),
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
        record.point_index: position for position, record in enumerate(dataset.records)
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
    dtype = {
        "float64": np.float64,
        "int64": np.int64,
        "complex128": np.complex128,
        "bool": np.bool_,
        "string": np.object_,
    }[variable.dtype]
    if any(reason is not None for reason in variable.availability):
        if variable.dtype == "float64":
            fill: object = math.nan
        elif variable.dtype == "complex128":
            fill = complex(math.nan, math.nan)
        else:
            fill = None
            dtype = np.object_
        local_shape = fixed_shape[1:]
        values = tuple(
            _filled_value(local_shape, fill) if value is None else value
            for value in variable.values
        )
    else:
        values = variable.values
    if not values:
        return np.empty(fixed_shape, dtype=dtype)
    return np.asarray(values, dtype=dtype)


def _variable_is_ragged(variable: Variable) -> bool:
    return any(extent is None for extent in variable.shape[1:])


def _xarray_ragged_values(
    variable: Variable,
    *,
    layout: _RaggedXarrayLayout,
) -> _RaggedXarrayValues:
    """Flatten point-local arrays without constructing a NumPy object array."""

    dtype = {
        "float64": np.float64,
        "int64": np.int64,
        "complex128": np.complex128,
        "bool": np.bool_,
        "string": np.object_,
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
    for row_size, raw_value in zip(
        layout.row_sizes,
        variable.raw_values,
        strict=True,
    ):
        if isinstance(raw_value, MeasurementScalar):
            raise ValueError(
                f"ragged variable {variable.id!r} must contain point-local arrays"
            )
        if isinstance(raw_value, MeasurementUnavailable):
            flattened_values.extend(fill for _index in range(row_size))
        else:
            flattened_values.extend(
                value
                for _local_index, value in _flatten_native_array(
                    _native_value(raw_value)
                )
            )

    values = (
        np.asarray(tuple(flattened_values), dtype=dtype)
        if flattened_values
        else np.empty((0,), dtype=dtype)
    )
    return _RaggedXarrayValues(
        values=values,
        layout=layout,
    )


def _ragged_xarray_layout(
    variable: Variable,
    *,
    records: Sequence[MeasurementRecord],
) -> _RaggedXarrayLayout:
    local_extents: list[list[int | None]] = [[] for _dimension_id in variable.dims[1:]]
    for raw_value in variable.raw_values:
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


def _filled_value(shape: Sequence[int], fill: object) -> object:
    if not shape:
        return fill
    return tuple(_filled_value(shape[1:], fill) for _ in range(shape[0]))


def _variable_attrs(variable: Variable) -> dict[str, object]:
    attrs: dict[str, object] = {
        "scopecat_role": variable.role,
        "scopecat_dtype": variable.dtype,
        "scopecat_dims_json": _stable_json(variable.dims),
        "scopecat_metadata_json": _stable_json(dict(variable.metadata)),
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
        "scopecat_dataset_id": dataset.schema.dataset_id,
        "scopecat_format_version": dataset.schema.format_version,
        "scopecat_entry_id": dataset.entry.id,
        "scopecat_entry_role": dataset.entry.role,
        "scopecat_entry_kind": dataset.entry.kind,
        "scopecat_content_hash": dataset.entry.content_hash,
        "scopecat_schema_json": _stable_json(dataset.schema.model_dump(mode="json")),
        "scopecat_metadata_json": _stable_json(dict(dataset.metadata)),
    }


def _stable_json(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


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
