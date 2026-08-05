# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import assert_type

import numpy as np
import pyarrow as pa
import pytest
import xarray as xr

from scopecat.kernel.quantity import Quantity
from scopecat.measurements.references import RecordRef
from scopecat.measurements.results import Dataset, PointMask, Variable
from scopecat.measurements.value_spec import MeasurementArrayData, MeasurementDType
from scopecat.program.value_types import Quantity as QuantityType
from scopecat.program.values import coordinate
from scopecat.records.artifact import RunContentEntry
from scopecat.records.measurement import (
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementPointCloudPointDomain,
    MeasurementPointDomainAxis,
    MeasurementPointDomainColumn,
    MeasurementProductGridPointDomain,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementValue,
    MeasurementVariable,
)


def test_dataset_exposes_labeled_variables_and_raw_records() -> None:
    dataset = _dataset()

    assert dataset.entry.id == "raw-measurements"
    assert dataset.schema.dataset_id == "raw-measurements"
    assert dataset.dims == {"point": 3, "sample": 2}
    assert tuple(dataset.coords) == ("bias", "frequency")
    assert tuple(dataset.data_vars) == ("temperature", "signal")
    assert tuple(dataset) == ("bias", "frequency", "temperature", "signal")
    assert isinstance(dataset["bias"], Variable)
    assert dataset["bias"].values == (0.0, 1.0, 2.0)
    assert dataset["bias"].shape == (3,)
    assert dataset["frequency"].shape == (3, 2)
    frequency = dataset["frequency"][1]
    signal = dataset["signal"][0]
    assert isinstance(frequency, np.ndarray)
    assert isinstance(signal, np.ndarray)
    np.testing.assert_array_equal(frequency, np.array([12.0, 13.0]))
    np.testing.assert_array_equal(
        signal,
        np.array([complex(1.0, 0.0), complex(0.5, -0.1)]),
    )
    assert not frequency.flags.writeable
    assert not signal.flags.writeable
    with pytest.raises(ValueError, match="cannot set WRITEABLE flag"):
        frequency.flags.writeable = True
    raw_frequency = dataset.records[1].coordinates["frequency"]
    assert isinstance(raw_frequency, MeasurementArray)
    assert frequency is raw_frequency.values
    assert dataset["temperature"].values == (0.05, None, 0.2)
    assert dataset["temperature"].availability == (None, "invalid", None)
    assert dataset.point_indices == (0, 1, 2)
    assert dataset.logical_point_ids == ("logical-0", "logical-1", "logical-2")
    assert dataset.raw.records[2] == dataset.records[2]
    assert dataset.raw.records[2] is dataset.records[2]

    with pytest.raises(KeyError, match="no variable 'missing'"):
        _ = dataset["missing"]


def test_typed_record_lookup_validates_schema_and_narrows_values() -> None:
    dataset = _dataset_with_record_sources()
    bias_ref: RecordRef[float] = RecordRef(
        variable_id="bias",
        dtype="float64",
        unit="V",
        dims=("point",),
        role="coordinate",
        source_value_id="bias",
    )
    signal_ref: RecordRef[MeasurementArrayData] = RecordRef(
        variable_id="signal",
        dtype="complex128",
        unit="ratio",
        dims=("point", "sample"),
        source_product_id="readout/signal",
        recording_group_id="readout",
    )

    bias = dataset[bias_ref]
    signal = dataset[signal_ref]

    assert_type(bias, Variable[float])
    assert_type(signal, Variable[MeasurementArrayData])
    assert bias.require_values() == (0.0, 1.0, 2.0)
    assert bias.require_quantities("mV") == (
        Quantity(0.0, "mV"),
        Quantity(1000.0, "mV"),
        Quantity(2000.0, "mV"),
    )
    assert signal[0] is signal.values[0]
    traces = dataset.traces(signal_ref)
    assert len(traces) == 3
    assert traces[0].coordinate_id == "frequency"
    assert traces[0].observable_id == "signal"


def test_direct_point_handle_narrows_a_dataset_coordinate() -> None:
    dataset = _dataset()
    bias_ref = coordinate("bias", QuantityType(unit="V"))

    bias = dataset[bias_ref]

    assert_type(bias, Variable[float])
    assert bias.require_quantities("mV")[1] == Quantity(1000.0, "mV")

    with pytest.raises(TypeError, match="direct experiment point coordinates"):
        _ = dataset[bias_ref + Quantity(1.0, "V")]


def test_variable_require_helpers_reject_unavailable_rows() -> None:
    dataset = _dataset_with_record_sources()
    temperature_ref: RecordRef[float] = RecordRef(
        variable_id="temperature",
        dtype="float64",
        unit="K",
        dims=("point",),
        source_product_id="thermometer/temperature",
    )
    temperature = dataset[temperature_ref]

    assert temperature.quantities("mK") == (
        Quantity(50.0, "mK"),
        None,
        Quantity(200.0, "mK"),
    )
    with pytest.raises(ValueError, match="row positions: 1"):
        temperature.require_values()
    with pytest.raises(ValueError, match="row positions: 1"):
        temperature.require_quantities()


@pytest.mark.parametrize(
    "ref",
    [
        RecordRef[float](
            variable_id="bias",
            dtype="int64",
            unit="V",
            dims=("point",),
            role="coordinate",
            source_value_id="bias",
        ),
        RecordRef[float](
            variable_id="bias",
            dtype="float64",
            unit="A",
            dims=("point",),
            role="coordinate",
            source_value_id="bias",
        ),
        RecordRef[float](
            variable_id="bias",
            dtype="float64",
            unit="V",
            dims=("point", "sample"),
            role="coordinate",
            source_value_id="bias",
        ),
        RecordRef[float](
            variable_id="bias",
            dtype="float64",
            unit="V",
            dims=("point",),
            source_value_id="bias",
        ),
        RecordRef[float](
            variable_id="bias",
            dtype="float64",
            unit="V",
            dims=("point",),
            role="coordinate",
            source_value_id="other",
        ),
    ],
)
def test_typed_record_lookup_rejects_schema_drift(ref: RecordRef[float]) -> None:
    dataset = _dataset_with_record_sources()

    with pytest.raises(TypeError, match="does not match the dataset schema"):
        _ = dataset[ref]


def test_dataset_supports_point_isel_sel_and_unit_aware_where() -> None:
    dataset = _dataset()

    selected = dataset.isel(point=[2, 0])
    assert [record.point_index for record in selected.records] == [2, 0]
    assert selected.dims["point"] == 2
    assert (
        next(
            dimension.size
            for dimension in selected.schema.dimensions
            if dimension.id == "point"
        )
        == 3
    )
    assert selected["bias"].values == (2.0, 0.0)

    [exact] = dataset.sel(bias=Quantity(1000.0, "mV")).records
    assert exact.point_index == 1
    [logical] = dataset.sel(point="logical-2").records
    assert logical.point_index == 2
    [nearest] = dataset.sel(
        bias=Quantity(1.6, "V"),
        method="nearest",
        tolerance=Quantity(0.5, "V"),
    ).records
    assert nearest.point_index == 2

    mask = (dataset["bias"] >= Quantity(1.0, "V")) & dataset[
        "temperature"
    ].is_available()
    assert isinstance(mask, PointMask)
    filtered = dataset.where(mask)
    assert [record.point_index for record in filtered.records] == [2]
    assert len(dataset.where(lambda current: current["bias"] < 1.5)) == 2
    grouped = dataset.groupby("bias")
    assert tuple(grouped) == (0.0, 1.0, 2.0)
    assert all(type(key) is float for key in grouped)
    assert grouped[1.0].records == (dataset.records[1],)

    with pytest.raises(KeyError, match="not all values found"):
        dataset.sel(
            bias=Quantity(1.6, "V"),
            method="nearest",
            tolerance=Quantity(0.1, "V"),
        )
    with pytest.raises(ValueError, match="point predicates require a scalar"):
        _ = dataset["frequency"] > 10.0
    with pytest.raises(ValueError, match="point predicates require a scalar"):
        dataset.groupby("signal")


@pytest.mark.parametrize(
    ("indexer", "expected_frequency", "expected_size"),
    [
        (1, ((11.0,), (13.0,), (15.0,)), 1),
        (slice(1, None), ((11.0,), (13.0,), (15.0,)), 1),
        ([1, 0], ((11.0, 10.0), (13.0, 12.0), (15.0, 14.0)), 2),
        ([True, False], ((10.0,), (12.0,), (14.0,)), 1),
    ],
)
def test_dataset_isel_selects_fixed_local_dimensions_without_dropping_them(
    indexer: int | slice | list[int] | list[bool],
    expected_frequency: tuple[tuple[float, ...], ...],
    expected_size: int,
) -> None:
    selected = _dataset().isel(sample=indexer)

    assert selected.dims == {"point": 3, "sample": expected_size}
    assert (
        next(
            dimension.size
            for dimension in selected.schema.dimensions
            if dimension.id == "sample"
        )
        == 2
    )
    _assert_array_values(selected["frequency"].values, expected_frequency)
    assert all(
        isinstance(value, np.ndarray) and len(value) == expected_size
        for value in selected["signal"].values
    )


def test_dataset_isel_combines_point_and_fixed_local_selection() -> None:
    selected = _dataset().isel(point=[2, 0], sample=[1])

    assert [record.point_index for record in selected.records] == [2, 0]
    assert selected.dims == {"point": 2, "sample": 1}
    _assert_array_values(selected["frequency"].values, ((15.0,), (11.0,)))


def test_dataset_ecosystem_adapters_preserve_labels_shapes_and_availability() -> None:
    pd = pytest.importorskip("pandas")
    dataset = _dataset()

    xarray_dataset = dataset.to_xarray()
    assert isinstance(xarray_dataset, xr.Dataset)
    assert xarray_dataset is not dataset.xarray
    assert dataset["signal"].xarray.identical(xarray_dataset["signal"])
    assert xarray_dataset.sizes == {"point": 3, "sample": 2}
    assert tuple(xarray_dataset["frequency"].dims) == ("point", "sample")
    assert xarray_dataset["frequency"].attrs["units"] == "Hz"
    assert xarray_dataset["signal"].values[0, 1] == complex(0.5, -0.1)
    assert math.isnan(float(xarray_dataset["temperature"].values[1]))
    assert xarray_dataset["temperature__unavailable_reason"].values[1] == "invalid"
    assert xarray_dataset.attrs["scopecat_entry_id"] == dataset.entry.id
    assert xarray_dataset.attrs["scopecat_content_hash"] == dataset.entry.content_hash
    schema = json.loads(xarray_dataset.attrs["scopecat_schema_json"])
    assert schema["dataset_id"] == dataset.schema.dataset_id
    metadata = json.loads(xarray_dataset.attrs["scopecat_metadata_json"])
    assert metadata["context"]["tags"] == ["xarray", "netcdf"]
    variable_metadata = json.loads(
        xarray_dataset["bias"].attrs["scopecat_metadata_json"]
    )
    assert variable_metadata == {"calibration": {"revision": 2, "source": "smu"}}

    arrow_table = dataset.to_arrow()
    assert isinstance(arrow_table, pa.Table)
    assert arrow_table.num_rows == 3
    assert arrow_table["signal"][0].as_py() == [
        {"imag": 0.0, "real": 1.0},
        {"imag": -0.1, "real": 0.5},
    ]
    assert arrow_table["temperature"][1].as_py() is None
    assert arrow_table.schema.metadata[b"scopecat.dataset_id"] == b"raw-measurements"

    points = dataset.to_pandas()
    assert isinstance(points, pd.DataFrame)
    assert list(points["point_index"]) == [0, 1, 2]
    np.testing.assert_array_equal(
        points.loc[0, "signal"],
        np.array([complex(1.0, 0.0), complex(0.5, -0.1)]),
    )
    assert points.loc[1, "temperature__unavailable_reason"] == "invalid"
    assert points.attrs["scopecat"]["layout"] == "points"

    long = dataset.to_pandas(layout="long")
    signal_rows = long[long["variable"] == "signal"]
    assert len(signal_rows) == 6
    assert signal_rows.iloc[1]["local_index"] == (1,)
    assert signal_rows.iloc[1]["value"] == complex(0.5, -0.1)


def test_empty_arrow_export_keeps_declared_scientific_types() -> None:
    base = _dataset()
    raw = base.raw.model_copy(update={"records": ()})

    table = Dataset(raw, base.entry).to_arrow()
    complex_type = pa.struct(
        [
            pa.field("real", pa.float64(), nullable=False),
            pa.field("imag", pa.float64(), nullable=False),
        ]
    )

    assert table.num_rows == 0
    assert table.schema.field("point_index").type == pa.int64()
    assert table.schema.field("logical_point_id").type == pa.string()
    assert table.schema.field("bias").type == pa.float64()
    assert table.schema.field("frequency").type == pa.list_(pa.float64(), 2)
    assert table.schema.field("temperature").type == pa.float64()
    assert table.schema.field("signal").type == pa.list_(complex_type, 2)


def test_all_unavailable_arrow_column_keeps_declared_nested_type() -> None:
    base = _dataset()
    unavailable = MeasurementUnavailable.create(
        reason="missing",
        dtype="complex128",
        unit="ratio",
        shape=(2,),
        metadata={},
    )
    raw = base.raw.model_copy(
        update={
            "records": tuple(
                _replace_record_values(
                    record,
                    observables={"signal": unavailable},
                )
                for record in base.records
            )
        }
    )

    table = Dataset(raw, base.entry).to_arrow()

    complex_type = pa.struct(
        [
            pa.field("real", pa.float64(), nullable=False),
            pa.field("imag", pa.float64(), nullable=False),
        ]
    )
    assert table.schema.field("signal").type == pa.list_(complex_type, 2)
    assert table["signal"].null_count == 3
    assert table["signal__unavailable_reason"].to_pylist() == [
        "missing",
        "missing",
        "missing",
    ]


def test_product_grid_xarray_layout_restores_axis_dimensions_and_record_order() -> None:
    dataset = _product_grid_dataset()

    points = dataset.to_xarray()
    grid = dataset.to_xarray(layout="grid")

    assert points.sizes == {"point": 6, "sample": 2}
    assert grid.sizes == {"x": 2, "y": 3, "sample": 2}
    assert tuple(grid["x"].dims) == ("x",)
    assert tuple(grid["y"].dims) == ("y",)
    assert grid["x"].attrs["units"] == "V"
    np.testing.assert_array_equal(grid["x"].values, np.array([0.0, 1.0]))
    np.testing.assert_array_equal(grid["y"].values, np.array([10, 20, 30]))
    assert tuple(grid["signal"].dims) == ("x", "y")
    np.testing.assert_array_equal(
        grid["signal"].values,
        np.arange(6, dtype=np.float64).reshape(2, 3),
    )
    assert tuple(grid["trace"].dims) == ("x", "y", "sample")
    np.testing.assert_array_equal(
        grid["point"].values,
        np.arange(6, dtype=np.int64).reshape(2, 3),
    )
    assert grid.attrs["scopecat_xarray_layout"] == "product_grid"


def test_product_grid_xarray_layout_rejects_partial_or_inconsistent_grids() -> None:
    dataset = _product_grid_dataset()

    with pytest.raises(ValueError, match="every product-grid point exactly once"):
        dataset.isel(point=slice(0, 5)).to_xarray(layout="grid")

    raw = dataset.raw.model_copy(
        update={
            "records": (
                _replace_record_values(
                    dataset.records[0],
                    coordinates={
                        "x": MeasurementScalar.create(
                            value=99.0,
                            dtype="float64",
                            unit="V",
                        )
                    },
                ),
                *dataset.records[1:],
            )
        }
    )
    inconsistent = Dataset(raw, dataset.entry)
    with pytest.raises(ValueError, match="does not match its product-grid axis"):
        inconsistent.to_xarray(layout="grid")


def test_dataset_shares_immutable_models_and_detaches_mutable_entry() -> None:
    original = _dataset()
    source = original.raw
    entry = original.entry
    dataset = Dataset(source, entry)

    assert dataset.raw is source
    assert dataset.schema is source.dataset_schema
    assert dataset.records is source.records
    assert dataset["bias"].definition is source.dataset_schema.variables[0]
    assert (
        dataset["temperature"].raw_values[1]
        is source.records[1].observables["temperature"]
    )
    assert dataset.metadata is source.metadata
    assert dataset["bias"].metadata is source.dataset_schema.variables[0].metadata

    entry.id = "mutated-entry"
    assert dataset.entry.id == "raw-measurements"
    detached_entry = dataset.entry
    detached_entry.id = "mutated-output"
    assert dataset.entry.id == "raw-measurements"
    assert dataset.metadata["context"] == {
        "operator": "test",
        "tags": ("xarray", "netcdf"),
    }


def test_xarray_exports_are_independent_copies_of_cached_snapshot() -> None:
    dataset = _dataset()
    first = dataset.xarray

    first["bias"].values[0] = -100.0
    first.attrs["scopecat_dataset_id"] = "mutated"

    refreshed = dataset.to_xarray()
    assert refreshed is not first
    assert float(refreshed["bias"].values[0]) == 0.0
    assert float(first["bias"].values[0]) == -100.0
    assert refreshed.attrs["scopecat_dataset_id"] == "raw-measurements"


def test_xarray_snapshot_round_trips_through_netcdf(tmp_path: Path) -> None:
    dataset = _dataset()
    path = tmp_path / "measurements.nc"

    serializable = dataset.to_xarray().drop_vars("signal")
    serializable.to_netcdf(path)
    restored = xr.load_dataset(path)

    schema = json.loads(restored.attrs["scopecat_schema_json"])
    assert schema["dataset_id"] == dataset.schema.dataset_id
    assert json.loads(restored.attrs["scopecat_metadata_json"])["context"] == {
        "operator": "test",
        "tags": ["xarray", "netcdf"],
    }
    assert (
        json.loads(restored["bias"].attrs["scopecat_metadata_json"])["calibration"][
            "revision"
        ]
        == 2
    )
    assert restored.attrs["scopecat_entry_id"] == dataset.entry.id
    assert float(restored["frequency"].values[0, 1]) == 11.0


def test_ragged_dataset_exports_nested_arrow_lists() -> None:
    dataset = _ragged_dataset()

    arrow = dataset.to_arrow()
    assert isinstance(arrow, pa.Table)
    assert [len(value.as_py()) for value in arrow["signal"]] == [2, 1, 3]


def test_ragged_dataset_exports_indexed_xarray_observations() -> None:
    dataset = _ragged_dataset()

    xarray_dataset = dataset.to_xarray()
    assert isinstance(xarray_dataset, xr.Dataset)
    observation = "readout__sample__observation"
    assert tuple(xarray_dataset["frequency"].dims) == (observation,)
    assert tuple(xarray_dataset["signal"].dims) == (observation,)
    parent = xarray_dataset["readout__sample__parent_point_index"]
    assert list(parent.values) == [10, 10, 20, 40, 40, 40]
    assert parent.attrs["scopecat_parent_identity"] == "durable_point_index"
    assert parent.attrs["source_recording_group_id"] == "readout"
    assert list(xarray_dataset["readout__sample__row_size"].values) == [2, 1, 3]
    assert list(xarray_dataset["readout__sample__sample_extent"].values) == [2, 1, 3]
    assert list(xarray_dataset["readout__sample__sample_index"].values) == [
        0,
        1,
        0,
        0,
        1,
        2,
    ]
    assert (
        xarray_dataset["signal"].attrs["scopecat_ragged_representation"]
        == "indexed_observation"
    )
    assert xarray_dataset["frequency__observation_valid"].values.tolist() == [
        True,
        True,
        True,
        True,
        True,
        True,
    ]
    assert xarray_dataset["signal__observation_valid"].values.tolist() == [
        True,
        True,
        True,
        True,
        True,
        True,
    ]

    native_point_subset = xarray_dataset.isel(point=[1])
    assert native_point_subset.sizes[observation] == 6
    facade_point_subset = dataset.isel(point=[1]).to_xarray()
    assert facade_point_subset.sizes[observation] == 1
    assert list(facade_point_subset["readout__sample__parent_point_index"].values) == [
        20
    ]


def test_ragged_unavailable_unknown_extent_uses_recording_group_layout() -> None:
    dataset = _ragged_dataset()
    unavailable = MeasurementUnavailable.create(
        reason="missing",
        dtype="complex128",
        unit="ratio",
        shape=(None,),
        metadata={},
    )
    raw = dataset.raw.model_copy(
        update={
            "records": (
                dataset.records[0],
                _replace_record_values(
                    dataset.records[1],
                    observables={"signal": unavailable},
                ),
                dataset.records[2],
            )
        }
    )
    dataset = Dataset(raw, dataset.entry)

    arrow = dataset.to_arrow()
    xarray_dataset = dataset.to_xarray()

    assert isinstance(arrow, pa.Table)
    assert arrow["signal"][1].as_py() is None
    assert isinstance(xarray_dataset, xr.Dataset)
    assert list(xarray_dataset["readout__sample__row_size"].values) == [2, 1, 3]
    assert list(xarray_dataset["readout__sample__sample_extent"].values) == [
        2,
        1,
        3,
    ]
    missing_value = complex(xarray_dataset["signal"].values[2])
    assert math.isnan(missing_value.real)
    assert math.isnan(missing_value.imag)
    assert xarray_dataset["signal__unavailable_reason"].values[1] == "missing"
    assert xarray_dataset["signal__observation_valid"].values.tolist() == [
        True,
        True,
        False,
        True,
        True,
        True,
    ]
    reasons = xarray_dataset["signal__observation_unavailable_reason"]
    assert reasons.values[2] == "missing"
    assert reasons.isnull().values.tolist() == [True, True, False, True, True, True]


@pytest.mark.parametrize(
    ("dtype", "missing_fill", "dtype_kind"),
    [
        ("int64", 0, "i"),
        ("bool", False, "b"),
        ("string", "", "U"),
    ],
)
def test_ragged_non_nullable_dtypes_mark_filled_observations_invalid(
    dtype: MeasurementDType,
    missing_fill: object,
    dtype_kind: str,
) -> None:
    base = _ragged_dataset()
    signal = next(
        variable for variable in base.schema.variables if variable.id == "signal"
    )
    schema = base.schema.model_copy(
        update={
            "variables": tuple(
                variable.model_copy(update={"dtype": dtype, "unit": None})
                if variable.id == signal.id
                else variable
                for variable in base.schema.variables
            )
        }
    )
    records: list[MeasurementRecord] = []
    for position, record in enumerate(base.records):
        length = (2, 1, 3)[position]
        if position == 1:
            records.append(
                _replace_record_values(
                    record,
                    observables={
                        "signal": MeasurementUnavailable.create(
                            reason="missing",
                            dtype=dtype,
                            unit=None,
                            shape=(None,),
                            metadata={},
                        )
                    },
                )
            )
            continue
        if dtype == "int64":
            values: tuple[object, ...] = tuple(range(length))
        elif dtype == "bool":
            values = tuple(index % 2 == 0 for index in range(length))
        else:
            values = tuple(f"value-{position}-{index}" for index in range(length))
        records.append(
            _replace_record_values(
                record,
                observables={
                    "signal": MeasurementArray.create(
                        values=values,
                        dtype=dtype,
                        unit=None,
                        metadata={},
                    )
                },
            )
        )

    raw = base.raw.model_copy(
        update={"dataset_schema": schema, "records": tuple(records)}
    )
    xarray_dataset = Dataset(raw, base.entry).to_xarray()

    assert xarray_dataset["signal"].dtype.kind == dtype_kind
    assert xarray_dataset["signal"].values[2] == missing_fill
    assert xarray_dataset["signal__observation_valid"].values.tolist() == [
        True,
        True,
        False,
        True,
        True,
        True,
    ]
    reasons = xarray_dataset["signal__observation_unavailable_reason"]
    assert reasons.values[2] == "missing"
    assert reasons.isnull().values.tolist() == [True, True, False, True, True, True]


def test_ungrouped_ragged_unavailable_preserves_unknown_extent_in_xarray() -> None:
    dataset = _ragged_dataset()
    schema = dataset.schema.model_copy(
        update={
            "variables": tuple(
                variable.model_copy(update={"recording_group_id": None})
                if variable.id == "signal"
                else variable
                for variable in dataset.schema.variables
            )
        }
    )
    unavailable = MeasurementUnavailable.create(
        reason="missing",
        dtype="complex128",
        unit="ratio",
        shape=(None,),
        metadata={},
    )
    raw = dataset.raw.model_copy(
        update={
            "dataset_schema": schema,
            "records": (
                dataset.records[0],
                _replace_record_values(
                    dataset.records[1],
                    observables={"signal": unavailable},
                ),
                dataset.records[2],
            ),
        }
    )
    dataset = Dataset(raw, dataset.entry)

    xarray_dataset = dataset.to_xarray()

    assert isinstance(xarray_dataset, xr.Dataset)
    assert list(xarray_dataset["signal__sample__row_size"].values) == [2, 0, 3]
    assert list(xarray_dataset["signal__sample__sample_extent"].values) == [
        2,
        None,
        3,
    ]
    with pytest.raises(ValueError, match="unknown point-local extent"):
        dataset.isel_ragged(sample=0, variable="signal")


def test_ungrouped_ragged_variables_keep_independent_xarray_observations() -> None:
    dataset = _ragged_dataset()
    schema = dataset.schema.model_copy(
        update={
            "variables": tuple(
                variable.model_copy(update={"recording_group_id": None})
                if variable.id in {"frequency", "signal"}
                else variable
                for variable in dataset.schema.variables
            )
        }
    )
    raw = dataset.raw.model_copy(update={"dataset_schema": schema})
    dataset = Dataset(raw, dataset.entry)

    xarray_dataset = dataset.to_xarray()

    assert isinstance(xarray_dataset, xr.Dataset)
    assert tuple(xarray_dataset["frequency"].dims) == (
        "frequency__sample__observation",
    )
    assert tuple(xarray_dataset["signal"].dims) == ("signal__sample__observation",)


def test_grouped_ragged_xarray_rejects_misaligned_point_local_shapes() -> None:
    dataset = _ragged_dataset()
    misaligned = MeasurementArray.create(
        values=(
            complex(1.0, 0.0),
            complex(1.0, 1.0),
        ),
        dtype="complex128",
        unit="ratio",
    )
    raw = dataset.raw.model_copy(
        update={
            "records": (
                dataset.records[0],
                _replace_record_values(
                    dataset.records[1],
                    observables={"signal": misaligned},
                ),
                dataset.records[2],
            )
        }
    )

    with pytest.raises(
        ValueError,
        match=r"recording group 'readout'.*do not share one point-local",
    ):
        Dataset(raw, dataset.entry)


def test_ragged_sample_selection_applies_independently_per_point_and_group() -> None:
    dataset = _ragged_dataset()

    with pytest.raises(ValueError, match=r"use isel_ragged\(\)"):
        dataset.isel(sample=slice(0, 2))

    selected = dataset.isel_ragged(
        sample=slice(0, 2),
        group="readout",
    )

    assert selected.dims["sample"] is None
    frequency_values = selected["frequency"].values
    signal_values = selected["signal"].values
    assert all(isinstance(value, np.ndarray) for value in frequency_values)
    assert all(isinstance(value, np.ndarray) for value in signal_values)
    assert [
        len(value) for value in frequency_values if isinstance(value, np.ndarray)
    ] == [2, 1, 2]
    assert [len(value) for value in signal_values if isinstance(value, np.ndarray)] == [
        2,
        1,
        2,
    ]
    with pytest.raises(
        IndexError,
        match=r"point_index 20, variable 'frequency'.*sample index 1",
    ):
        dataset.isel_ragged(sample=1, group="readout")
    with pytest.raises(ValueError, match=r"belongs to recording group 'readout'"):
        dataset.isel_ragged(sample=slice(0, 1), variable="signal")


def _assert_array_values(
    actual: tuple[object, ...],
    expected: tuple[tuple[object, ...], ...],
) -> None:
    assert len(actual) == len(expected)
    for value, expected_value in zip(actual, expected, strict=True):
        assert isinstance(value, np.ndarray)
        np.testing.assert_array_equal(value, np.asarray(expected_value))
        assert not value.flags.writeable


def _replace_record_values(
    record: MeasurementRecord,
    *,
    coordinates: Mapping[str, MeasurementValue] | None = None,
    observables: Mapping[str, MeasurementValue] | None = None,
    point_index: int | None = None,
) -> MeasurementRecord:
    updates: dict[str, object] = {}
    if coordinates is not None:
        updates["coordinates"] = {**record.coordinates, **coordinates}
    if observables is not None:
        updates["observables"] = {**record.observables, **observables}
    if point_index is not None:
        updates["point_index"] = point_index
    return record.model_copy(update=updates)


def _ragged_dataset() -> Dataset:
    dataset = _dataset()
    schema = dataset.schema.model_copy(
        update={
            "dimensions": (
                dataset.schema.dimensions[0],
                dataset.schema.dimensions[1].model_copy(update={"size": None}),
            ),
            "variables": tuple(
                variable.model_copy(update={"recording_group_id": "readout"})
                if variable.id == "frequency"
                else variable
                for variable in dataset.schema.variables
            ),
        }
    )
    lengths = (2, 1, 3)
    records = tuple(
        _replace_record_values(
            record,
            point_index=(10, 20, 40)[point],
            coordinates={
                "frequency": MeasurementArray.create(
                    values=tuple(10.0 * point + index for index in range(length)),
                    dtype="float64",
                    unit="Hz",
                )
            },
            observables={
                "signal": MeasurementArray.create(
                    values=tuple(
                        complex(float(point), float(index)) for index in range(length)
                    ),
                    dtype="complex128",
                    unit="ratio",
                )
            },
        )
        for point, (record, length) in enumerate(
            zip(dataset.records, lengths, strict=True)
        )
    )
    raw = dataset.raw.model_copy(update={"dataset_schema": schema, "records": records})
    return Dataset(raw, dataset.entry)


def _product_grid_dataset() -> Dataset:
    x_values = (0.0, 1.0)
    y_values = (10, 20, 30)
    schema = MeasurementDatasetSchema(
        dataset_id="product-grid",
        point_domain=MeasurementProductGridPointDomain(
            axes=[
                MeasurementPointDomainAxis(
                    id="x",
                    size=len(x_values),
                    values=[
                        MeasurementScalar.create(
                            value=value,
                            dtype="float64",
                            unit="V",
                        )
                        for value in x_values
                    ],
                ),
                MeasurementPointDomainAxis(
                    id="y",
                    size=len(y_values),
                    values=[
                        MeasurementScalar.create(value=value, dtype="int64")
                        for value in y_values
                    ],
                ),
            ]
        ),
        dimensions=[
            MeasurementDimension(id="point", kind="point", size=6),
            MeasurementDimension(id="sample", kind="sample", size=2),
        ],
        variables=[
            MeasurementVariable(
                id="x",
                role="coordinate",
                dtype="float64",
                unit="V",
                dims=["point"],
            ),
            MeasurementVariable(
                id="y",
                role="coordinate",
                dtype="int64",
                dims=["point"],
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="float64",
                dims=["point"],
            ),
            MeasurementVariable(
                id="trace",
                role="observable",
                dtype="float64",
                dims=["point", "sample"],
            ),
        ],
        primary_coordinates=["x", "y"],
        primary_observables=["signal", "trace"],
    )
    records = [
        MeasurementRecord(
            run_id="run-product-grid",
            logical_point_id=f"logical-{point_index}",
            point_index=point_index,
            coordinates={
                "x": MeasurementScalar.create(
                    value=x_values[point_index // len(y_values)],
                    dtype="float64",
                    unit="V",
                ),
                "y": MeasurementScalar.create(
                    value=y_values[point_index % len(y_values)],
                    dtype="int64",
                ),
            },
            observables={
                "signal": MeasurementScalar.create(
                    value=float(point_index),
                    dtype="float64",
                ),
                "trace": MeasurementArray.create(
                    values=np.array(
                        [float(point_index), float(point_index) + 0.5],
                        dtype=np.float64,
                    ),
                    dtype="float64",
                ),
            },
        )
        for point_index in range(6)
    ]
    raw = MeasurementDataset(
        dataset_schema=schema,
        records=[records[index] for index in (5, 0, 3, 1, 4, 2)],
    )
    entry = RunContentEntry(
        role="dataset",
        id="product-grid",
        kind="measurement_dataset",
        content_hash="unused-product-grid",
        schema=schema.model_dump(mode="json"),
    )
    return Dataset(raw, entry)


def _dataset() -> Dataset:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
        point_domain=MeasurementPointCloudPointDomain(
            columns=(MeasurementPointDomainColumn(id="bias"),)
        ),
        dimensions=[
            MeasurementDimension(id="point", kind="point", size=3),
            MeasurementDimension(id="sample", kind="frequency", size=2),
        ],
        variables=[
            MeasurementVariable(
                id="bias",
                role="coordinate",
                dtype="float64",
                unit="V",
                dims=["point"],
                label="DC bias",
                metadata={
                    "calibration": {
                        "source": "smu",
                        "revision": 2,
                    }
                },
            ),
            MeasurementVariable(
                id="frequency",
                role="coordinate",
                dtype="float64",
                unit="Hz",
                dims=["point", "sample"],
            ),
            MeasurementVariable(
                id="temperature",
                role="observable",
                dtype="float64",
                unit="K",
                dims=["point"],
            ),
            MeasurementVariable(
                id="signal",
                role="observable",
                dtype="complex128",
                unit="ratio",
                dims=["point", "sample"],
                recording_group_id="readout",
            ),
        ],
        primary_coordinates=["bias", "frequency"],
        primary_observables=["temperature", "signal"],
    )
    records = [
        MeasurementRecord(
            run_id="run-dataset",
            logical_point_id=f"logical-{point_index}",
            point_index=point_index,
            coordinates={
                "bias": MeasurementScalar.create(
                    value=float(point_index), dtype="float64", unit="V"
                ),
                "frequency": MeasurementArray.create(
                    values=(
                        10.0 + 2.0 * point_index,
                        11.0 + 2.0 * point_index,
                    ),
                    dtype="float64",
                    unit="Hz",
                ),
            },
            observables={
                "temperature": (
                    MeasurementUnavailable.create(
                        reason="invalid",
                        dtype="float64",
                        unit="K",
                        shape=(),
                        metadata={"cause": "sensor settling"},
                    )
                    if point_index == 1
                    else MeasurementScalar.create(
                        value=0.05 if point_index == 0 else 0.2,
                        dtype="float64",
                        unit="K",
                    )
                ),
                "signal": MeasurementArray.create(
                    values=(
                        complex(1.0 + point_index, 0.0),
                        complex(0.5 + point_index, -0.1),
                    ),
                    dtype="complex128",
                    unit="ratio",
                ),
            },
        )
        for point_index in range(3)
    ]
    raw = MeasurementDataset(
        dataset_schema=schema,
        records=records,
        metadata={
            "experiment": "facade-test",
            "context": {
                "operator": "test",
                "tags": ["xarray", "netcdf"],
            },
        },
    )
    entry = RunContentEntry(
        role="dataset",
        id="raw-measurements",
        kind="measurement_dataset",
        content_hash="unused",
        schema=schema.model_dump(mode="json"),
    )
    return Dataset(raw, entry)


def _dataset_with_record_sources() -> Dataset:
    dataset = _dataset()
    source_fields = {
        "bias": {"source_value_id": "bias"},
        "frequency": {
            "source_product_id": "readout/frequency",
            "recording_group_id": "readout",
        },
        "temperature": {"source_product_id": "thermometer/temperature"},
        "signal": {"source_product_id": "readout/signal"},
    }
    variables = tuple(
        variable.model_copy(update=source_fields.get(variable.id, {}))
        for variable in dataset.schema.variables
    )
    schema = dataset.schema.model_copy(update={"variables": variables})
    raw = dataset.raw.model_copy(update={"dataset_schema": schema})
    return Dataset(raw, dataset.entry)
