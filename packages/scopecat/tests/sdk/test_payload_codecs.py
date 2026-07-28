from __future__ import annotations

import json

import pytest

from scopecat.records.artifact import command_payload_from_bytes
from scopecat.sdk.payloads import (
    PayloadCodec,
    PayloadCodecCatalog,
    PayloadCodecRegistry,
)


def _json_encoder(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _json_decoder(content: bytes) -> object:
    return json.loads(content)


def _registry() -> PayloadCodecRegistry:
    return PayloadCodecRegistry(
        {
            "tests.program/v1": PayloadCodec(
                id="tests.canonical-json",
                version=2,
                media_type="application/json",
                encoder=_json_encoder,
                decoder=_json_decoder,
            )
        }
    )


def test_payload_codec_registry_round_trips_encoded_command_payload() -> None:
    registry = _registry()
    value = {"samples": [0.0, 1.0], "enabled": True}

    encoded = registry.encode("tests.program/v1", value)
    payload = command_payload_from_bytes(
        id="program-a",
        schema_id=encoded.schema_id,
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    )

    assert payload.inline_bytes() == encoded.content
    assert registry.validate_descriptor(payload) is registry["tests.program/v1"]
    assert registry.decode(payload) == value


def test_payload_codec_catalog_is_stable_serializable_and_has_no_callables() -> None:
    registry = _registry()

    catalog = registry.catalog

    assert PayloadCodecCatalog.model_validate_json(catalog.model_dump_json()) == catalog
    assert catalog.model_dump(mode="json") == {
        "codecs": [
            {
                "schema_id": "tests.program/v1",
                "codec_id": "tests.canonical-json",
                "codec_version": 2,
                "media_type": "application/json",
            }
        ]
    }
    assert (
        catalog.validate_descriptor(
            command_payload_from_bytes(
                id="program-a",
                schema_id="tests.program/v1",
                codec_id="tests.canonical-json",
                codec_version=2,
                media_type="application/json",
                content=b"{}",
            )
        )
        == catalog.codecs[0]
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("codec_id", "tests.other-codec"),
        ("codec_version", 3),
        ("media_type", "application/octet-stream"),
    ],
)
def test_payload_codec_registry_rejects_descriptor_mismatch(
    field: str,
    value: str | int,
) -> None:
    registry = _registry()
    encoded = registry.encode("tests.program/v1", {"program": 1})
    payload = command_payload_from_bytes(
        id="program-a",
        schema_id=encoded.schema_id,
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    ).model_copy(update={field: value})

    with pytest.raises(ValueError, match=f"{field} mismatch"):
        registry.validate_descriptor(payload)


def test_payload_descriptor_validation_does_not_materialize_blob_content() -> None:
    registry = _registry()
    encoded = registry.encode("tests.program/v1", {"program": 1})
    inline = command_payload_from_bytes(
        id="program-a",
        schema_id=encoded.schema_id,
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    )
    blob = command_payload_from_bytes(
        id=inline.id,
        schema_id=inline.schema_id,
        codec_id=inline.codec_id,
        codec_version=inline.codec_version,
        media_type=inline.media_type,
        content=encoded.content,
        blob_ref=inline.content_hash,
    )

    assert registry.validate_descriptor(blob) is registry["tests.program/v1"]
    with pytest.raises(ValueError, match="must be resolved"):
        registry.decode(blob)


def test_payload_descriptor_validation_requires_registered_schema() -> None:
    registry = _registry()
    encoded = registry.encode("tests.program/v1", {"program": 1})
    payload = command_payload_from_bytes(
        id="program-a",
        schema_id="tests.unknown/v1",
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    )

    with pytest.raises(LookupError, match="no payload codec registered"):
        registry.validate_descriptor(payload)


def test_payload_codec_registry_requires_explicit_schema_registration() -> None:
    registry = _registry()

    with pytest.raises(LookupError, match="no payload codec registered"):
        registry.encode("tests.unknown/v1", object())
