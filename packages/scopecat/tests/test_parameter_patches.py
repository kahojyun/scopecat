import pytest

from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ParameterPatch,
    ParameterState,
    ParameterTable,
    ParameterTableColumn,
    ParameterTableDefinition,
    ParameterValue,
    ParameterValueSet,
    Quantity,
)
from scopecat.parameters import apply_parameter_patches, diff_parameter_states


def test_parameter_patches_apply_to_candidate_state_without_mutating_source() -> None:
    source = _state()

    candidate = apply_parameter_patches(
        catalog=_catalog(),
        parameter_state=source,
        state_id="candidate",
        allow_table_row_changes=True,
        patches=[
            ParameterPatch(
                kind="set_scalar",
                parameter_id="drive.lo_frequency",
                expected_value=Quantity(value=5.0, unit="GHz"),
                value=Quantity(value=5100, unit="MHz"),
            ),
            ParameterPatch(
                kind="update_rows",
                table_id="drive_channels",
                key={"channel_id": "xy0"},
                values={"gain": 0.7},
                expected_values={"gain": 0.5},
            ),
            ParameterPatch(
                kind="insert_rows",
                table_id="drive_channels",
                rows=[
                    {
                        "channel_id": "xy2",
                        "resource_id": "drive-c",
                        "enabled": True,
                        "gain": 0.25,
                        "fixed_if": Quantity(value=140, unit="MHz"),
                    }
                ],
            ),
            ParameterPatch(
                kind="delete_rows",
                table_id="drive_channels",
                key={"channel_id": "xy1"},
            ),
        ],
    )

    assert candidate.id == "candidate"
    assert candidate.scalar_value_set().get("drive.lo_frequency") == ParameterValue(
        id="drive.lo_frequency",
        quantity=Quantity(value=5100, unit="MHz"),
    )
    assert source.scalar_value_set().get("drive.lo_frequency") == ParameterValue(
        id="drive.lo_frequency",
        quantity=Quantity(value=5.0, unit="GHz"),
    )
    assert candidate.tables[0].rows == [
        {
            "channel_id": "xy0",
            "resource_id": "drive-a",
            "enabled": True,
            "gain": 0.7,
            "fixed_if": Quantity(value=100, unit="MHz"),
        },
        {
            "channel_id": "xy2",
            "resource_id": "drive-c",
            "enabled": True,
            "gain": 0.25,
            "fixed_if": Quantity(value=140, unit="MHz"),
        },
    ]
    assert source.tables[0].rows[0]["gain"] == 0.5


def test_parameter_patches_reject_table_row_changes_without_permission() -> None:
    with pytest.raises(ValueError, match="explicit table row change permission"):
        apply_parameter_patches(
            catalog=_catalog(),
            parameter_state=_state(),
            patches=[
                ParameterPatch(
                    kind="delete_rows",
                    table_id="drive_channels",
                    key={"channel_id": "xy1"},
                )
            ],
        )


def test_parameter_patches_reject_stale_expected_values() -> None:
    with pytest.raises(ValueError, match="stale parameter patch"):
        apply_parameter_patches(
            catalog=_catalog(),
            parameter_state=_state(),
            patches=[
                ParameterPatch(
                    kind="set_scalar",
                    parameter_id="drive.lo_frequency",
                    expected_value=Quantity(value=4.9, unit="GHz"),
                    value=Quantity(value=5.1, unit="GHz"),
                )
            ],
        )


def test_parameter_patches_validate_table_schema_and_units() -> None:
    with pytest.raises(ValueError, match="requires quantity"):
        apply_parameter_patches(
            catalog=_catalog(),
            parameter_state=_state(),
            patches=[
                ParameterPatch(
                    kind="update_rows",
                    table_id="drive_channels",
                    key={"channel_id": "xy0"},
                    values={"fixed_if": 120},
                )
            ],
        )


def test_diff_parameter_states_returns_replayable_change_set() -> None:
    source = _state()
    candidate = apply_parameter_patches(
        catalog=_catalog(),
        parameter_state=source,
        patches=[
            ParameterPatch(
                kind="set_scalar",
                parameter_id="drive.lo_frequency",
                expected_value=Quantity(value=5.0, unit="GHz"),
                value=Quantity(value=5.1, unit="GHz"),
            ),
            ParameterPatch(
                kind="update_rows",
                table_id="drive_channels",
                key={"channel_id": "xy0"},
                values={"enabled": False},
            ),
        ],
    )

    change_set = diff_parameter_states(
        id="candidate-diff",
        source_run_id="run-1",
        reason="candidate review",
        catalog=_catalog(),
        before=source,
        after=candidate,
        confidence=0.8,
    )
    replayed = apply_parameter_patches(
        catalog=_catalog(),
        parameter_state=source,
        patches=change_set.patches,
    )

    assert change_set.schema_version == "scopecat.parameter_change_set.v1"
    assert change_set.patches == [
        ParameterPatch(
            kind="set_scalar",
            parameter_id="drive.lo_frequency",
            expected_value=Quantity(value=5.0, unit="GHz"),
            value=Quantity(value=5.1, unit="GHz"),
        ),
        ParameterPatch(
            kind="update_rows",
            table_id="drive_channels",
            key={"channel_id": "xy0"},
            values={"enabled": False},
            expected_values={"enabled": True},
        ),
    ]
    assert replayed.scalar_value_set().values == candidate.scalar_value_set().values
    assert replayed.tables == candidate.tables


def _catalog() -> ParameterCatalog:
    return ParameterCatalog(
        id="catalog",
        scalar_definitions=[
            ParameterDefinition(
                id="drive.lo_frequency",
                unit="GHz",
                safety_min=Quantity(value=4.0, unit="GHz"),
                safety_max=Quantity(value=6.0, unit="GHz"),
            )
        ],
        table_definitions=[
            ParameterTableDefinition(
                id="drive_channels",
                primary_key=["channel_id"],
                columns=[
                    ParameterTableColumn(id="channel_id", kind="string"),
                    ParameterTableColumn(id="resource_id", kind="string"),
                    ParameterTableColumn(id="enabled", kind="bool"),
                    ParameterTableColumn(id="gain", kind="number"),
                    ParameterTableColumn(id="fixed_if", kind="quantity", unit="MHz"),
                ],
            )
        ],
    )


def _state() -> ParameterState:
    return ParameterState(
        id="accepted",
        scalar_values=ParameterValueSet(
            id="accepted-scalars",
            values=[
                ParameterValue(
                    id="drive.lo_frequency",
                    quantity=Quantity(value=5.0, unit="GHz"),
                )
            ],
        ),
        tables=[
            ParameterTable(
                id="drive_channels",
                rows=[
                    {
                        "channel_id": "xy0",
                        "resource_id": "drive-a",
                        "enabled": True,
                        "gain": 0.5,
                        "fixed_if": Quantity(value=100, unit="MHz"),
                    },
                    {
                        "channel_id": "xy1",
                        "resource_id": "drive-b",
                        "enabled": True,
                        "gain": 0.6,
                        "fixed_if": Quantity(value=120, unit="MHz"),
                    },
                ],
            )
        ],
    )
