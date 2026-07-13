from __future__ import annotations

from pathlib import Path

import scopecat as sc
from scopecat._workflows.config import register_and_activate_candidate_config
from scopecat.config_profiles import load_config_profile
from scopecat.config_registry import (
    CandidateConfigRegistrySource,
    load_config_registry_config,
)
from scopecat.models.config import ConfigProfileSnapshot
from scopecat.models.parameter import (
    ParameterDefinition,
    Quantity,
    TableParameterValue,
)
from scopecat.value_types import Float, Scalar, String, Table, TableColumn
from scopecat.value_types import Quantity as QuantityType
from tests.support.signal_instruments import TestSignalInstrumentProvider
from tests.support.workflow_fixtures import load_invocation

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


def test_candidate_config_activation_materializes_table_row_updates(
    tmp_path: Path,
) -> None:
    config = _config_with_drive_channels()
    lab = sc.open(
        tmp_path,
        config=config,
        execution_backend=sc.ExecutionBackend(provider=TestSignalInstrumentProvider()),
    )
    run = lab.prepare(load_invocation()).run()
    analysis = run.analysis("table update fixture").propose(
        "drive-channel-update",
        sc.update_parameter_rows(
            "drive_channels",
            key={"channel_id": "xy0"},
            values={"gain": 0.75},
        ),
        sc.insert_parameter_rows(
            "drive_channels",
            rows=[
                {
                    "channel_id": "xy1",
                    "resource_id": "drive-b",
                    "gain": 0.25,
                    "fixed_if": Quantity(value=120, unit="MHz"),
                }
            ],
        ),
        sc.delete_parameter_rows(
            "drive_channels",
            key={"channel_id": "remove-me"},
        ),
        reason="table row updates",
    )
    candidate = analysis.candidate_config()
    proposal = analysis.parameter_proposals[0]

    assert len(proposal.deltas) == 1
    assert proposal.deltas[0].parameter_id == "drive_channels"
    assert proposal.candidate_snapshot.get("drive_channels") == (
        proposal.deltas[0].after
    )
    analysis.save()
    lab.review_parameter_proposal(run, proposal.id)

    activation = register_and_activate_candidate_config(
        candidate=candidate,
        workspace=tmp_path,
        registered_by="operator",
        operator="operator",
        entry_id="candidate-table-update",
    )
    entry = activation.entry
    assert isinstance(entry.source, CandidateConfigRegistrySource)
    assert entry.source.proposal_ids == ["drive-channel-update"]

    candidate_config = load_config_registry_config(
        entry_id=entry.id,
        workspace=tmp_path,
    )
    table = candidate_config.parameter_snapshot.get("drive_channels")
    assert isinstance(table, TableParameterValue)
    assert table.rows == (
        {
            "channel_id": "xy0",
            "resource_id": "drive-a",
            "gain": 0.75,
            "fixed_if": Quantity(value=100, unit="MHz"),
        },
        {
            "channel_id": "xy1",
            "resource_id": "drive-b",
            "gain": 0.25,
            "fixed_if": Quantity(value=120, unit="MHz"),
        },
    )


def _config_with_drive_channels() -> ConfigProfileSnapshot:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    definition = ParameterDefinition(
        id="drive_channels",
        value_type=Table(
            columns=(
                TableColumn(id="channel_id", value_type=Scalar(String())),
                TableColumn(id="resource_id", value_type=Scalar(String())),
                TableColumn(id="gain", value_type=Scalar(Float())),
                TableColumn(
                    id="fixed_if",
                    value_type=Scalar(QuantityType(unit="MHz")),
                ),
            ),
            primary_key=("channel_id",),
        ),
    )
    catalog = config.parameter_catalog.model_copy(
        update={"definitions": (*config.parameter_catalog.definitions, definition)}
    )
    system = config.system.model_copy(update={"parameter_catalog": catalog})
    table = TableParameterValue(
        id="drive_channels",
        rows=(
            {
                "channel_id": "xy0",
                "resource_id": "drive-a",
                "gain": 0.5,
                "fixed_if": Quantity(value=100, unit="MHz"),
            },
            {
                "channel_id": "remove-me",
                "resource_id": "drive-stale",
                "gain": 0.1,
                "fixed_if": Quantity(value=80, unit="MHz"),
            },
        ),
    )
    snapshot = config.parameter_snapshot.model_copy(
        update={"values": (*config.parameter_snapshot.values, table)}
    )
    return config.model_copy(update={"system": system, "parameter_snapshot": snapshot})
