from __future__ import annotations

import pytest

from scopecat.config.parameter_updates import (
    materialize_parameter_updates,
    merge_parameter_change_deltas,
)
from scopecat.config.parameters import (
    delete_parameter_rows,
    insert_parameter_rows,
    replace_scalar_parameter,
    replace_series_parameter,
    replace_table_parameter,
    update_parameter_rows,
)
from scopecat.config.validation import parameter_table_key_part
from scopecat.kernel.value_types import (
    Bool,
    Float,
    Int,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
)
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ParameterSnapshot,
    Quantity,
    ScalarParameterValue,
    SeriesParameterValue,
    TableParameterValue,
)


def test_typed_replacements_materialize_authoritative_snapshot_and_deltas() -> None:
    source = _snapshot()

    candidate, deltas = materialize_parameter_updates(
        catalog=_catalog(),
        base=source,
        candidate_id="candidate",
        updates=(
            replace_scalar_parameter(
                "drive.lo_frequency",
                Quantity(value=5100, unit="MHz"),
            ),
            replace_series_parameter("thresholds", [3, 4, 5]),
            replace_table_parameter(
                "drive_channels",
                [
                    {
                        "channel_id": "xy2",
                        "resource_id": "drive-c",
                        "enabled": True,
                        "gain": 1,
                        "fixed_if": Quantity(value=140, unit="MHz"),
                    }
                ],
            ),
        ),
    )

    frequency = candidate.get("drive.lo_frequency")
    thresholds = candidate.get("thresholds")
    channels = candidate.get("drive_channels")
    assert frequency == ScalarParameterValue(
        id="drive.lo_frequency",
        value=Quantity(value=5.1, unit="GHz"),
    )
    assert thresholds == SeriesParameterValue(
        id="thresholds",
        items=(3, 4, 5),
    )
    assert isinstance(channels, TableParameterValue)
    assert channels.rows == (
        {
            "channel_id": "xy2",
            "resource_id": "drive-c",
            "enabled": True,
            "gain": 1.0,
            "fixed_if": Quantity(value=140, unit="MHz"),
        },
    )
    assert [delta.parameter_id for delta in deltas] == [
        "drive.lo_frequency",
        "thresholds",
        "drive_channels",
    ]
    assert all(candidate.get(delta.parameter_id) == delta.after for delta in deltas)
    assert source == _snapshot()


def test_row_updates_materialize_one_whole_value_delta_without_mutating_base() -> None:
    source = _snapshot()

    candidate, deltas = materialize_parameter_updates(
        catalog=_catalog(),
        base=source,
        candidate_id="row-candidate",
        updates=(
            update_parameter_rows(
                "drive_channels",
                key={"channel_id": "xy0"},
                values={"gain": 0.7},
            ),
            insert_parameter_rows(
                "drive_channels",
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
            delete_parameter_rows(
                "drive_channels",
                key={"channel_id": "xy1"},
            ),
        ),
    )

    table = candidate.get("drive_channels")
    assert isinstance(table, TableParameterValue)
    assert table.rows == (
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
    )
    assert len(deltas) == 1
    assert deltas[0].parameter_id == "drive_channels"
    assert deltas[0].before == source.get("drive_channels")
    assert deltas[0].after == table
    assert source == _snapshot()


def test_deltas_are_authoritative_candidate_input() -> None:
    source = _snapshot()
    candidate, deltas = materialize_parameter_updates(
        catalog=_catalog(),
        base=source,
        candidate_id="candidate",
        updates=(
            replace_scalar_parameter(
                "drive.lo_frequency",
                Quantity(value=5.1, unit="GHz"),
            ),
        ),
    )
    merged = merge_parameter_change_deltas(
        base=source,
        proposals=(deltas,),
        candidate_id="merged",
    )
    assert merged == candidate.model_copy(update={"id": "merged"})

    [delta] = deltas
    invalid = delta.model_copy(
        update={
            "before": ScalarParameterValue(
                id=delta.parameter_id,
                value=Quantity(value=4.9, unit="GHz"),
            )
        },
    )
    with pytest.raises(ValueError, match="before value does not match"):
        merge_parameter_change_deltas(
            base=source,
            proposals=((invalid,),),
            candidate_id="merged",
        )


def test_materialization_rejects_unknown_and_wrong_shape_updates() -> None:
    source = _snapshot()

    for update, message in (
        (replace_scalar_parameter("unknown", True), "not defined"),
        (
            replace_series_parameter("drive.lo_frequency", [1, 2]),
            "replacement shape",
        ),
        (
            update_parameter_rows(
                "drive.lo_frequency",
                key={"id": "x"},
                values={"value": 1},
            ),
            "not table-shaped",
        ),
    ):
        try:
            materialize_parameter_updates(
                catalog=_catalog(),
                base=source,
                candidate_id="invalid",
                updates=(update,),
            )
        except ValueError as error:
            assert message in str(error)
        else:
            raise AssertionError("invalid parameter update was accepted")


def test_materialization_rejects_semantic_no_op_after_normalization() -> None:
    with pytest.raises(ValueError, match="does not change"):
        materialize_parameter_updates(
            catalog=_catalog(),
            base=_snapshot(),
            candidate_id="no-op",
            updates=(
                replace_scalar_parameter(
                    "drive.lo_frequency",
                    Quantity(value=5000, unit="MHz"),
                ),
            ),
        )


def test_quantity_primary_key_matches_normalized_snapshot_rows() -> None:
    catalog = ParameterCatalog(
        id="frequency-catalog",
        definitions=(
            ParameterDefinition(
                id="frequencies",
                value_type=Table(
                    columns=(
                        TableColumn(
                            id="frequency",
                            value_type=Scalar(QuantityType(unit="GHz")),
                        ),
                        TableColumn(id="label", value_type=Scalar(String())),
                    ),
                    primary_key=("frequency",),
                ),
            ),
        ),
    )
    source = ParameterSnapshot.model_validate(
        {
            "id": "frequency-snapshot",
            "values": [
                {
                    "shape": "table",
                    "id": "frequencies",
                    "rows": [
                        {
                            "frequency": {"value": 5000, "unit": "MHz"},
                            "label": "old",
                        }
                    ],
                }
            ],
        }
    )

    candidate, _deltas = materialize_parameter_updates(
        catalog=catalog,
        base=source,
        candidate_id="frequency-candidate",
        updates=(
            update_parameter_rows(
                "frequencies",
                key={"frequency": Quantity(value=5, unit="GHz")},
                values={"label": "new"},
            ),
        ),
    )

    table = candidate.get("frequencies")
    assert isinstance(table, TableParameterValue)
    assert table.rows == (
        {
            "frequency": Quantity(value=5, unit="GHz"),
            "label": "new",
        },
    )


def test_entity_parameter_key_identity_ignores_metadata_but_includes_kind() -> None:
    left = EntityRef(
        id="q0",
        kind="qubit",
        metadata={"labels": ["data"], "index": 0},
    )
    same_identity = EntityRef(
        id="q0",
        kind="qubit",
        metadata={"index": 1, "labels": ["ancilla"]},
    )
    other_kind = EntityRef(id="q0", kind="resonator")

    assert parameter_table_key_part(left) == parameter_table_key_part(same_identity)
    assert parameter_table_key_part(left) != parameter_table_key_part(other_kind)


def _catalog() -> ParameterCatalog:
    return ParameterCatalog(
        id="catalog",
        definitions=(
            ParameterDefinition(
                id="drive.lo_frequency",
                value_type=Scalar(QuantityType(unit="GHz", minimum=4.0, maximum=6.0)),
            ),
            ParameterDefinition(
                id="thresholds",
                value_type=Series(Scalar(Int()), min_length=1),
            ),
            ParameterDefinition(
                id="drive_channels",
                value_type=Table(
                    columns=(
                        TableColumn(
                            id="channel_id",
                            value_type=Scalar(String()),
                        ),
                        TableColumn(
                            id="resource_id",
                            value_type=Scalar(String()),
                        ),
                        TableColumn(id="enabled", value_type=Scalar(Bool())),
                        TableColumn(id="gain", value_type=Scalar(Float())),
                        TableColumn(
                            id="fixed_if",
                            value_type=Scalar(QuantityType(unit="MHz")),
                        ),
                    ),
                    primary_key=("channel_id",),
                ),
            ),
        ),
    )


def _snapshot() -> ParameterSnapshot:
    return ParameterSnapshot(
        id="accepted",
        values=(
            ScalarParameterValue(
                id="drive.lo_frequency",
                value=Quantity(value=5.0, unit="GHz"),
            ),
            SeriesParameterValue(id="thresholds", items=(1, 2)),
            TableParameterValue(
                id="drive_channels",
                rows=(
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
                ),
            ),
        ),
    )
