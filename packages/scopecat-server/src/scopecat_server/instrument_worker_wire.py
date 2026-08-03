"""JSON descriptors and raw attachments for worker RPC frames."""

from __future__ import annotations

import json
import math
import sys
from array import array as PrimitiveArray
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from hashlib import sha256
from itertools import pairwise
from typing import Annotated, Literal, Protocol, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.problems import Problem
from scopecat.records._metadata import JsonMetadata
from scopecat.records.instrument import InstrumentReadback
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementDType,
    MeasurementScalar,
    MeasurementUnavailable,
)
from scopecat.sdk.instruments.backend import (
    BackendInvokeRequest,
    BackendOperationArgument,
    BackendPayload,
)
from scopecat.sdk.instruments.commands import CollectReceipt

type _NonEmptyText = Annotated[str, Field(min_length=1)]
type _Sha256Hex = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
type _ArrayExtent = Annotated[int, Field(ge=0)]

INVOKE_WIRE_VERSION = 1
COLLECT_WIRE_VERSION = 2
_MAX_ARRAY_RANK = 16
_MAX_ARRAY_CONTAINERS = 1_000_000


class WorkerWireError(ValueError):
    """A worker RPC frame set is invalid or exceeds transport limits."""


class _SizedAttachment(Protocol):
    size_bytes: int


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


@dataclass(frozen=True, slots=True)
class CollectFrames:
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


type _CollectInlineValue = Annotated[
    MeasurementScalar | MeasurementUnavailable,
    Field(discriminator="kind"),
]


class _CollectReadbackDescriptor(_WireModel):
    values: dict[str, _CollectInlineValue] = Field(default_factory=dict)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_unavailable_shapes(self) -> _CollectReadbackDescriptor:
        for value in self.values.values():
            if not isinstance(value, MeasurementUnavailable):
                continue
            if len(value.shape) > _MAX_ARRAY_RANK:
                raise ValueError("worker collect unavailable rank exceeds its limit")
            if any(extent is not None and extent < 0 for extent in value.shape):
                raise ValueError(
                    "worker collect unavailable shape extents must be non-negative"
                )
        return self


class _CollectReceiptDescriptor(_WireModel):
    status: Literal["collected", "not_collected", "unknown"]
    problems: tuple[Problem, ...] = ()
    readback: _CollectReadbackDescriptor | None = None
    metadata: JsonMetadata = Field(default_factory=dict)


class _CollectArrayDescriptor(_WireModel):
    request_id: _NonEmptyText
    dtype: MeasurementDType
    unit: str | None = None
    shape: tuple[_ArrayExtent, ...] = Field(min_length=1)
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("shape")
    @classmethod
    def validate_shape_cost(
        cls,
        value: tuple[int, ...],
    ) -> tuple[int, ...]:
        if len(value) > _MAX_ARRAY_RANK:
            raise ValueError("worker collect array rank exceeds its limit")
        containers = 1
        prefix_size = 1
        for extent in value[:-1]:
            prefix_size *= extent
            containers += prefix_size
            if containers > _MAX_ARRAY_CONTAINERS:
                raise ValueError(
                    "worker collect array container count exceeds its limit"
                )
        return value


class _CollectAttachmentManifest(_WireModel):
    index: int = Field(ge=0)
    request_id: _NonEmptyText
    size_bytes: int = Field(ge=0)
    sha256: _Sha256Hex


class _CollectHeader(_WireModel):
    protocol_version: Literal[2]
    receipt: _CollectReceiptDescriptor
    arrays: tuple[_CollectArrayDescriptor, ...] = ()
    attachments: tuple[_CollectAttachmentManifest, ...] = ()

    @model_validator(mode="after")
    def validate_attachment_order(self) -> _CollectHeader:
        request_ids = tuple(item.request_id for item in self.arrays)
        if len(request_ids) != len(set(request_ids)):
            raise ValueError("worker collect array request ids must be unique")
        if request_ids != tuple(sorted(request_ids)):
            raise ValueError("worker collect arrays are out of order")
        if tuple(item.index for item in self.attachments) != tuple(
            range(len(self.arrays))
        ):
            raise ValueError("worker collect attachment indexes are out of order")
        if tuple(item.request_id for item in self.attachments) != request_ids:
            raise ValueError(
                "worker collect attachment order does not match array requests"
            )
        if self.arrays and self.receipt.readback is None:
            raise ValueError("worker collect arrays require a readback")
        inline_ids: set[str] = (
            set[str]()
            if self.receipt.readback is None
            else set(self.receipt.readback.values)
        )
        if inline_ids & set(request_ids):
            raise ValueError("worker collect request ids must be unique")
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
    _validate_declared_attachment_limits(
        label="worker invoke",
        header=frames.header,
        manifests=header.attachments,
        limits=limits,
    )
    _validate_actual_attachment_limits(
        label="worker invoke",
        attachments=frames.attachments,
        limits=limits,
    )
    return frames


def join_invoke_request(
    header: bytes,
    attachments: Sequence[bytes],
    *,
    limits: WireLimits = DEFAULT_WIRE_LIMITS,
) -> BackendInvokeRequest:
    descriptor = _parse_invoke_header(header, limits=limits)

    frames = InvokeFrames(header=header, attachments=tuple(attachments))
    _validate_actual_attachment_limits(
        label="worker invoke",
        attachments=frames.attachments,
        limits=limits,
    )
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


def invoke_attachment_sizes(
    header: bytes,
    *,
    limits: WireLimits = DEFAULT_WIRE_LIMITS,
) -> tuple[int, ...]:
    """Validate an invoke header before receiving its declared attachments."""

    descriptor = _parse_invoke_header(header, limits=limits)
    return tuple(item.size_bytes for item in descriptor.attachments)


def split_collect_receipt(
    receipt: CollectReceipt,
    *,
    limits: WireLimits = DEFAULT_WIRE_LIMITS,
) -> CollectFrames:
    readback = receipt.readback
    inline_values: dict[str, MeasurementScalar | MeasurementUnavailable] = {}
    selected_arrays: list[tuple[str, MeasurementArray]] = []
    if readback is not None:
        for request_id, value in sorted(readback.values.items()):
            if isinstance(value, MeasurementArray):
                selected_arrays.append((request_id, value))
            else:
                inline_values[request_id] = value

    arrays: list[_CollectArrayDescriptor] = []
    manifests: list[_CollectAttachmentManifest] = []
    attachments: list[bytes] = []
    for index, (request_id, value) in enumerate(selected_arrays):
        content = _encode_measurement_array(value)
        arrays.append(
            _CollectArrayDescriptor(
                request_id=request_id,
                dtype=value.dtype,
                unit=value.unit,
                shape=tuple(value.shape),
                metadata=value.metadata,
            )
        )
        manifests.append(
            _CollectAttachmentManifest(
                index=index,
                request_id=request_id,
                size_bytes=len(content),
                sha256=sha256(content).hexdigest(),
            )
        )
        attachments.append(content)

    descriptor = _CollectReceiptDescriptor(
        status=receipt.status,
        problems=receipt.problems,
        readback=(
            None
            if readback is None
            else _CollectReadbackDescriptor(
                values=inline_values,
                metadata=readback.metadata,
            )
        ),
        metadata=receipt.metadata,
    )
    header = _CollectHeader(
        protocol_version=COLLECT_WIRE_VERSION,
        receipt=descriptor,
        arrays=tuple(arrays),
        attachments=tuple(manifests),
    )
    frames = CollectFrames(
        header=json.dumps(
            header.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8"),
        attachments=tuple(attachments),
    )
    _validate_declared_attachment_limits(
        label="worker collect",
        header=frames.header,
        manifests=header.attachments,
        limits=limits,
    )
    _validate_actual_attachment_limits(
        label="worker collect",
        attachments=frames.attachments,
        limits=limits,
    )
    return frames


def join_collect_receipt(
    header: bytes,
    attachments: Sequence[bytes],
    *,
    limits: WireLimits = DEFAULT_WIRE_LIMITS,
) -> CollectReceipt:
    descriptor = _parse_collect_header(header, limits=limits)

    frames = CollectFrames(header=header, attachments=tuple(attachments))
    _validate_actual_attachment_limits(
        label="worker collect",
        attachments=frames.attachments,
        limits=limits,
    )
    if len(frames.attachments) != len(descriptor.attachments):
        raise WorkerWireError(
            "worker collect attachment count does not match its manifest"
        )

    array_values: dict[str, MeasurementArray] = {}
    for array_descriptor, manifest, content in zip(
        descriptor.arrays,
        descriptor.attachments,
        frames.attachments,
        strict=True,
    ):
        if len(content) != manifest.size_bytes:
            raise WorkerWireError(
                "worker collect attachment length mismatch for request "
                f"{array_descriptor.request_id!r}"
            )
        if sha256(content).hexdigest() != manifest.sha256:
            raise WorkerWireError(
                "worker collect attachment hash mismatch for request "
                f"{array_descriptor.request_id!r}"
            )
        array_values[array_descriptor.request_id] = _decode_measurement_array(
            array_descriptor,
            content,
        )

    receipt = descriptor.receipt
    readback: InstrumentReadback | None = None
    if receipt.readback is not None:
        values = dict(
            sorted(
                (
                    *receipt.readback.values.items(),
                    *array_values.items(),
                )
            )
        )
        readback = InstrumentReadback(
            values=values,
            metadata=receipt.readback.metadata,
        )
    try:
        return CollectReceipt(
            status=receipt.status,
            problems=receipt.problems,
            readback=readback,
            metadata=receipt.metadata,
        )
    except ValidationError as error:
        raise WorkerWireError("invalid worker collect receipt") from error


def collect_attachment_sizes(
    header: bytes,
    *,
    limits: WireLimits = DEFAULT_WIRE_LIMITS,
) -> tuple[int, ...]:
    """Validate a collect header before receiving its declared attachments."""

    descriptor = _parse_collect_header(header, limits=limits)
    return tuple(item.size_bytes for item in descriptor.attachments)


def _encode_measurement_array(value: MeasurementArray) -> bytes:
    leaves = _flatten_measurement_values(value.values)
    expected_count = math.prod(value.shape)
    if len(leaves) != expected_count:
        raise WorkerWireError("worker collect array shape does not match its values")
    try:
        if value.dtype == "float64":
            return _encode_primitive_array(
                "d",
                (_require_float(item) for item in leaves),
            )
        if value.dtype == "int64":
            return _encode_primitive_array(
                "q",
                (_require_int(item) for item in leaves),
            )
        if value.dtype == "complex128":
            return _encode_primitive_array(
                "d",
                (
                    part
                    for item in leaves
                    for component in (_require_complex(item),)
                    for part in (component.real, component.imag)
                ),
            )
        if value.dtype == "bool":
            return _encode_primitive_array(
                "B",
                (_require_bool(item) for item in leaves),
            )
        return _encode_strings(leaves)
    except OverflowError as error:
        raise WorkerWireError("worker collect array value is out of range") from error


def _decode_measurement_array(
    descriptor: _CollectArrayDescriptor,
    content: bytes,
) -> MeasurementArray:
    count = math.prod(descriptor.shape)
    if descriptor.dtype == "float64":
        leaves: tuple[object, ...] = _decode_primitive_array(
            content,
            count=count,
            typecode="d",
        )
    elif descriptor.dtype == "int64":
        leaves = _decode_primitive_array(content, count=count, typecode="q")
    elif descriptor.dtype == "complex128":
        components = _decode_primitive_array(
            content,
            count=count * 2,
            typecode="d",
        )
        leaves = tuple(
            ComplexComponents(
                real=cast("float", components[index]),
                imag=cast("float", components[index + 1]),
            )
            for index in range(0, len(components), 2)
        )
    elif descriptor.dtype == "bool":
        raw_bools = _decode_primitive_array(
            content,
            count=count,
            typecode="B",
        )
        if any(item not in (0, 1) for item in raw_bools):
            raise WorkerWireError("worker collect bool attachment is invalid")
        leaves = tuple(bool(item) for item in raw_bools)
    else:
        leaves = _decode_strings(content, count=count)

    try:
        return MeasurementArray.create(
            dtype=descriptor.dtype,
            unit=descriptor.unit,
            shape=descriptor.shape,
            values=_reshape_measurement_values(leaves, descriptor.shape),
            metadata=descriptor.metadata,
        )
    except ValidationError as error:
        raise WorkerWireError("invalid worker collect array attachment") from error


def _flatten_measurement_values(values: object) -> tuple[object, ...]:
    flattened: list[object] = []

    def append(value: object) -> None:
        if isinstance(value, tuple):
            for item in cast("tuple[object, ...]", value):
                append(item)
            return
        flattened.append(value)

    append(values)
    return tuple(flattened)


def _reshape_measurement_values(
    values: tuple[object, ...],
    shape: Sequence[int],
) -> tuple[object, ...]:
    position = 0

    def consume(axis: int) -> tuple[object, ...]:
        nonlocal position
        size = shape[axis]
        if axis == len(shape) - 1:
            selected = values[position : position + size]
            position += size
            return selected
        return tuple(consume(axis + 1) for _ in range(size))

    restored = consume(0)
    if position != len(values):
        raise WorkerWireError("worker collect attachment has excess values")
    return restored


def _encode_primitive_array(
    typecode: Literal["B", "d", "q", "Q"],
    values: Iterable[int | float],
) -> bytes:
    selected: PrimitiveArray[int] | PrimitiveArray[float]
    if typecode == "d":
        selected = PrimitiveArray("d", cast("Iterable[float]", values))
    else:
        selected = PrimitiveArray(typecode, cast("Iterable[int]", values))
    _require_canonical_item_size(selected)
    if sys.byteorder != "little" and selected.itemsize > 1:
        selected.byteswap()
    return selected.tobytes()


def _decode_primitive_array(
    content: bytes,
    *,
    count: int,
    typecode: Literal["B", "d", "q", "Q"],
) -> tuple[object, ...]:
    selected: PrimitiveArray[int] | PrimitiveArray[float]
    selected = PrimitiveArray("d") if typecode == "d" else PrimitiveArray(typecode)
    _require_canonical_item_size(selected)
    if len(content) != count * selected.itemsize:
        raise WorkerWireError("worker collect attachment has invalid size")
    selected.frombytes(content)
    if sys.byteorder != "little" and selected.itemsize > 1:
        selected.byteswap()
    return cast("tuple[object, ...]", tuple(selected))


def _require_canonical_item_size(
    value: PrimitiveArray[int] | PrimitiveArray[float],
) -> None:
    expected = 1 if value.typecode == "B" else 8
    if value.itemsize != expected:
        raise WorkerWireError("platform cannot encode canonical worker arrays")


def _encode_strings(values: tuple[object, ...]) -> bytes:
    offsets = [0]
    chunks: list[bytes] = []
    size = 0
    for item in values:
        try:
            encoded = _require_string(item).encode("utf-8")
        except UnicodeEncodeError as error:
            raise WorkerWireError(
                "worker collect string array is not valid UTF-8"
            ) from error
        chunks.append(encoded)
        size += len(encoded)
        offsets.append(size)
    return _encode_primitive_array("Q", offsets) + b"".join(chunks)


def _decode_strings(content: bytes, *, count: int) -> tuple[object, ...]:
    offset_bytes = (count + 1) * 8
    if len(content) < offset_bytes:
        raise WorkerWireError("worker collect string attachment has invalid size")
    offsets = cast(
        "tuple[int, ...]",
        _decode_primitive_array(
            content[:offset_bytes],
            count=count + 1,
            typecode="Q",
        ),
    )
    encoded = content[offset_bytes:]
    if (
        offsets[0] != 0
        or offsets[-1] != len(encoded)
        or any(left > right for left, right in pairwise(offsets))
    ):
        raise WorkerWireError("worker collect string offsets are invalid")
    try:
        return tuple(
            encoded[start:stop].decode("utf-8") for start, stop in pairwise(offsets)
        )
    except UnicodeDecodeError as error:
        raise WorkerWireError(
            "worker collect string attachment is not UTF-8"
        ) from error


def _require_float(value: object) -> float:
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise WorkerWireError("worker collect float64 array contains an invalid value")
    selected = float(value)
    if not math.isfinite(selected):
        raise WorkerWireError("worker collect float64 array value is out of range")
    return selected


def _require_int(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise WorkerWireError("worker collect int64 array contains an invalid value")
    return value


def _require_complex(value: object) -> ComplexComponents:
    if not isinstance(value, ComplexComponents):
        raise WorkerWireError(
            "worker collect complex128 array contains an invalid value"
        )
    return value


def _require_bool(value: object) -> bool:
    if not isinstance(value, bool):
        raise WorkerWireError("worker collect bool array contains an invalid value")
    return value


def _require_string(value: object) -> str:
    if not isinstance(value, str):
        raise WorkerWireError("worker collect string array contains an invalid value")
    return value


def _parse_invoke_header(
    header: bytes,
    *,
    limits: WireLimits,
) -> _InvokeHeader:
    if len(header) > limits.max_header_bytes:
        raise WorkerWireError("worker invoke header exceeds its size limit")
    try:
        descriptor = _InvokeHeader.model_validate_json(header)
    except ValidationError as error:
        raise WorkerWireError("invalid worker invoke header") from error
    _validate_declared_attachment_limits(
        label="worker invoke",
        header=header,
        manifests=descriptor.attachments,
        limits=limits,
    )
    return descriptor


def _parse_collect_header(
    header: bytes,
    *,
    limits: WireLimits,
) -> _CollectHeader:
    if len(header) > limits.max_header_bytes:
        raise WorkerWireError("worker collect header exceeds its size limit")
    try:
        descriptor = _CollectHeader.model_validate_json(header)
    except ValidationError as error:
        raise WorkerWireError("invalid worker collect header") from error
    _validate_declared_attachment_limits(
        label="worker collect",
        header=header,
        manifests=descriptor.attachments,
        limits=limits,
    )
    return descriptor


def _validate_declared_attachment_limits(
    *,
    label: str,
    header: bytes,
    manifests: Sequence[_SizedAttachment],
    limits: WireLimits,
) -> None:
    if len(header) > limits.max_header_bytes:
        raise WorkerWireError(f"{label} header exceeds its size limit")
    if len(manifests) > limits.max_attachments:
        raise WorkerWireError(f"{label} attachment count exceeds its limit")

    declared_total = 0
    for manifest in manifests:
        if manifest.size_bytes > limits.max_attachment_bytes:
            raise WorkerWireError(f"{label} attachment exceeds its size limit")
        declared_total += manifest.size_bytes
    if declared_total > limits.max_total_attachment_bytes:
        raise WorkerWireError(f"{label} attachments exceed their total size limit")


def _validate_actual_attachment_limits(
    *,
    label: str,
    attachments: Sequence[bytes],
    limits: WireLimits,
) -> None:
    if len(attachments) > limits.max_attachments:
        raise WorkerWireError(f"{label} attachment count exceeds its limit")
    actual_total = 0
    for content in attachments:
        if len(content) > limits.max_attachment_bytes:
            raise WorkerWireError(f"{label} attachment exceeds its size limit")
        actual_total += len(content)
    if actual_total > limits.max_total_attachment_bytes:
        raise WorkerWireError(f"{label} attachments exceed their total size limit")


__all__ = [
    "COLLECT_WIRE_VERSION",
    "DEFAULT_WIRE_LIMITS",
    "INVOKE_WIRE_VERSION",
    "CollectFrames",
    "InvokeFrames",
    "WireLimits",
    "WorkerWireError",
    "collect_attachment_sizes",
    "invoke_attachment_sizes",
    "join_collect_receipt",
    "join_invoke_request",
    "split_collect_receipt",
    "split_invoke_request",
]
