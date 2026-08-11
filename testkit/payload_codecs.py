"""Explicit payload codecs used by execution integration tests."""

from __future__ import annotations

import json

from pydantic import BaseModel

from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry


def json_payload_codecs(*schema_ids: str) -> PayloadCodecRegistry:
    codec = PayloadCodec(
        id="tests.canonical-json",
        version=1,
        media_type="application/json",
        encoder=_encode_json,
        decoder=json.loads,
    )
    return PayloadCodecRegistry(dict.fromkeys(schema_ids, codec))


def _encode_json(value: object) -> bytes:
    return json.dumps(
        value,
        default=_json_default,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _json_default(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    raise TypeError(f"{type(value).__qualname__} is not supported by the test codec")


__all__ = ["json_payload_codecs"]
