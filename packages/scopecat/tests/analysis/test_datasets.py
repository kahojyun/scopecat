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


def test_derived_dataset_codec_is_public_and_versioned() -> None:
    assert DERIVED_DATASET_CODEC == "scopecat.derived-dataset.arrow-ipc.v1"
