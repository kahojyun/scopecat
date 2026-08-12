from __future__ import annotations

import pytest
from pydantic import ValidationError

from scopecat.kernel.content_identity import sha256_content_hash
from scopecat.records.artifact import (
    BlobPayloadBody,
    CommandPayload,
    InlinePayloadBody,
    command_payload_from_bytes,
)

_CONTENT = b"\x00\xffopaque payload\x00"


def _inline_payload() -> CommandPayload:
    return command_payload_from_bytes(
        id="program-a",
        schema_id="tests.pulse_program/v1",
        codec_id="tests.binary",
        codec_version=1,
        media_type="application/octet-stream",
        content=_CONTENT,
    )


def test_inline_command_payload_round_trips_exact_bytes_over_json() -> None:
    payload = _inline_payload()
    assert isinstance(payload.body, InlinePayloadBody)

    assert payload.body.content is _CONTENT
    assert payload.body.model_dump(mode="python")["content_base64"] is _CONTENT

    restored = CommandPayload.model_validate_json(payload.model_dump_json())

    assert restored == payload
    assert restored.inline_bytes() == _CONTENT
    assert restored.content_hash == sha256_content_hash(_CONTENT)
    assert restored.size_bytes == len(_CONTENT)
    assert isinstance(restored.body, InlinePayloadBody)
    assert restored.model_dump(mode="json")["body"] == {
        "kind": "inline",
        "content_base64": "AP9vcGFxdWUgcGF5bG9hZAA=",
    }


def test_inline_payload_rejects_noncanonical_or_misidentified_content() -> None:
    wire = _inline_payload().model_dump(mode="json")

    with pytest.raises(ValidationError, match="valid base64"):
        CommandPayload.model_validate(
            {**wire, "body": {"kind": "inline", "content_base64": "***"}}
        )
    with pytest.raises(ValidationError, match="declared size_bytes"):
        CommandPayload.model_validate({**wire, "size_bytes": len(_CONTENT) + 1})
    with pytest.raises(ValidationError, match="declared content_hash"):
        CommandPayload.model_validate({**wire, "content_hash": "sha256:" + "0" * 64})


def test_blob_payload_is_content_addressed_and_requires_resolution() -> None:
    content_hash = sha256_content_hash(_CONTENT)
    payload = command_payload_from_bytes(
        id="program-blob",
        schema_id="tests.pulse_program/v1",
        codec_id="tests.binary",
        codec_version=1,
        media_type="application/octet-stream",
        content=_CONTENT,
        blob_ref=content_hash,
    )

    assert isinstance(payload.body, BlobPayloadBody)
    assert payload.body.ref == payload.content_hash
    payload.verify_content(_CONTENT)
    with pytest.raises(ValueError, match="must be resolved"):
        payload.inline_bytes()

    wire = payload.model_dump(mode="json")
    with pytest.raises(ValidationError, match="must equal content_hash"):
        CommandPayload.model_validate(
            {
                **wire,
                "body": {"kind": "blob", "ref": "sha256:" + "1" * 64},
            }
        )


def test_command_payload_rejects_unmodeled_python_object_field() -> None:
    wire = _inline_payload().model_dump(mode="json")

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CommandPayload.model_validate({**wire, "payload": {"samples": [0.0]}})
