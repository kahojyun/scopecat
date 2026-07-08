from __future__ import annotations

from pathlib import Path

from scopecat._runtime.executor import execute_run
from scopecat.instruments import (
    InstrumentDescription,
    InstrumentProviderContext,
    InstrumentProviderDescription,
    InstrumentProviderResult,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    InstrumentStateSnapshot,
    apply_state_command_to_snapshot,
    capability,
    payload_field,
    validate_state_command,
)
from scopecat.models.artifact import CommandPayload
from tests.support.instrument_drivers import (
    SignalInstrumentDriver,
    load_config,
    payload_state,
    quantity_state,
)
from tests.support.workflow_fixtures import load_experiment


def test_instrument_driver_generates_description_and_applies_state() -> None:
    instrument = SignalInstrumentDriver()
    command = _state_command(
        capability_id="set_frequency",
        field_path="frequency",
        value=quantity_state(5.0, "GHz"),
    )

    description = instrument.describe()
    current = instrument.read_state()
    result = instrument.apply_state(command)
    updated = apply_state_command_to_snapshot(current, command)
    no_change = _changed_state_command(updated, command)

    assert description.instrument_id == "source-0"
    assert description.capabilities[0].fields[0].id == "frequency"
    assert description.capabilities[0].fields[0].kind == "quantity"
    assert result.diagnostics == []
    assert instrument.applied[0] == command
    assert updated.fields[0].value == quantity_state(5.0, "GHz")
    assert no_change.fields == []


def test_instrument_driver_validator_checks_declared_field_shapes() -> None:
    description = SignalInstrumentDriver().describe()

    unsupported = validate_state_command(
        command=_state_command(
            capability_id="set_frequency",
            field_path="amplitude",
            value=quantity_state(1.0, "GHz"),
        ),
        description=description,
    )
    unit_mismatch = validate_state_command(
        command=_state_command(
            capability_id="set_frequency",
            field_path="frequency",
            value=quantity_state(1.0, "ns"),
        ),
        description=description,
    )
    kind_mismatch = validate_state_command(
        command=_state_command(
            capability_id="set_gain",
            field_path="gain",
            value=quantity_state(1.0, "GHz"),
        ),
        description=description,
    )

    assert unsupported[0].code == "instrument_driver_unsupported_field"
    assert unit_mismatch[0].code == "instrument_driver_unit_mismatch"
    assert kind_mismatch[0].code == "instrument_driver_field_kind_mismatch"


def test_instrument_driver_validator_checks_payload_references_and_kinds() -> None:
    payload = CommandPayload(
        id="program-a",
        kind="pulse_program",
        payload={"samples": [0.0]},
    )
    description = InstrumentDescription(
        instrument_id="source-0",
        implementation_id="tests.payload_driver",
        implementation_version="v0",
        capabilities=[
            capability(
                "play_program",
                fields=[payload_field("program", payload_kinds=("pulse_program",))],
            )
        ],
    )
    wrong_kind_description = description.model_copy(
        update={
            "capabilities": [
                capability(
                    "play_program",
                    fields=[
                        payload_field("program", payload_kinds=("readout_program",))
                    ],
                )
            ]
        }
    )

    valid = validate_state_command(
        command=_state_command(
            capability_id="play_program",
            field_path="program",
            value=payload_state(payload.id),
        ),
        description=description,
        payloads={payload.id: payload},
    )
    command_payload = validate_state_command(
        command=_state_command(
            capability_id="play_program",
            field_path="program",
            value=payload_state(payload.id),
            payloads={payload.id: payload},
        ),
        description=description,
    )
    missing = validate_state_command(
        command=_state_command(
            capability_id="play_program",
            field_path="program",
            value=payload_state("missing-program"),
        ),
        description=description,
        payloads={payload.id: payload},
    )
    wrong_kind = validate_state_command(
        command=_state_command(
            capability_id="play_program",
            field_path="program",
            value=payload_state(payload.id),
        ),
        description=wrong_kind_description,
        payloads={payload.id: payload},
    )

    assert valid == []
    assert command_payload == []
    assert missing[0].code == "instrument_driver_unknown_payload"
    assert wrong_kind[0].code == "instrument_driver_payload_kind_mismatch"


def test_provider_builds_fresh_drivers() -> None:
    class Provider:
        @property
        def provider_id(self) -> str:
            return "tests.driver_provider"

        def describe(self) -> InstrumentProviderDescription:
            return InstrumentProviderDescription(
                provider_id=self.provider_id,
                label="Driver provider",
                provided_instrument_ids=("source-0",),
                capabilities=("set_frequency", "scalar_signal"),
                metadata={"mode": "test_offline"},
            )

        def provide(
            self, context: InstrumentProviderContext
        ) -> InstrumentProviderResult:
            assert context.config.workspace_id == "example-workspace"
            return InstrumentProviderResult(drivers=(SignalInstrumentDriver(),))

    provider = Provider()
    first = provider.provide(InstrumentProviderContext(config=load_config()))
    second = provider.provide(InstrumentProviderContext(config=load_config()))

    assert provider.describe().provider_id == "tests.driver_provider"
    assert first.diagnostics == ()
    assert first.drivers[0] is not second.drivers[0]


def test_execute_run_accepts_instrument_driver(tmp_path: Path) -> None:
    instrument = SignalInstrumentDriver()

    manifest, snapshot = execute_run(
        config=load_config(),
        experiment=load_experiment(),
        instruments=[instrument],
        workspace=tmp_path,
    )

    assert manifest.status == "completed"
    assert snapshot.instrument_ids == ["source-0"]
    assert snapshot.measurement_count == 3
    assert instrument.collect_commands[0].point_index == 0
    assert instrument.collect_commands[0].point_count == 3
    assert [request.id for request in instrument.collect_commands[0].requests] == [
        "signal"
    ]
    assert instrument.applied[0].fields[0].capability_id == "set_frequency"


def _state_command(
    *,
    capability_id: str,
    field_path: str,
    value,
    payloads: dict[str, CommandPayload] | None = None,
) -> InstrumentStateCommand:
    return InstrumentStateCommand(
        instrument_id="source-0",
        fields=[
            InstrumentStateCommandField(
                resource_id="source-0",
                capability_id=capability_id,
                field_path=field_path,
                value=value,
            )
        ],
        payloads=payloads or {},
    )


def _changed_state_command(
    snapshot: InstrumentStateSnapshot,
    command: InstrumentStateCommand,
) -> InstrumentStateCommand:
    current = {
        (field.capability_id, field.field_path): field.value
        for field in snapshot.fields
    }
    return InstrumentStateCommand(
        instrument_id=command.instrument_id,
        fields=[
            field
            for field in command.fields
            if current.get((field.capability_id, field.field_path)) != field.value
        ],
    )
