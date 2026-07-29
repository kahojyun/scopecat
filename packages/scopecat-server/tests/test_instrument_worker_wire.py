from __future__ import annotations

import json
from dataclasses import replace
from typing import cast

import pytest
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.sdk.instruments.backend import (
    BackendInvokeRequest,
    BackendOperationArgument,
    BackendPayload,
)

from scopecat_server.instrument_worker_wire import (
    DEFAULT_WIRE_LIMITS,
    WorkerWireError,
    join_invoke_request,
    split_invoke_request,
)


def _payload(payload_id: str, content: bytes) -> BackendPayload:
    return BackendPayload(
        id=payload_id,
        schema_id=f"tests.{payload_id}/v1",
        codec_id="tests.binary",
        codec_version=2,
        media_type="application/octet-stream",
        content=content,
    )


def _request(*payloads: BackendPayload) -> BackendInvokeRequest:
    return BackendInvokeRequest(
        interface_id="tests.program_player/v1",
        component_path=("channel-a",),
        operation_id="play",
        arguments=tuple(
            BackendOperationArgument(
                id=f"argument-{payload.id}",
                value=StateValue(PayloadRef(payload_id=payload.id)),
            )
            for payload in payloads
        ),
        payloads={payload.id: payload for payload in reversed(payloads)},
    )


def _header_document(header: bytes) -> dict[str, object]:
    document: object = json.loads(header)
    assert isinstance(document, dict)
    return cast("dict[str, object]", document)


def _encode_header(document: dict[str, object]) -> bytes:
    return json.dumps(document, separators=(",", ":"), sort_keys=True).encode()


def test_invoke_wire_separates_json_descriptor_from_binary_content() -> None:
    request = _request(_payload("program", b"\x00\xffbinary\x00"))

    frames = split_invoke_request(request)
    document = json.loads(frames.header)

    assert frames.attachments == (b"\x00\xffbinary\x00",)
    assert set(document) == {
        "attachments",
        "payloads",
        "protocol_version",
        "request",
    }
    assert set(document["request"]) == {
        "arguments",
        "component_path",
        "interface_id",
        "operation_id",
    }
    assert set(document["payloads"][0]) == {
        "codec_id",
        "codec_version",
        "id",
        "media_type",
        "schema_id",
    }
    assert set(document["attachments"][0]) == {
        "index",
        "payload_id",
        "sha256",
        "size_bytes",
    }
    header_text = frames.header.decode()
    assert "content_base64" not in header_text
    assert '"body"' not in header_text
    assert "command_id" not in header_text
    assert "instrument_id" not in header_text
    assert "resource_id" not in header_text
    assert join_invoke_request(frames.header, frames.attachments) == request


def test_invoke_wire_orders_multiple_payload_attachments_by_id() -> None:
    first = _payload("alpha", b"\x00first")
    second = _payload("zeta", b"\xffsecond")
    request = _request(first, second)

    frames = split_invoke_request(request)
    document = json.loads(frames.header)
    restored = join_invoke_request(frames.header, frames.attachments)

    assert [payload["id"] for payload in document["payloads"]] == [
        "alpha",
        "zeta",
    ]
    assert [item["payload_id"] for item in document["attachments"]] == [
        "alpha",
        "zeta",
    ]
    assert frames.attachments == (first.content, second.content)
    assert restored == request


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_invoke_wire_rejects_missing_or_extra_attachments(change: str) -> None:
    frames = split_invoke_request(_request(_payload("program", b"content")))
    attachments = (
        frames.attachments[:-1]
        if change == "missing"
        else (*frames.attachments, b"unexpected")
    )

    with pytest.raises(WorkerWireError, match="count"):
        join_invoke_request(frames.header, attachments)


def test_invoke_wire_rejects_attachment_order_changes() -> None:
    request = _request(
        _payload("alpha", b"aaaa"),
        _payload("zeta", b"zzzz"),
    )
    frames = split_invoke_request(request)

    with pytest.raises(WorkerWireError, match="hash mismatch"):
        join_invoke_request(frames.header, tuple(reversed(frames.attachments)))


def test_invoke_wire_rejects_attachment_length_and_hash_tampering() -> None:
    frames = split_invoke_request(_request(_payload("program", b"payload")))

    with pytest.raises(WorkerWireError, match="length mismatch"):
        join_invoke_request(frames.header, (b"payloa",))
    with pytest.raises(WorkerWireError, match="hash mismatch"):
        join_invoke_request(frames.header, (b"payloae",))


def test_invoke_wire_rejects_unknown_version_and_public_provenance() -> None:
    frames = split_invoke_request(_request(_payload("program", b"payload")))
    wrong_version_document = _header_document(frames.header)
    wrong_version_document["protocol_version"] = 2
    wrong_version = _encode_header(wrong_version_document)
    provenance_document = _header_document(frames.header)
    request_document = provenance_document["request"]
    assert isinstance(request_document, dict)
    request_document["command_id"] = "invoke-1"
    with_provenance = _encode_header(provenance_document)

    with pytest.raises(WorkerWireError, match="invalid"):
        join_invoke_request(wrong_version, frames.attachments)
    with pytest.raises(WorkerWireError, match="invalid"):
        join_invoke_request(with_provenance, frames.attachments)


def test_invoke_wire_enforces_attachment_count_and_size_limits() -> None:
    two_frames = split_invoke_request(
        _request(
            _payload("alpha", b"abc"),
            _payload("zeta", b"def"),
        )
    )
    one_frame = split_invoke_request(_request(_payload("program", b"abcd")))

    with pytest.raises(WorkerWireError, match="count exceeds"):
        join_invoke_request(
            two_frames.header,
            two_frames.attachments,
            limits=replace(DEFAULT_WIRE_LIMITS, max_attachments=1),
        )
    with pytest.raises(WorkerWireError, match="attachment exceeds"):
        join_invoke_request(
            one_frame.header,
            one_frame.attachments,
            limits=replace(DEFAULT_WIRE_LIMITS, max_attachment_bytes=3),
        )
    with pytest.raises(WorkerWireError, match="total size"):
        join_invoke_request(
            two_frames.header,
            two_frames.attachments,
            limits=replace(DEFAULT_WIRE_LIMITS, max_total_attachment_bytes=5),
        )
