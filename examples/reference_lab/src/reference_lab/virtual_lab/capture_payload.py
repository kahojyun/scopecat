"""Payload model used only to inject traces into the virtual bench plant."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field
from scopecat.sdk.payloads import PayloadCodec

VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID = "reference_lab.virtual_capture_queue.v1"


@dataclass(frozen=True, slots=True)
class DecodedVirtualCaptureTrace:
    instrument_id: str
    component_path: tuple[str, ...]
    samples: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class DecodedVirtualCapture:
    traces: tuple[DecodedVirtualCaptureTrace, ...]


@dataclass(frozen=True, slots=True)
class DecodedVirtualCaptureQueue:
    captures: tuple[DecodedVirtualCapture, ...]


class _VirtualCaptureTraceDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    component_path: tuple[str, ...] = Field(min_length=1)
    samples: tuple[float, ...] = Field(min_length=1)


class _VirtualCaptureDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    traces: tuple[_VirtualCaptureTraceDocument, ...] = ()


class _VirtualCaptureQueueDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    captures: tuple[_VirtualCaptureDocument, ...] = Field(min_length=1)


def virtual_capture_queue_codec() -> PayloadCodec:
    """Return the worker/client codec for the virtual plant input."""

    return PayloadCodec(
        id="reference_lab.virtual-capture-queue-json",
        version=1,
        media_type="application/json",
        encoder=_encode_virtual_capture_queue,
        decoder=_decode_virtual_capture_queue,
    )


def _encode_virtual_capture_queue(value: object) -> bytes:
    document = _VirtualCaptureQueueDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_virtual_capture_queue(content: bytes) -> object:
    document = _VirtualCaptureQueueDocument.model_validate_json(content)
    return DecodedVirtualCaptureQueue(
        captures=tuple(
            DecodedVirtualCapture(
                traces=tuple(
                    DecodedVirtualCaptureTrace(
                        instrument_id=trace.instrument_id,
                        component_path=trace.component_path,
                        samples=trace.samples,
                    )
                    for trace in capture.traces
                )
            )
            for capture in document.captures
        )
    )


__all__ = [
    "VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID",
    "DecodedVirtualCapture",
    "DecodedVirtualCaptureQueue",
    "DecodedVirtualCaptureTrace",
    "virtual_capture_queue_codec",
]
