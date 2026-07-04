from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat.config_registry import (
    CandidateConfigRegistrySource,
    load_config_registry_config,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import (
    ParameterTable,
    ParameterTableColumn,
    ParameterTableDefinition,
    Quantity,
)
from scopecat.runs import open_run_store
from scopecat.workflows import register_and_activate_candidate_config
from tests.support.config_registry import signal_run_with_parameter_change


def test_candidate_config_activation_applies_table_patches(tmp_path: Path) -> None:
    run_id = signal_run_with_parameter_change(tmp_path)
    storage = open_run_store(tmp_path)
    config = storage.read_model(
        run_id,
        "config-profile.snapshot.json",
        ConfigProfileSnapshot,
    )
    table_definition = ParameterTableDefinition(
        id="drive_channels",
        primary_key=["channel_id"],
        columns=[
            ParameterTableColumn(id="channel_id", kind="string"),
            ParameterTableColumn(id="resource_id", kind="string"),
            ParameterTableColumn(id="gain", kind="number"),
            ParameterTableColumn(id="fixed_if", kind="quantity", unit="MHz"),
        ],
    )
    system = config.system.model_copy(
        update={
            "parameter_catalog": config.parameter_catalog.model_copy(
                update={"table_definitions": [table_definition]},
                deep=True,
            )
        },
        deep=True,
    )
    parameter_state = config.parameter_state.model_copy(
        update={
            "tables": [
                ParameterTable(
                    id="drive_channels",
                    rows=[
                        {
                            "channel_id": "xy0",
                            "resource_id": "drive-a",
                            "gain": 0.5,
                            "fixed_if": Quantity(value=100, unit="MHz"),
                        }
                    ],
                )
            ]
        },
        deep=True,
    )
    config = ConfigProfileSnapshot.model_validate(
        config.model_dump(mode="python")
        | {
            "system": system,
            "parameter_state": parameter_state,
        }
    )
    storage.write_model(run_id, "config-profile.snapshot.json", config)
    lab = sc.open(tmp_path, config=config)
    run = lab.get_run(run_id)
    candidate = (
        run.analysis("table patch fixture")
        .propose(
            "drive-channel-update",
            sc.update_param_rows(
                "drive_channels",
                key={"channel_id": "xy0"},
                values={"gain": 0.75},
            ),
            reason="table patch change",
        )
        .candidate_config()
    )

    activation = register_and_activate_candidate_config(
        candidate=candidate,
        workspace=tmp_path,
        registered_by="operator",
        operator="operator",
        entry_id="candidate-table-patch",
    )
    entry = activation.entry
    assert isinstance(entry.source, CandidateConfigRegistrySource)

    candidate_config = load_config_registry_config(
        entry_id=entry.id,
        workspace=tmp_path,
    )
    table = candidate_config.parameter_state.tables[0]
    assert table.id == "drive_channels"
    assert table.rows[0]["gain"] == 0.75
    assert candidate_config.parameter_build is not None
    assert candidate_config.parameter_build.table("drive_channels") is not None
