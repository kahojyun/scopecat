from __future__ import annotations

from collections.abc import Callable

import pytest
from pydantic import BaseModel, ValidationError

from scopecat.execution.ports.instruments import RunHardwareApply
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.records.artifact import CommandPayload, command_payload_from_bytes
from scopecat.sdk.instruments.contracts import (
    InstrumentStateCommand,
    InstrumentStateCommandField,
)

type _ConcretePayloadFactory = Callable[
    [tuple[InstrumentStateCommandField, ...], dict[str, CommandPayload]],
    BaseModel,
]


def _command(
    fields: tuple[InstrumentStateCommandField, ...],
    payloads: dict[str, CommandPayload],
) -> BaseModel:
    return InstrumentStateCommand(
        operation_id="apply-program",
        instrument_id="source-0",
        fields=list(fields),
        payloads=payloads,
    )


def _hardware_apply(
    fields: tuple[InstrumentStateCommandField, ...],
    payloads: dict[str, CommandPayload],
) -> BaseModel:
    return RunHardwareApply(
        effect_id="apply-program",
        point_index=0,
        instrument_id="source-0",
        fields=fields,
        payloads=payloads,
    )


_CONCRETE_FACTORIES = (_command, _hardware_apply)


def _payload() -> CommandPayload:
    return command_payload_from_bytes(
        id="program-a",
        schema_id="tests.program/v1",
        codec_id="tests.binary",
        codec_version=1,
        media_type="application/octet-stream",
        content=b"program",
    )


def _field(value: StateValue) -> InstrumentStateCommandField:
    return InstrumentStateCommandField(
        resource_id="source-0",
        capability_id="play_program",
        field_path="program",
        value=value,
    )


@pytest.mark.parametrize("factory", _CONCRETE_FACTORIES)
def test_concrete_payload_map_accepts_exact_references(
    factory: _ConcretePayloadFactory,
) -> None:
    payload = _payload()

    model = factory(
        (_field(StateValue(PayloadRef(payload_id=payload.id))),),
        {payload.id: payload},
    )

    assert model is not None


@pytest.mark.parametrize("factory", _CONCRETE_FACTORIES)
def test_concrete_payload_map_rejects_key_id_mismatch(
    factory: _ConcretePayloadFactory,
) -> None:
    payload = _payload()

    with pytest.raises(ValidationError, match=r"does not match payload\.id"):
        factory(
            (_field(StateValue(PayloadRef(payload_id="alias"))),),
            {"alias": payload},
        )


@pytest.mark.parametrize("factory", _CONCRETE_FACTORIES)
def test_concrete_payload_map_rejects_missing_referenced_payload(
    factory: _ConcretePayloadFactory,
) -> None:
    payload = _payload()

    with pytest.raises(ValidationError, match="missing referenced payload ids"):
        factory(
            (_field(StateValue(PayloadRef(payload_id=payload.id))),),
            {},
        )


@pytest.mark.parametrize("factory", _CONCRETE_FACTORIES)
def test_concrete_payload_map_rejects_unreferenced_payload(
    factory: _ConcretePayloadFactory,
) -> None:
    payload = _payload()

    with pytest.raises(ValidationError, match="unreferenced payload ids"):
        factory(
            (_field(StateValue(1.0)),),
            {payload.id: payload},
        )
