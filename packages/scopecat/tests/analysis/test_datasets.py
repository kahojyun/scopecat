# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from __future__ import annotations

import numpy as np
import pyarrow as pa
import pytest
import xarray as xr

import scopecat as sc
from scopecat.analysis.datasets import DERIVED_DATASET_CODEC, DerivedDataset


def test_derived_dataset_round_trips_exact_arrow_and_semantic_schema() -> None:
    source = pa.table(
        {
            "bias": pa.array([-1.0, 0.0, 1.0], type=pa.float64()),
            "score": pa.array([0.2, 0.8, 0.3], type=pa.float64()),
        }
    )

    dataset = sc.derived_dataset(
        source,
        coordinates=("bias",),
        units={"bias": "V", "score": "ratio"},
        labels={"bias": "DC bias", "score": "Fit score"},
    )
    restored = DerivedDataset.from_json_value(dataset.to_json_value())

    assert dataset.schema.schema_id == "scopecat.derived-dataset.v2"
    assert dataset.schema.fields[0].role == "coordinate"
    assert dataset.schema.fields[0].unit == "V"
    assert dataset.table.schema.field("score").metadata[b"units"] == b"ratio"
    assert restored.schema == dataset.schema
    assert restored.table.equals(dataset.table, check_metadata=True)

    presentation = restored.to_analysis_table()
    assert [column.id for column in presentation.columns] == ["bias", "score"]
    assert presentation.columns[0].label == "DC bias"
    assert presentation.rows[1].cells == [0.0, 0.8]


def test_derived_dataset_accepts_familiar_dataframe_and_xarray_results() -> None:
    pd = pytest.importorskip("pandas")
    pl = pytest.importorskip("polars")

    pandas_dataset = sc.derived_dataset(
        pd.DataFrame({"x": [1, 2], "y": [3.0, 4.0]}),
        coordinates=("x",),
    )
    polars_dataset = sc.derived_dataset(
        pl.DataFrame({"x": [1, 2], "y": [3.0, 4.0]}),
        coordinates=("x",),
    )
    xarray_dataset = sc.derived_dataset(
        xr.Dataset(
            data_vars={"y": (("x",), [3.0, 4.0], {"quality": "fit"})},
            coords={"x": ("x", [1, 2], {"long_name": "Bias index"})},
            attrs={"model": "linear"},
        ),
        units={"y": "ratio"},
    )

    assert pandas_dataset.table.to_pylist() == [
        {"x": 1, "y": 3.0},
        {"x": 2, "y": 4.0},
    ]
    assert polars_dataset.table.to_pylist() == pandas_dataset.table.to_pylist()
    assert xarray_dataset.table.to_pylist() == pandas_dataset.table.to_pylist()
    restored_xarray = xarray_dataset.to_xarray()
    assert restored_xarray.sizes == {"x": 2}
    assert restored_xarray.attrs == {"model": "linear"}
    assert restored_xarray["x"].attrs == {"long_name": "Bias index"}
    assert restored_xarray["y"].attrs == {
        "quality": "fit",
        "units": "ratio",
    }
    assert restored_xarray.identical(
        xr.Dataset(
            data_vars={
                "y": (
                    ("x",),
                    [3.0, 4.0],
                    {"quality": "fit", "units": "ratio"},
                )
            },
            coords={"x": ("x", [1, 2], {"long_name": "Bias index"})},
            attrs={"model": "linear"},
        )
    )
    assert isinstance(pandas_dataset.to_pandas(), pd.DataFrame)
    assert isinstance(polars_dataset.to_polars(), pl.DataFrame)


def test_derived_dataset_retains_only_meaningful_pandas_indexes() -> None:
    pd = pytest.importorskip("pandas")

    implicit = sc.derived_dataset(pd.DataFrame({"score": [0.2, 0.8]}))
    indexed = sc.derived_dataset(
        pd.DataFrame(
            {"score": [0.2, 0.8]},
            index=pd.Index([4.0, 5.0], name="bias"),
        )
    )
    dropped = sc.derived_dataset(
        pd.DataFrame(
            {"score": [0.2, 0.8]},
            index=pd.Index([4.0, 5.0], name="bias"),
        ),
        index="drop",
    )

    assert implicit.table.column_names == ["score"]
    assert indexed.table.column_names == ["bias", "score"]
    assert indexed.schema.fields[0].role == "coordinate"
    assert dropped.table.column_names == ["score"]


def test_derived_dataset_rejects_ambiguous_pandas_column_names() -> None:
    pd = pytest.importorskip("pandas")

    with pytest.raises(ValueError, match="index names conflict"):
        sc.derived_dataset(
            pd.DataFrame(
                {"bias": [0.2, 0.8]},
                index=pd.Index([4.0, 5.0], name="bias"),
            )
        )
    with pytest.raises(TypeError, match="columns must be strings"):
        sc.derived_dataset(pd.DataFrame({1: [0.2, 0.8]}), index="drop")


def test_derived_dataset_inherits_and_overrides_pandas_semantics() -> None:
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame({"bias": [0.0, 1.0], "score": [0.2, 0.8]})
    frame.attrs["scopecat"] = {
        "fields": [
            {
                "name": "bias",
                "role": "coordinate",
                "unit": "V",
                "label": "Bias",
            },
            {
                "name": "score",
                "role": "observable",
                "unit": "ratio",
                "label": "Score",
            },
        ]
    }

    dataset = sc.derived_dataset(
        frame,
        units={"bias": "mV"},
        labels={"score": "Fit score"},
    )

    assert dataset.schema.fields[0].role == "coordinate"
    assert dataset.schema.fields[0].unit == "mV"
    assert dataset.schema.fields[0].label == "Bias"
    assert dataset.schema.fields[1].unit == "ratio"
    assert dataset.schema.fields[1].label == "Fit score"


def test_derived_dataset_inherits_arrow_and_xarray_semantics() -> None:
    arrow_schema = pa.schema(
        [
            pa.field(
                "bias",
                pa.float64(),
                metadata={
                    b"units": b"V",
                    b"long_name": b"Bias",
                    b"scopecat.role": b"coordinate",
                },
            ),
            pa.field("score", pa.float64(), metadata={b"units": b"ratio"}),
        ]
    )
    arrow = sc.derived_dataset(
        pa.Table.from_arrays([[0.0, 1.0], [0.2, 0.8]], schema=arrow_schema),
        labels={"score": "Fit score"},
    )
    xarray = sc.derived_dataset(
        xr.Dataset(
            data_vars={
                "score": (
                    ("bias",),
                    [0.2, 0.8],
                    {"units": "ratio", "long_name": "Fit score"},
                )
            },
            coords={"bias": ("bias", [0.0, 1.0], {"units": "V"})},
        )
    )

    assert arrow.schema.fields[0].role == "coordinate"
    assert arrow.schema.fields[0].unit == "V"
    assert arrow.schema.fields[1].label == "Fit score"
    assert xarray.schema.fields[0].role == "coordinate"
    assert xarray.schema.fields[0].unit == "V"
    assert xarray.schema.fields[1].unit == "ratio"
    assert xarray.schema.fields[1].label == "Fit score"


def test_derived_dataset_rejects_implicit_lossy_xarray_flattening() -> None:
    multidimensional = xr.Dataset(
        data_vars={"signal": (("bias", "frequency"), [[1.0, 2.0], [3.0, 4.0]])},
        coords={"bias": [0.0, 1.0], "frequency": [5.0, 6.0]},
    )
    mixed_shape = xr.Dataset(
        data_vars={
            "signal": (("bias",), [1.0, 2.0]),
            "fit_quality": 0.9,
        },
        coords={"bias": [0.0, 1.0]},
    )

    with pytest.raises(ValueError, match="exactly one dimension"):
        sc.derived_dataset(multidimensional)
    with pytest.raises(ValueError, match="must use dimension"):
        sc.derived_dataset(mixed_shape)


def test_derived_xarray_round_trip_preserves_physical_dtype() -> None:
    source = xr.Dataset(
        data_vars={"score": (("bias",), np.asarray([0.2, 0.8], dtype=np.float32))},
        coords={"bias": np.asarray([1, 2], dtype=np.int32)},
    )

    restored = sc.derived_dataset(source).to_xarray()

    assert restored["bias"].dtype == np.dtype(np.int32)
    assert restored["score"].dtype == np.dtype(np.float32)
    assert restored.identical(source)


def test_derived_dataset_round_trips_raw_arrow_content() -> None:
    dataset = sc.derived_dataset(pa.table({"score": [0.2, 0.8]}))

    restored = DerivedDataset.from_arrow_ipc(
        dataset.to_arrow_ipc(),
        schema=dataset.schema,
    )

    assert restored.schema == dataset.schema
    assert restored.table.equals(dataset.table, check_metadata=True)


def test_derived_dataset_presentation_selects_only_scalar_view_columns() -> None:
    dataset = sc.derived_dataset(
        pa.table(
            {
                "bias": [0.0, 1.0],
                "score": [0.2, 0.8],
                "trace": [[1.0, 2.0], [3.0, 4.0]],
            }
        ),
        coordinates=("bias",),
    )

    table = dataset.to_analysis_table(columns=("bias", "score"))

    assert [column.id for column in table.columns] == ["bias", "score"]
    assert table.rows[1].cells == [1.0, 0.8]


def test_derived_dataset_codec_is_public_and_versioned() -> None:
    assert DERIVED_DATASET_CODEC == "scopecat.derived-dataset.arrow-ipc.v1"
