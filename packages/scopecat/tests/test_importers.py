from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest
from pydantic import ValidationError

import scopecat.importers as importers
from scopecat.importers import (
    ImportSourceLocation,
    ParameterImportRejected,
    ScalarParameterDraftValue,
    SeriesParameterDraftValue,
    TableParameterDraftValue,
    accept_parameter_import,
    import_diagnostic,
    parameter_import_result,
)
from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ScalarParameterValue,
    SeriesParameterValue,
    TableParameterValue,
)
from scopecat.value_types import (
    Bool,
    Float,
    Int,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)


def test_import_result_contains_raw_draft_instead_of_parameter_snapshot() -> None:
    location = ImportSourceLocation(
        source_uri="registry://parameters",
        path="parameters.enabled",
    )
    result = parameter_import_result(
        id="typed-import",
        source_kind="registry",
        source_uri=location.source_uri,
        values=[
            ScalarParameterDraftValue(
                id="enabled",
                value="not-yet-validated",
                location=location,
            ),
            SeriesParameterDraftValue(
                id="thresholds",
                items=[1, "also-raw"],
                location=location,
            ),
            TableParameterDraftValue(
                id="channels",
                rows=[{"id": "ch-0", "gain": "raw"}],
                location=location,
            ),
        ],
    )

    assert result.draft.id == "typed-import.draft"
    scalar = result.draft.values[0]
    series = result.draft.values[1]
    table = result.draft.values[2]
    assert isinstance(scalar, ScalarParameterDraftValue)
    assert scalar.value == "not-yet-validated"
    assert isinstance(series, SeriesParameterDraftValue)
    assert series.items == [1, "also-raw"]
    assert isinstance(table, TableParameterDraftValue)
    assert table.rows[0]["gain"] == "raw"
    assert not hasattr(result, "parameter_state")
    assert not hasattr(importers, "ImportedScalarParameter")
    assert not hasattr(importers, "ImportedParameterTable")


def test_accept_parameter_import_validates_and_freezes_all_shapes() -> None:
    source_uri = "file://calibration.json"
    location = ImportSourceLocation(source_uri=source_uri)
    row_location = ImportSourceLocation(source_uri=source_uri, row=2)
    result = parameter_import_result(
        id="calibration-import",
        source_kind="json",
        source_uri=source_uri,
        values=[
            ScalarParameterDraftValue(id="gain", value=1, location=location),
            ScalarParameterDraftValue(id="enabled", value=True, location=location),
            SeriesParameterDraftValue(
                id="thresholds",
                items=[1, 2],
                location=location,
                item_locations=[location, location],
            ),
            TableParameterDraftValue(
                id="channels",
                rows=[{"id": "ch-0", "gain": 1}],
                location=location,
                row_locations=[row_location],
            ),
        ],
        draft_metadata={"nested": {"reviewed": True}},
    )

    snapshot = accept_parameter_import(result, _catalog())

    scalar = snapshot.get("gain")
    series = snapshot.get("thresholds")
    table = snapshot.get("channels")
    assert isinstance(scalar, ScalarParameterValue)
    assert scalar.value == 1.0
    assert isinstance(series, SeriesParameterValue)
    assert series.items == (1, 2)
    assert isinstance(table, TableParameterValue)
    assert table.rows == ({"id": "ch-0", "gain": 1.0},)
    assert table.metadata["import_row_locations"] == (
        {"source_uri": source_uri, "row": 2},
    )
    nested = snapshot.metadata["nested"]
    assert isinstance(nested, Mapping)
    with pytest.raises(TypeError):
        cast("dict[str, object]", table.rows[0])["gain"] = 2.0
    with pytest.raises(TypeError):
        cast("dict[str, object]", nested)["reviewed"] = False


def test_importer_blocking_diagnostic_prevents_acceptance() -> None:
    location = ImportSourceLocation(
        source_uri="legacy://calibration",
        path="parameters.enabled",
    )
    result = parameter_import_result(
        id="blocked-import",
        source_kind="legacy",
        source_uri=location.source_uri,
        values=[ScalarParameterDraftValue(id="enabled", value=True, location=location)],
        diagnostics=[
            import_diagnostic(
                severity="blocker",
                code="import_required_value_missing",
                message="source record is incomplete",
                location=location,
            )
        ],
    )

    assert result.has_blocking_diagnostics is True
    with pytest.raises(ParameterImportRejected) as caught:
        accept_parameter_import(result, _catalog())
    assert [diagnostic.code for diagnostic in caught.value.diagnostics] == [
        "import_required_value_missing"
    ]


def test_catalog_validation_rejects_raw_value_at_source_location() -> None:
    location = ImportSourceLocation(
        source_uri="registry://parameters",
        path="parameters.enabled",
    )
    result = parameter_import_result(
        id="invalid-import",
        source_kind="registry",
        source_uri=location.source_uri,
        values=[
            ScalarParameterDraftValue(
                id="gain",
                value=0.5,
                location=location,
            ),
            ScalarParameterDraftValue(
                id="enabled",
                value="yes",
                location=location,
            ),
            SeriesParameterDraftValue(
                id="thresholds",
                items=[1, 2],
                location=location,
            ),
            TableParameterDraftValue(
                id="channels",
                rows=[{"id": "ch-0", "gain": 0.5}],
                location=location,
            ),
        ],
    )

    with pytest.raises(ParameterImportRejected) as caught:
        accept_parameter_import(result, _catalog())

    assert [diagnostic.code for diagnostic in caught.value.diagnostics] == [
        "invalid_parameter_bool"
    ]
    assert caught.value.diagnostics[0].location == location


def test_acceptance_wraps_invalid_draft_metadata_as_import_diagnostic() -> None:
    result = parameter_import_result(
        id="invalid-metadata",
        source_kind="manual",
        source_uri="manual://parameters",
        draft_metadata={"open_handle": object()},
    )

    with pytest.raises(ParameterImportRejected) as caught:
        accept_parameter_import(result, _catalog())

    assert [diagnostic.code for diagnostic in caught.value.diagnostics] == [
        "invalid_parameter_draft_metadata"
    ]
    assert caught.value.diagnostics[0].location == ImportSourceLocation(
        source_uri="manual://parameters"
    )


def test_catalog_diagnostics_use_series_item_and_table_row_locations() -> None:
    source = "file://calibration.csv"
    parameter_location = ImportSourceLocation(source_uri=source, row=1)
    item_locations = [
        ImportSourceLocation(source_uri=source, row=2),
        ImportSourceLocation(source_uri=source, row=3),
    ]
    row_locations = [
        ImportSourceLocation(source_uri=source, row=8),
        ImportSourceLocation(source_uri=source, row=9),
    ]
    result = parameter_import_result(
        id="located-errors",
        source_kind="csv",
        source_uri=source,
        values=[
            ScalarParameterDraftValue(
                id="gain",
                value=0.5,
                location=parameter_location,
            ),
            ScalarParameterDraftValue(
                id="enabled",
                value=True,
                location=parameter_location,
            ),
            SeriesParameterDraftValue(
                id="thresholds",
                items=[1, "invalid"],
                location=parameter_location,
                item_locations=item_locations,
            ),
            TableParameterDraftValue(
                id="channels",
                rows=[
                    {"id": "ch-0", "gain": 0.5},
                    {"id": "ch-1", "gain": "invalid"},
                ],
                location=parameter_location,
                row_locations=row_locations,
            ),
        ],
    )

    with pytest.raises(ParameterImportRejected) as caught:
        accept_parameter_import(result, _catalog())

    assert [diagnostic.code for diagnostic in caught.value.diagnostics] == [
        "invalid_parameter_int",
        "invalid_parameter_number",
    ]
    assert [diagnostic.location for diagnostic in caught.value.diagnostics] == [
        item_locations[1],
        row_locations[1],
    ]


def test_raw_conversion_error_uses_the_failing_row_location() -> None:
    source = "file://calibration.csv"
    parameter_location = ImportSourceLocation(source_uri=source, row=1)
    row_locations = [ImportSourceLocation(source_uri=source, row=12)]
    result = parameter_import_result(
        id="raw-row-error",
        source_kind="csv",
        source_uri=source,
        values=[
            TableParameterDraftValue(
                id="channels",
                rows=[{"id": "ch-0", "gain": object()}],
                location=parameter_location,
                row_locations=row_locations,
            )
        ],
    )

    with pytest.raises(ParameterImportRejected) as caught:
        accept_parameter_import(result, _catalog())

    assert caught.value.diagnostics[0].code == "invalid_imported_parameter_value"
    assert caught.value.diagnostics[0].location == row_locations[0]


def test_draft_collection_location_cardinality_is_structural() -> None:
    location = ImportSourceLocation(source_uri="file://calibration.csv")
    with pytest.raises(ValidationError):
        SeriesParameterDraftValue(
            id="thresholds",
            items=[1, 2],
            location=location,
            item_locations=[location],
        )
    with pytest.raises(ValidationError):
        TableParameterDraftValue(
            id="channels",
            rows=[{"id": "ch-0"}, {"id": "ch-1"}],
            location=location,
            row_locations=[location],
        )


def _catalog() -> ParameterCatalog:
    return ParameterCatalog(
        id="parameter-catalog",
        definitions=[
            ParameterDefinition(id="gain", value_type=Scalar(Float())),
            ParameterDefinition(id="enabled", value_type=Scalar(Bool())),
            ParameterDefinition(
                id="thresholds",
                value_type=Series(Scalar(Int())),
            ),
            ParameterDefinition(
                id="channels",
                value_type=Table(
                    columns=(
                        TableColumn(id="id", value_type=Scalar(String())),
                        TableColumn(id="gain", value_type=Scalar(Float())),
                    ),
                    primary_key=("id",),
                ),
            ),
        ],
    )
