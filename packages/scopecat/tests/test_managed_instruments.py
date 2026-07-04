from __future__ import annotations

from pathlib import Path

from scopecat.instruments import (
    ManagedInstrument,
    ManagedInstrumentProvider,
    ProviderBuildContext,
    asset_field,
    capability,
)
from scopecat.instruments.executor import execute_run
from scopecat.instruments.sdk import InstrumentProviderContext
from scopecat.models.artifact import ExperimentAsset
from tests.support.managed_instruments import (
    ManagedSignalInstrument,
    asset_state,
    desired_field,
    load_config,
    quantity_state,
)
from tests.support.workflow_fixtures import load_experiment


def test_managed_instrument_generates_description_and_applies_state() -> None:
    instrument = ManagedSignalInstrument()
    desired = desired_field(
        capability_id="set_frequency",
        field_path="frequency",
        value=quantity_state(5.0, "GHz"),
    )

    description = instrument.describe()
    current = instrument.readback()
    patch = instrument.diff(current, desired)
    updated = instrument.apply(patch)
    no_change = instrument.diff(updated, desired)

    assert description.instrument_id == "source-0"
    assert description.capabilities[0].fields[0].id == "frequency"
    assert description.capabilities[0].fields[0].kind == "quantity"
    assert len(patch.fields) == 1
    assert instrument.applied[0].fields == tuple(patch.fields)
    assert updated.fields[0].value == quantity_state(5.0, "GHz")
    assert no_change.fields == []


def test_managed_instrument_validates_declared_field_shapes() -> None:
    instrument = ManagedSignalInstrument()

    unsupported = instrument.validate(
        desired_field(
            capability_id="set_frequency",
            field_path="amplitude",
            value=quantity_state(1.0, "GHz"),
        )
    )
    unit_mismatch = instrument.validate(
        desired_field(
            capability_id="set_frequency",
            field_path="frequency",
            value=quantity_state(1.0, "ns"),
        )
    )
    kind_mismatch = instrument.validate(
        desired_field(
            capability_id="set_gain",
            field_path="gain",
            value=quantity_state(1.0, "GHz"),
        )
    )

    assert unsupported[0].code == "managed_instrument_unsupported_field"
    assert unit_mismatch[0].code == "managed_instrument_unit_mismatch"
    assert kind_mismatch[0].code == "managed_instrument_field_kind_mismatch"


def test_managed_instrument_validates_asset_references_and_kinds() -> None:
    asset = ExperimentAsset(
        id="program-a",
        kind="pulse_program",
        uri="scopecat-asset:program-a",
    )
    instrument = ManagedInstrument(
        instrument_id="source-0",
        implementation_id="tests.managed_asset",
        implementation_version="v0",
        capabilities=[
            capability(
                "play_program",
                fields=[asset_field("program", asset_kinds=("pulse_program",))],
            )
        ],
        asset_catalog={asset.id: asset},
    )

    valid = instrument.validate(
        desired_field(
            capability_id="play_program",
            field_path="program",
            value=asset_state(asset.id),
        )
    )
    missing = instrument.validate(
        desired_field(
            capability_id="play_program",
            field_path="program",
            value=asset_state("missing-program"),
        )
    )
    wrong_kind = ManagedInstrument(
        instrument_id="source-0",
        implementation_id="tests.managed_asset",
        implementation_version="v0",
        capabilities=[
            capability(
                "play_program",
                fields=[asset_field("program", asset_kinds=("readout_program",))],
            )
        ],
        asset_catalog={asset.id: asset},
    ).validate(
        desired_field(
            capability_id="play_program",
            field_path="program",
            value=asset_state(asset.id),
        )
    )

    assert valid == []
    assert missing[0].code == "managed_instrument_unknown_asset"
    assert wrong_kind[0].code == "managed_instrument_asset_kind_mismatch"


def test_managed_provider_builds_fresh_instruments() -> None:
    def build(context: ProviderBuildContext):
        assert context.experiment.id == "simple-frequency-scan"
        return [ManagedSignalInstrument()]

    provider = ManagedInstrumentProvider(
        provider_id="tests.managed_provider",
        build=build,
        label="Managed provider",
        provided_instrument_ids=("source-0",),
        capabilities=("set_frequency", "scalar_signal"),
        metadata={"mode": "test_offline"},
    )
    first = provider.provide(
        InstrumentProviderContext(
            config=load_config(),
            experiment=load_experiment(),
        )
    )
    second = provider.provide(
        InstrumentProviderContext(
            config=load_config(),
            experiment=load_experiment(),
        )
    )

    assert provider.describe().provider_id == "tests.managed_provider"
    assert first.diagnostics == ()
    assert first.instruments[0] is not second.instruments[0]


def test_execute_run_accepts_managed_instrument(tmp_path: Path) -> None:
    instrument = ManagedSignalInstrument()

    manifest, snapshot = execute_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[instrument],
        workspace=tmp_path,
    )

    assert manifest.status == "completed"
    assert snapshot.instrument_ids == ["source-0"]
    assert snapshot.measurement_count == 3
    assert instrument.contexts[0].point_index == 0
    assert instrument.contexts[0].point_count == 3
    assert instrument.contexts[0].acquisition_kind == "scalar"
    assert instrument.contexts[0].record == "point"
    assert instrument.contexts[0].expected_schema is not None
    assert instrument.contexts[0].desired_state[0].capability_id == "set_frequency"
