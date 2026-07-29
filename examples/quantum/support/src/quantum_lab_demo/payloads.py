"""Pulse-program payload codec shared by planning and the instrument worker."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from pydantic import JsonValue, TypeAdapter
from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry

PULSE_PROGRAM_SCHEMA_ID = "pulse_program"
_JSON_VALUE: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


@dataclass(frozen=True, slots=True)
class DecodedPulseProgram:
    document: JsonValue = field(repr=False)


def quantum_lab_payload_codecs() -> PayloadCodecRegistry:
    return PayloadCodecRegistry(
        {
            PULSE_PROGRAM_SCHEMA_ID: PayloadCodec(
                id="quantum_lab_demo.canonical-json",
                version=1,
                media_type="application/json",
                encoder=_encode_pulse_program,
                decoder=_decode_pulse_program,
            )
        }
    )


def _encode_pulse_program(value: object) -> bytes:
    document = _JSON_VALUE.validate_python(value)
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _decode_pulse_program(content: bytes) -> object:
    return DecodedPulseProgram(document=_JSON_VALUE.validate_json(content))


__all__ = [
    "PULSE_PROGRAM_SCHEMA_ID",
    "DecodedPulseProgram",
    "quantum_lab_payload_codecs",
]
