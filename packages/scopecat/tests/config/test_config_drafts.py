from __future__ import annotations

from scopecat.config.drafts import ConfigDraft
from scopecat.kernel.problems import ModelLocation
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
from scopecat.records.config import ConfigProfileSnapshot, config_content_hash
from scopecat.records.parameter import (
    ParameterCatalog,
    ParameterDefinition,
    ParameterSnapshot,
    Quantity,
    ScalarParameterValue,
    SeriesParameterValue,
    TableParameterValue,
)
from tests.testkit.workflow_fixtures import load_config


def test_draft_builds_candidate_deltas_and_structured_table_diff() -> None:
    source = _config()
    source_before = source.model_copy(deep=True)
    draft = (
        ConfigDraft.from_snapshot(source)
        .replace_scalar(
            "drive.lo_frequency",
            Quantity(value=5100, unit="MHz"),
        )
        .replace_series("thresholds", [3, 4, 5])
    )
    (
        draft.table("drive_channels")
        .update(key={"channel_id": "xy0"}, values={"gain": 0.7})
        .insert(
            [
                {
                    "channel_id": "xy2",
                    "resource_id": "drive-c",
                    "enabled": True,
                    "gain": 0.25,
                    "fixed_if": Quantity(value=140, unit="MHz"),
                }
            ]
        )
        .delete(key={"channel_id": "xy1"})
    )

    result = draft.check(candidate_id="candidate")

    assert draft.base_content_hash == config_content_hash(source)
    assert result.ok
    assert result.problems == ()
    assert result.candidate is not None
    assert result.candidate.id == "candidate"
    assert result.candidate.parameter_snapshot.id == "candidate.parameters"
    assert [delta.parameter_id for delta in result.deltas] == [
        "drive.lo_frequency",
        "thresholds",
        "drive_channels",
    ]
    assert result.diff is not None
    assert [parameter.parameter_id for parameter in result.diff.parameters] == [
        "drive.lo_frequency",
        "thresholds",
        "drive_channels",
    ]
    frequency = result.candidate.parameter_snapshot.get("drive.lo_frequency")
    assert frequency == ScalarParameterValue(
        id="drive.lo_frequency",
        value=Quantity(value=5.1, unit="GHz"),
    )
    table_parameter = result.diff.get("drive_channels")
    assert table_parameter is not None
    assert table_parameter.table is not None
    assert table_parameter.table.primary_key == ("channel_id",)
    assert [row.operation for row in table_parameter.table.rows] == [
        "update",
        "delete",
        "insert",
    ]
    update = table_parameter.table.rows[0]
    assert update.key == {"channel_id": "xy0"}
    assert update.before_index == update.after_index == 0
    assert [(cell.column_id, cell.before, cell.after) for cell in update.cells] == [
        ("gain", 0.5, 0.7)
    ]
    assert source == source_before


def test_draft_supports_complete_table_replacement() -> None:
    draft = ConfigDraft(_config())
    draft.table("drive_channels").replace(
        [
            {
                "channel_id": "xy0",
                "resource_id": "drive-a",
                "enabled": False,
                "gain": 0.5,
                "fixed_if": Quantity(value=100, unit="MHz"),
            }
        ]
    )
    result = draft.check()

    assert result.ok
    assert result.diff is not None
    parameter = result.diff.get("drive_channels")
    assert parameter is not None
    assert parameter.table is not None
    assert [row.operation for row in parameter.table.rows] == ["update", "delete"]
    assert [cell.column_id for cell in parameter.table.rows[0].cells] == ["enabled"]


def test_invalid_draft_returns_cell_addressable_problem() -> None:
    result = ConfigDraft(_config()).replace_scalar("drive.lo_frequency", True).check()

    assert not result.ok
    assert result.candidate is None
    assert result.deltas == ()
    assert result.diff is None
    [problem] = result.problems
    assert problem.code == "invalid_parameter_quantity"
    assert isinstance(problem.location, ModelLocation)
    assert problem.location.root == "parameter_snapshot"
    assert problem.location.path == ("values", "drive.lo_frequency", "value")


def test_empty_and_semantic_noop_drafts_are_not_candidates() -> None:
    empty = ConfigDraft(_config()).check()
    no_op = (
        ConfigDraft(_config())
        .replace_scalar(
            "drive.lo_frequency",
            Quantity(value=5000, unit="MHz"),
        )
        .check()
    )

    assert not empty.ok
    assert empty.problems[0].code == "config_draft_empty"
    assert not no_op.ok
    assert no_op.problems[0].code == "config_draft_no_changes"


def _config() -> ConfigProfileSnapshot:
    base = load_config()
    catalog = _catalog()
    return base.model_copy(
        update={
            "system": base.system.model_copy(
                update={"parameter_catalog": catalog},
            ),
            "parameter_snapshot": _snapshot(),
        },
        deep=True,
    )


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
                        "enabled": False,
                        "gain": 0.25,
                        "fixed_if": Quantity(value=120, unit="MHz"),
                    },
                ),
            ),
        ),
    )
