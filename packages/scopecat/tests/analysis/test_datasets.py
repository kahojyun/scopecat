# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

from __future__ import annotations

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

    assert dataset.schema.schema_id == "scopecat.derived-dataset.v1"
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
            data_vars={"y": (("x",), [3.0, 4.0])},
            coords={"x": [1, 2]},
        ),
        units={"y": "ratio"},
    )

    assert pandas_dataset.table.to_pylist() == [
        {"x": 1, "y": 3.0},
        {"x": 2, "y": 4.0},
    ]
    assert polars_dataset.table.to_pylist() == pandas_dataset.table.to_pylist()
    assert xarray_dataset.table.to_pylist() == pandas_dataset.table.to_pylist()
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


def test_derived_dataset_round_trips_raw_arrow_content() -> None:
    dataset = sc.derived_dataset(pa.table({"score": [0.2, 0.8]}))

    restored = DerivedDataset.from_arrow_ipc(
        dataset.to_arrow_ipc(),
        schema=dataset.schema,
    )

    assert restored.schema == dataset.schema
    assert restored.table.equals(dataset.table, check_metadata=True)


def test_derived_dataset_codec_is_public_and_versioned() -> None:
    assert DERIVED_DATASET_CODEC == "scopecat.derived-dataset.arrow-ipc.v1"
