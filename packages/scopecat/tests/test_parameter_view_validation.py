from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ParameterState,
    ParameterTable,
    ParameterTableColumn,
    ParameterTableDefinition,
    ParameterValue,
    ParameterValueSet,
    Quantity,
)
from scopecat.parameters import (
    ParameterDerivationSet,
    TableParameterDerivation,
    build_parameter_view,
)
from scopecat.relations import col, table
from scopecat.value_types import Bool, Float, Scalar, String


def test_parameter_view_snapshot_records_scalar_validation_diagnostics() -> None:
    build = build_parameter_view(
        catalog=ParameterCatalog(
            id="catalog",
            scalar_definitions=[
                ParameterDefinition(
                    id="drive_frequency",
                    unit="GHz",
                    safety_min=Quantity(value=4.0, unit="GHz"),
                    safety_max=Quantity(value=6.0, unit="GHz"),
                ),
                ParameterDefinition(id="readout_frequency", unit="GHz"),
            ],
        ),
        parameter_state=ParameterState(
            id="state",
            scalar_values=ParameterValueSet(
                id="scalars",
                values=[
                    ParameterValue(
                        id="drive_frequency",
                        quantity=Quantity(value=7000, unit="MHz"),
                    ),
                    ParameterValue(
                        id="orphan",
                        quantity=Quantity(value=5.0, unit="GHz"),
                    ),
                ],
            ),
        ),
    )

    assert _codes(build.diagnostics) == [
        "missing_parameter_value",
        "parameter_value_outside_safety_limits",
        "unknown_parameter_value_definition",
    ]
    assert build.diagnostics[0]["path"] == "parameter_state.scalar_values"


def test_parameter_view_snapshot_records_derivation_diagnostics() -> None:
    build = build_parameter_view(
        catalog=ParameterCatalog(
            id="catalog",
            table_definitions=[
                ParameterTableDefinition(
                    id="drive_plan",
                    primary_key=["channel_id"],
                    columns=[
                        ParameterTableColumn(
                            id="channel_id",
                            value_type=Scalar(String()),
                        ),
                        ParameterTableColumn(
                            id="enabled",
                            value_type=Scalar(Bool()),
                        ),
                    ],
                )
            ],
        ),
        parameter_state=ParameterState(
            id="state",
            scalar_values=ParameterValueSet(id="scalars", values=[]),
            tables=[
                ParameterTable(
                    id="drive_channels",
                    rows=[{"channel_id": "xy0", "enabled": "yes"}],
                )
            ],
        ),
        derivations=ParameterDerivationSet(
            id="derivations",
            tables=[
                TableParameterDerivation(
                    id="drive_plan",
                    relation=table("drive_channels").select(
                        "channel_id",
                        "enabled",
                    ),
                )
            ],
        ),
    )

    assert _codes(build.diagnostics) == [
        "unknown_parameter_table_definition",
        "invalid_parameter_table_bool",
    ]
    assert build.table("drive_plan") is not None


def test_parameter_table_cells_use_scalar_constraints_and_nullable_semantics() -> None:
    build = build_parameter_view(
        catalog=ParameterCatalog(
            id="catalog",
            table_definitions=[
                ParameterTableDefinition(
                    id="channels",
                    primary_key=["id"],
                    columns=[
                        ParameterTableColumn(
                            id="id",
                            value_type=Scalar(String(pattern=r"ch-\d+")),
                        ),
                        ParameterTableColumn(
                            id="gain",
                            value_type=Scalar(Float(minimum=0.0, maximum=1.0)),
                        ),
                        ParameterTableColumn(
                            id="note",
                            value_type=Scalar(String()),
                            required=False,
                        ),
                        ParameterTableColumn(
                            id="nullable_note",
                            value_type=Scalar(String(), nullable=True),
                            required=False,
                        ),
                    ],
                )
            ],
        ),
        parameter_state=ParameterState(
            id="state",
            scalar_values=ParameterValueSet(id="scalars", values=[]),
            tables=[
                ParameterTable(
                    id="channels",
                    rows=[
                        {
                            "id": "bad",
                            "gain": 2.0,
                            "note": None,
                            "nullable_note": None,
                        },
                        {"id": "ch-2", "gain": 0.5},
                    ],
                )
            ],
        ),
    )

    assert _codes(build.diagnostics) == [
        "invalid_parameter_table_string",
        "invalid_parameter_table_number",
        "invalid_parameter_table_string",
    ]


def test_parameter_view_snapshot_records_failed_derivations_as_diagnostics() -> None:
    build = build_parameter_view(
        catalog=ParameterCatalog(id="catalog"),
        parameter_state=ParameterState(
            id="state",
            scalar_values=ParameterValueSet(id="scalars", values=[]),
        ),
        derivations=ParameterDerivationSet(
            id="broken",
            tables=[
                TableParameterDerivation(
                    id="broken_table",
                    relation=table("missing").with_columns(id=col("id")),
                )
            ],
        ),
    )

    assert _codes(build.diagnostics) == ["parameter_derivation_evaluation_failed"]
    assert build.table("broken_table") is None


def _codes(diagnostics: list[dict[str, object]]) -> list[str]:
    return [str(item["code"]) for item in diagnostics]
