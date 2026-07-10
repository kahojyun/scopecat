import pytest
from pydantic import ValidationError

from scopecat.models.config import (
    InstrumentRegistry,
    SystemSpec,
    Topology,
)
from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterState,
    ParameterTable,
    ParameterValue,
    ParameterValueSet,
    Quantity,
)
from scopecat.parameters import (
    ParameterDerivationSet,
    ScalarParameterDerivation,
    TableParameterDerivation,
    build_parameter_view,
)
from scopecat.relations import col, param, table
from tests.support.records import assert_model_round_trip


def test_parameter_derivation_set_round_trips_separately_from_state() -> None:
    derivations = _parameter_derivations()
    restored = assert_model_round_trip(
        derivations,
        schema_version="scopecat.parameter_derivation_set.v2",
    )

    assert restored.scalars[0].id == "drive.center_frequency"

    with pytest.raises(ValidationError):
        ParameterDerivationSet.model_validate(
            {
                **restored.model_dump(mode="python"),
                "schema_version": "scopecat.parameter_derivation_set.v1",
            }
        )


def test_build_parameter_view_evaluates_relation_derivations() -> None:
    state = _parameter_state()
    system = _system()
    derivations = _parameter_derivations()
    build = build_parameter_view(
        catalog=system.parameter_catalog,
        parameter_state=state,
        derivations=derivations,
    )
    repeated = build_parameter_view(
        catalog=system.parameter_catalog,
        parameter_state=state,
        derivations=derivations,
    )
    changed = build_parameter_view(
        catalog=system.parameter_catalog,
        parameter_state=state.model_copy(
            update={
                "scalar_values": ParameterValueSet(
                    id="accepted-scalars",
                    values=[
                        ParameterValue(
                            id="drive.lo_frequency",
                            quantity=Quantity(value=5.1, unit="GHz"),
                        )
                    ],
                )
            },
            deep=True,
        ),
        derivations=derivations,
    )

    derived_scalar = build.get("drive.center_frequency")
    derived_table = build.table("drive_plan")

    assert build.derivation_set_id == "drive-derivations"
    assert build.derivation_set_hash is not None
    assert build.view_implementation_id == "scopecat.parameter_view.local"
    assert build.view_implementation_version == "v2"
    assert _is_sha256(build.catalog_hash)
    assert _is_sha256(build.source_state_hash)
    assert _is_sha256(build.derivation_set_hash)
    assert _is_sha256(build.content_hash)
    assert repeated.content_hash == build.content_hash
    assert changed.source_state_hash != build.source_state_hash
    assert changed.content_hash != build.content_hash
    assert derived_scalar is not None
    assert derived_scalar.quantity == Quantity(value=5.1, unit="GHz")
    assert derived_table is not None
    assert derived_table.rows == [
        {
            "channel_id": "xy0",
            "resource_id": "drive-a",
            "carrier_frequency": Quantity(value=5.1, unit="GHz"),
        },
        {
            "channel_id": "xy1",
            "resource_id": "drive-b",
            "carrier_frequency": Quantity(value=5.12, unit="GHz"),
        },
    ]


def _parameter_state() -> ParameterState:
    return ParameterState(
        id="parameter-state",
        scalar_values=ParameterValueSet(
            id="accepted-scalars",
            values=[
                ParameterValue(
                    id="drive.lo_frequency",
                    quantity=Quantity(value=5.0, unit="GHz"),
                ),
            ],
        ),
        tables=[
            ParameterTable(
                id="drive_channels",
                rows=[
                    {
                        "channel_id": "xy0",
                        "resource_id": "drive-a",
                        "fixed_if": Quantity(value=100, unit="MHz"),
                    },
                    {
                        "channel_id": "xy1",
                        "resource_id": "drive-b",
                        "fixed_if": Quantity(value=120, unit="MHz"),
                    },
                ],
            )
        ],
    )


def _parameter_derivations() -> ParameterDerivationSet:
    return ParameterDerivationSet(
        id="drive-derivations",
        scalars=[
            ScalarParameterDerivation(
                id="drive.center_frequency",
                expression=param("drive.lo_frequency")
                + Quantity(value=100, unit="MHz"),
            )
        ],
        tables=[
            TableParameterDerivation(
                id="drive_plan",
                relation=table("drive_channels")
                .with_columns(
                    carrier_frequency=param("drive.lo_frequency") + col("fixed_if")
                )
                .select("channel_id", "resource_id", "carrier_frequency"),
            )
        ],
    )


def _system() -> SystemSpec:
    return SystemSpec(
        id="system",
        workspace_id="workspace",
        primary_entity_id="sample",
        topology=Topology(devices=[]),
        instrument_registry=InstrumentRegistry(instruments=[]),
        parameter_catalog=ParameterCatalog(id="catalog"),
    )


def _is_sha256(value: str) -> bool:
    prefix = "sha256:"
    return value.startswith(prefix) and len(value.removeprefix(prefix)) == 64
