"""Binary payload used only to inject traces into the virtual bench plant."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scopecat.sdk.payloads import PayloadCodec

VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID = "reference_lab.virtual_capture_queue.v2"


@dataclass(frozen=True, slots=True)
class DecodedVirtualCaptureTrace:
    instrument_id: str
    component_path: tuple[str, ...]
    samples: NDArray[np.float64] = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class DecodedVirtualCapture:
    traces: tuple[DecodedVirtualCaptureTrace, ...]


@dataclass(frozen=True, slots=True)
class DecodedVirtualCaptureQueue:
    captures: tuple[DecodedVirtualCapture, ...]


def virtual_capture_queue_codec() -> PayloadCodec:
    """Return the worker/client codec for the virtual plant input."""

    return PayloadCodec(
        id="reference_lab.virtual-capture-queue-float64",
        version=2,
        media_type="application/vnd.scopecat.capture-queue+float64",
        encoder=_encode_virtual_capture_queue,
        decoder=_decode_virtual_capture_queue,
    )


def _encode_virtual_capture_queue(value: object) -> bytes:
    document = cast("dict[str, object]", value)
    encoded_captures: list[dict[str, object]] = []
    sample_bodies: list[bytes] = []
    for capture in cast("list[dict[str, object]]", document["captures"]):
        encoded_traces: list[dict[str, object]] = []
        for trace in cast("list[dict[str, object]]", capture["traces"]):
            samples = np.ascontiguousarray(trace["samples"], dtype="<f8")
            encoded_traces.append(
                {
                    "instrument_id": trace["instrument_id"],
                    "component_path": trace["component_path"],
                    "sample_count": int(samples.size),
                }
            )
            sample_bodies.append(samples.tobytes())
        encoded_captures.append({"traces": encoded_traces})
    header = json.dumps(
        {"captures": encoded_captures},
        separators=(",", ":"),
    ).encode("utf-8")
    return b"".join((struct.pack("<Q", len(header)), header, *sample_bodies))


def _decode_virtual_capture_queue(content: bytes) -> object:
    header_size = struct.unpack_from("<Q", content)[0]
    body_offset = 8 + header_size
    document = cast(
        "dict[str, object]",
        json.loads(content[8:body_offset]),
    )
    captures: list[DecodedVirtualCapture] = []
    for capture in cast("list[dict[str, object]]", document["captures"]):
        traces: list[DecodedVirtualCaptureTrace] = []
        for trace in cast("list[dict[str, object]]", capture["traces"]):
            sample_count = cast("int", trace["sample_count"])
            samples = np.frombuffer(
                content,
                dtype="<f8",
                count=sample_count,
                offset=body_offset,
            )
            body_offset += samples.nbytes
            traces.append(
                DecodedVirtualCaptureTrace(
                    instrument_id=cast("str", trace["instrument_id"]),
                    component_path=tuple(cast("list[str]", trace["component_path"])),
                    samples=samples,
                )
            )
        captures.append(DecodedVirtualCapture(traces=tuple(traces)))
    return DecodedVirtualCaptureQueue(captures=tuple(captures))


__all__ = [
    "VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID",
    "DecodedVirtualCapture",
    "DecodedVirtualCaptureQueue",
    "DecodedVirtualCaptureTrace",
    "virtual_capture_queue_codec",
]
