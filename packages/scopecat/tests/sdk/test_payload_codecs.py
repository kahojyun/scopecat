from __future__ import annotations

import json
from typing import Annotated, Literal, assert_type

import numpy as np
import pytest
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from scopecat.kernel.payloads import PayloadValue
from scopecat.records.content import command_payload_from_bytes
from scopecat.sdk.payloads import (
    PayloadCodec,
    PayloadCodecCatalog,
    PayloadCodecRegistry,
    PayloadContract,
)
from scopecat.sdk.structured_payloads import (
    STRUCTURED_PAYLOAD_MEDIA_TYPE,
    FrozenFloat64Vector,
    StructuredPayloadError,
    pydantic_buffer_bundle_codec,
)


class _ArrayProgram(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    id: str
    waveforms: tuple[np.ndarray, ...]
    metadata: dict[str, int]


class _FrozenVectorProgram(BaseModel):
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="forbid",
        frozen=True,
        strict=True,
    )

    samples: FrozenFloat64Vector


class _LeftProgram(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["left"]
    value: int


class _RightProgram(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["right"]
    label: str


type _ProgramVariant = Annotated[
    _LeftProgram | _RightProgram,
    Field(discriminator="kind"),
]


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


def test_payload_codec_registry_decodes_verified_external_content() -> None:
    registry = _registry()
    value = {"program": [1, 2, 3]}
    encoded = registry.encode("tests.program/v1", value)

    assert registry.decode_content(registry.catalog.codecs[0], encoded.content) == value


def test_command_payload_decode_still_verifies_content_identity() -> None:
    registry = _registry()
    encoded = registry.encode("tests.program/v1", {"program": 1})
    payload = command_payload_from_bytes(
        id="program-a",
        schema_id=encoded.schema_id,
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    ).model_copy(update={"content_hash": f"sha256:{'0' * 64}"})

    with pytest.raises(ValueError, match="content_hash"):
        registry.decode(payload)


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


def test_pydantic_buffer_bundle_codec_round_trips_immutable_numpy_buffers() -> None:
    contract = PayloadContract(
        schema_id="tests.array-program/v1",
        codec=pydantic_buffer_bundle_codec(_ArrayProgram),
    )
    registry = PayloadCodecRegistry.from_contracts(contract)
    value = _ArrayProgram(
        id="readout",
        waveforms=(
            np.asarray([0.25, -0.5], dtype=np.float64),
            np.asarray([1.0 + 2.0j, 3.0 - 4.0j], dtype=np.complex128),
        ),
        metadata={"shots": 16, "channels": 2},
    )

    assert_type(contract(value), PayloadValue)
    encoded = contract.encode(value)
    decoded = assert_type(contract.decode_content(encoded.content), _ArrayProgram)

    assert isinstance(decoded, _ArrayProgram)
    assert decoded.id == value.id
    assert decoded.metadata == value.metadata
    assert len(decoded.waveforms) == 2
    for actual, expected in zip(decoded.waveforms, value.waveforms, strict=True):
        assert np.array_equal(actual, expected)
        assert actual.dtype == expected.dtype
        assert actual.shape == expected.shape
        assert not actual.flags.writeable
    assert encoded.media_type == STRUCTURED_PAYLOAD_MEDIA_TYPE
    assert value.waveforms[0].tobytes() in encoded.content
    assert b"0.25" not in encoded.content

    payload = contract.command_payload("array-program", value)
    assert contract.decode(payload).id == value.id
    assert isinstance(registry.decode(payload), _ArrayProgram)


def test_payload_contract_rejects_mismatched_descriptor() -> None:
    contract = PayloadContract(
        schema_id="tests.array-program/v1",
        codec=pydantic_buffer_bundle_codec(_ArrayProgram),
    )
    encoded = contract.encode(_ArrayProgram(id="readout", waveforms=(), metadata={}))
    payload = command_payload_from_bytes(
        id="array-program",
        schema_id="tests.other/v1",
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    )

    with pytest.raises(ValueError, match="schema mismatch"):
        contract.decode(payload)


def test_frozen_float64_vector_snapshots_numeric_input() -> None:
    source = np.arange(4, dtype=np.int64)

    value = _FrozenVectorProgram.model_validate({"samples": source})
    source[0] = 99

    assert value.samples.dtype == np.dtype(np.float64)
    assert not value.samples.flags.writeable
    np.testing.assert_array_equal(value.samples, np.arange(4, dtype=np.float64))


def test_pydantic_buffer_bundle_codec_supports_discriminated_type_adapters() -> None:
    adapter = TypeAdapter[_ProgramVariant](_ProgramVariant)
    codec = pydantic_buffer_bundle_codec(adapter)
    value = _RightProgram(kind="right", label="selected")

    decoded = assert_type(codec.decoder(codec.encoder(value)), _ProgramVariant)

    assert isinstance(decoded, _RightProgram)
    assert decoded == value


def test_pydantic_buffer_bundle_codec_is_deterministic_for_mapping_order() -> None:
    codec = pydantic_buffer_bundle_codec(_ArrayProgram)
    waveform = np.arange(8, dtype=np.float64)
    left = _ArrayProgram(
        id="same",
        waveforms=(waveform,),
        metadata={"second": 2, "first": 1},
    )
    right = _ArrayProgram(
        id="same",
        waveforms=(waveform.copy(),),
        metadata={"first": 1, "second": 2},
    )

    assert codec.encoder(left) == codec.encoder(right)


def test_pydantic_buffer_bundle_codec_rejects_object_arrays_and_trailing_bytes() -> (
    None
):
    codec = pydantic_buffer_bundle_codec(_ArrayProgram)
    invalid = _ArrayProgram(
        id="objects",
        waveforms=(np.asarray([object()], dtype=object),),
        metadata={},
    )

    with pytest.raises(StructuredPayloadError, match="dtype object"):
        codec.encoder(invalid)

    encoded = codec.encoder(
        _ArrayProgram(
            id="valid",
            waveforms=(np.arange(4, dtype=np.int64),),
            metadata={},
        )
    )
    with pytest.raises(StructuredPayloadError, match="trailing array bytes"):
        codec.decoder(encoded + b"extra")
