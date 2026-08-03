# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from __future__ import annotations

import math

import pytest

from scopecat.api.data import Data
from scopecat.kernel.quantity import Quantity
from scopecat.measurements.results import Dataset, PointMask, Variable
from scopecat.records.artifact import RunContentEntry
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementVariable,
)
from scopecat.runs.data import RunMeasurementDatasetResult


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
    assert dataset["frequency"][1] == (12.0, 13.0)
    assert dataset["signal"][0] == (complex(1.0, 0.0), complex(0.5, -0.1))
    assert dataset["temperature"].values == (0.05, None, 0.2)
    assert dataset["temperature"].availability == (None, "invalid", None)
    assert dataset.raw.records[2] is dataset.records[2]

    with pytest.raises(KeyError, match="no variable 'missing'"):
        _ = dataset["missing"]


def test_dataset_supports_point_isel_sel_and_unit_aware_where() -> None:
    dataset = _dataset()

    selected = dataset.isel(point=[2, 0])
    assert [record.point_index for record in selected.records] == [2, 0]
    assert selected.dims["point"] == 2
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
    assert grouped[1.0].records == (dataset.records[1],)

    with pytest.raises(KeyError, match="no measurement points"):
        dataset.sel(
            bias=Quantity(1.6, "V"),
            method="nearest",
            tolerance=Quantity(0.1, "V"),
        )
    with pytest.raises(ValueError, match="point predicates require a scalar"):
        _ = dataset["frequency"] > 10.0
    with pytest.raises(ValueError, match="point predicates require a scalar"):
        dataset.groupby("signal")


def test_data_measurements_returns_the_notebook_dataset_facade() -> None:
    dataset = _dataset()
    run = _DataRunStub(
        RunMeasurementDatasetResult(
            dataset_entry=dataset.entry,
            dataset=dataset.raw,
        )
    )

    selected = Data(run).measurements()  # pyright: ignore[reportArgumentType]

    assert isinstance(selected, Dataset)
    assert selected.entry is dataset.entry
    assert selected.raw is dataset.raw


def test_dataset_ecosystem_adapters_preserve_labels_shapes_and_availability() -> None:
    pd = pytest.importorskip("pandas")
    pa = pytest.importorskip("pyarrow")
    xr = pytest.importorskip("xarray")
    dataset = _dataset()

    xarray_dataset = dataset.to_xarray()
    assert isinstance(xarray_dataset, xr.Dataset)
    assert xarray_dataset.sizes == {"point": 3, "sample": 2}
    assert tuple(xarray_dataset["frequency"].dims) == ("point", "sample")
    assert xarray_dataset["frequency"].attrs["units"] == "Hz"
    assert xarray_dataset["signal"].values[0, 1] == complex(0.5, -0.1)
    assert math.isnan(float(xarray_dataset["temperature"].values[1]))
    assert xarray_dataset["temperature__unavailable_reason"].values[1] == "invalid"

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
    assert points.loc[0, "signal"] == (complex(1.0, 0.0), complex(0.5, -0.1))
    assert points.loc[1, "temperature__unavailable_reason"] == "invalid"
    assert points.attrs["scopecat"]["layout"] == "points"

    long = dataset.to_pandas(layout="long")
    signal_rows = long[long["variable"] == "signal"]
    assert len(signal_rows) == 6
    assert signal_rows.iloc[1]["local_index"] == (1,)
    assert signal_rows.iloc[1]["value"] == complex(0.5, -0.1)


def test_ragged_dataset_exports_nested_arrow_lists() -> None:
    pa = pytest.importorskip("pyarrow")
    dataset = _ragged_dataset()

    arrow = dataset.to_arrow()
    assert isinstance(arrow, pa.Table)
    assert [len(value.as_py()) for value in arrow["signal"]] == [2, 1, 3]


def test_ragged_dataset_exports_indexed_xarray_observations() -> None:
    xr = pytest.importorskip("xarray")
    dataset = _ragged_dataset()

    xarray_dataset = dataset.to_xarray()
    assert isinstance(xarray_dataset, xr.Dataset)
    assert tuple(xarray_dataset["signal"].dims) == ("signal__observation",)
    assert list(xarray_dataset["signal__parent_point"].values) == [0, 0, 1, 2, 2, 2]
    assert list(xarray_dataset["signal__row_size"].values) == [2, 1, 3]
    assert list(xarray_dataset["signal__sample_extent"].values) == [2, 1, 3]
    assert list(xarray_dataset["signal__sample_index"].values) == [0, 1, 0, 0, 1, 2]
    assert (
        xarray_dataset["signal"].attrs["scopecat_ragged_representation"]
        == "indexed_observation"
    )


def _ragged_dataset() -> Dataset:
    dataset = _dataset()
    dataset.raw.dataset_schema.dimensions[1].size = None
    lengths = (2, 1, 3)
    for point, length in enumerate(lengths):
        dataset.raw.records[point].coordinates["frequency"] = MeasurementArray.create(
            shape=(length,),
            values=tuple(10.0 * point + index for index in range(length)),
            dtype="float64",
            unit="Hz",
        )
        dataset.raw.records[point].observables["signal"] = MeasurementArray.create(
            shape=(length,),
            values=tuple(
                ComplexComponents(real=float(point), imag=float(index))
                for index in range(length)
            ),
            dtype="complex128",
            unit="ratio",
        )
    return Dataset(dataset.raw, dataset.entry)


class _DataRunStub:
    def __init__(self, result: RunMeasurementDatasetResult) -> None:
        self._result = result

    def measurements(
        self,
        *,
        selector: str = "raw-measurements",
    ) -> RunMeasurementDatasetResult:
        assert selector == "raw-measurements"
        return self._result


def _dataset() -> Dataset:
    schema = MeasurementDatasetSchema(
        dataset_id="raw-measurements",
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
                    shape=(2,),
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
                    shape=(2,),
                    values=(
                        ComplexComponents(real=1.0 + point_index, imag=0.0),
                        ComplexComponents(real=0.5 + point_index, imag=-0.1),
                    ),
                    dtype="complex128",
                    unit="ratio",
                ),
            },
        )
        for point_index in range(3)
    ]
    raw = MeasurementDataset(
        schema=schema,
        records=records,
        metadata={"experiment": "facade-test"},
    )
    entry = RunContentEntry(
        role="dataset",
        id="raw-measurements",
        kind="measurement_dataset",
        content_hash="unused",
        schema=schema.model_dump(mode="json"),
    )
    return Dataset(raw, entry)
