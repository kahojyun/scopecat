from __future__ import annotations

from scopecat.records.data_artifact import (
    DataColumn,
    DataTableSchema,
)


def metrics_table_schema() -> DataTableSchema:
    return DataTableSchema(
        columns=[
            DataColumn(id="metric", role="identifier", dtype="string"),
            DataColumn(id="value", role="observable", dtype="float64", unit="ratio"),
            DataColumn(id="passed", role="status", dtype="bool"),
        ],
        primary_key=["metric"],
    )
