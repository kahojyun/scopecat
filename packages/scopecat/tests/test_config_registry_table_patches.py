from __future__ import annotations

from pathlib import Path

from scopecat.models.artifact import Artifact
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import (
    ParameterChangeSet,
    ParameterPatch,
    ParameterTable,
    ParameterTableColumn,
    ParameterTableDefinition,
    Quantity,
)
from scopecat.proposals import accept_parameter_proposal
from scopecat.runs import open_run_store
from tests.support.config_registry import simulate_with_proposal
from tests.support.records import assert_artifact_ref, read_model


def test_accept_parameter_proposal_applies_table_patches(tmp_path: Path) -> None:
    run_id = simulate_with_proposal(tmp_path)
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
    proposal = ParameterChangeSet(
        id="drive-channel-update",
        source_run_id=run_id,
        reason="table patch proposal",
        patches=[
            ParameterPatch(
                kind="update_rows",
                table_id="drive_channels",
                key={"channel_id": "xy0"},
                values={"gain": 0.75},
                expected_values={"gain": 0.5},
            )
        ],
    )
    proposal_record_ref = "proposals/drive-channel-update.json"
    storage.write_model(run_id, proposal_record_ref, proposal)
    manifest = storage.read_manifest(run_id)
    manifest.artifact_refs.append(
        Artifact(
            id=proposal.id,
            kind="parameter_change_set",
            path=proposal_record_ref,
            media_type="application/json",
        )
    )
    storage.write_manifest(manifest)

    result, review, *_ = accept_parameter_proposal(
        run_id=run_id,
        selector="drive-channel-update",
        workspace=tmp_path,
        reviewer="operator",
        operator="operator",
        entry_id="accepted-table-patch",
    )

    updated_manifest = storage.read_manifest(run_id)
    candidate_config_artifact = assert_artifact_ref(
        updated_manifest.artifact_refs,
        result.candidate_artifact_id,
        kind="candidate_config",
    )
    candidate_config = read_model(
        storage.ref_path(run_id, candidate_config_artifact.path),
        ConfigProfileSnapshot,
    )
    table = candidate_config.parameter_state.tables[0]
    assert review is not None
    assert table.id == "drive_channels"
    assert table.rows[0]["gain"] == 0.75
    assert candidate_config.parameter_build is not None
    assert candidate_config.parameter_build.table("drive_channels") is not None
