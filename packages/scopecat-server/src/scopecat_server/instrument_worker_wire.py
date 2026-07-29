"""JSON descriptors and raw attachment frames for driver invocations."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.sdk.instruments.backend import (
    BackendInvokeRequest,
    BackendOperationArgument,
    BackendPayload,
)

type _NonEmptyText = Annotated[str, Field(min_length=1)]
type _Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]

INVOKE_WIRE_VERSION = 1


class WorkerWireError(ValueError):
    """An invocation frame set is invalid or exceeds transport limits."""


@dataclass(frozen=True, slots=True)
class WireLimits:
    max_header_bytes: int = 1 * 1024 * 1024
    max_attachments: int = 256
    max_attachment_bytes: int = 128 * 1024 * 1024
    max_total_attachment_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        if (
            self.max_header_bytes < 1
            or self.max_attachments < 1
            or self.max_attachment_bytes < 1
            or self.max_total_attachment_bytes < 1
        ):
            raise ValueError("worker wire limits must be positive")


DEFAULT_WIRE_LIMITS = WireLimits()


@dataclass(frozen=True, slots=True)
class InvokeFrames:
    header: bytes
    attachments: tuple[bytes, ...]


class _WireModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        allow_inf_nan=False,
    )


class _InvokeDescriptor(_WireModel):
    interface_id: InterfaceId
    component_path: tuple[_NonEmptyText, ...] = ()
    operation_id: _NonEmptyText
    arguments: tuple[BackendOperationArgument, ...] = ()


class _PayloadDescriptor(_WireModel):
    id: _NonEmptyText
    schema_id: _NonEmptyText
    codec_id: _NonEmptyText
    codec_version: int = Field(ge=1)
    media_type: _NonEmptyText


class _AttachmentManifest(_WireModel):
    index: int = Field(ge=0)
    payload_id: _NonEmptyText
    size_bytes: int = Field(ge=0)
    sha256: _Sha256Hex


class _InvokeHeader(_WireModel):
    protocol_version: Literal[1]
    request: _InvokeDescriptor
    payloads: tuple[_PayloadDescriptor, ...] = ()
    attachments: tuple[_AttachmentManifest, ...] = ()

    @model_validator(mode="after")
    def validate_payload_order(self) -> _InvokeHeader:
        payload_ids = tuple(payload.id for payload in self.payloads)
        if len(payload_ids) != len(set(payload_ids)):
            raise ValueError("worker payload ids must be unique")
        expected = tuple(range(len(self.payloads)))
        if tuple(item.index for item in self.attachments) != expected:
            raise ValueError("worker attachment indexes are out of order")
        if tuple(item.payload_id for item in self.attachments) != payload_ids:
            raise ValueError("worker attachment order does not match payloads")
        return self


def split_invoke_request(
    request: BackendInvokeRequest,
    *,
    limits: WireLimits = DEFAULT_WIRE_LIMITS,
) -> InvokeFrames:
    selected = tuple(sorted(request.payloads.items()))
    payloads: list[_PayloadDescriptor] = []
    manifests: list[_AttachmentManifest] = []
    attachments: list[bytes] = []
    for index, (_, payload) in enumerate(selected):
        content = payload.content
        payloads.append(
            _PayloadDescriptor(
                id=payload.id,
                schema_id=payload.schema_id,
                codec_id=payload.codec_id,
                codec_version=payload.codec_version,
                media_type=payload.media_type,
            )
        )
        manifests.append(
            _AttachmentManifest(
                index=index,
                payload_id=payload.id,
                size_bytes=len(content),
                sha256=sha256(content).hexdigest(),
            )
        )
        attachments.append(content)

    header = _InvokeHeader(
        protocol_version=INVOKE_WIRE_VERSION,
        request=_InvokeDescriptor(
            interface_id=request.interface_id,
            component_path=request.component_path,
            operation_id=request.operation_id,
            arguments=request.arguments,
        ),
        payloads=tuple(payloads),
        attachments=tuple(manifests),
    )
    header_bytes = json.dumps(
        header.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    frames = InvokeFrames(
        header=header_bytes,
        attachments=tuple(attachments),
    )
    _validate_limits(header, frames, limits=limits)
    return frames


def join_invoke_request(
    header: bytes,
    attachments: Sequence[bytes],
    *,
    limits: WireLimits = DEFAULT_WIRE_LIMITS,
) -> BackendInvokeRequest:
    if len(header) > limits.max_header_bytes:
        raise WorkerWireError("worker invoke header exceeds its size limit")
    try:
        descriptor = _InvokeHeader.model_validate_json(header)
    except ValidationError as error:
        raise WorkerWireError("invalid worker invoke header") from error

    frames = InvokeFrames(header=header, attachments=tuple(attachments))
    _validate_limits(descriptor, frames, limits=limits)
    if len(frames.attachments) != len(descriptor.attachments):
        raise WorkerWireError("worker attachment count does not match its manifest")

    payloads: dict[str, BackendPayload] = {}
    for payload, manifest, content in zip(
        descriptor.payloads,
        descriptor.attachments,
        frames.attachments,
        strict=True,
    ):
        if len(content) != manifest.size_bytes:
            raise WorkerWireError(
                f"worker attachment length mismatch for payload {payload.id!r}"
            )
        if sha256(content).hexdigest() != manifest.sha256:
            raise WorkerWireError(
                f"worker attachment hash mismatch for payload {payload.id!r}"
            )
        payloads[payload.id] = BackendPayload(
            id=payload.id,
            schema_id=payload.schema_id,
            codec_id=payload.codec_id,
            codec_version=payload.codec_version,
            media_type=payload.media_type,
            content=content,
        )

    try:
        return BackendInvokeRequest(
            interface_id=descriptor.request.interface_id,
            component_path=descriptor.request.component_path,
            operation_id=descriptor.request.operation_id,
            arguments=descriptor.request.arguments,
            payloads=payloads,
        )
    except ValidationError as error:
        raise WorkerWireError("invalid worker invoke request") from error


def _validate_limits(
    header: _InvokeHeader,
    frames: InvokeFrames,
    *,
    limits: WireLimits,
) -> None:
    if len(frames.header) > limits.max_header_bytes:
        raise WorkerWireError("worker invoke header exceeds its size limit")
    if len(header.attachments) > limits.max_attachments:
        raise WorkerWireError("worker attachment count exceeds its limit")

    declared_total = 0
    for manifest in header.attachments:
        if manifest.size_bytes > limits.max_attachment_bytes:
            raise WorkerWireError("worker attachment exceeds its size limit")
        declared_total += manifest.size_bytes
    if declared_total > limits.max_total_attachment_bytes:
        raise WorkerWireError("worker attachments exceed their total size limit")

    actual_total = 0
    for content in frames.attachments:
        if len(content) > limits.max_attachment_bytes:
            raise WorkerWireError("worker attachment exceeds its size limit")
        actual_total += len(content)
    if actual_total > limits.max_total_attachment_bytes:
        raise WorkerWireError("worker attachments exceed their total size limit")


__all__ = [
    "DEFAULT_WIRE_LIMITS",
    "INVOKE_WIRE_VERSION",
    "InvokeFrames",
    "WireLimits",
    "WorkerWireError",
    "join_invoke_request",
    "split_invoke_request",
]
