"""Deterministic Pydantic payloads with buffer-backed NumPy attachments."""

from __future__ import annotations

import enum
import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, is_dataclass
from typing import Annotated, Literal, cast

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError

from scopecat.kernel.content_identity import canonical_json
from scopecat.kernel.numpy_storage import freeze_ndarray
from scopecat.sdk.payloads import PayloadCodec

STRUCTURED_PAYLOAD_CODEC_ID = "scopecat.pydantic-buffer-bundle"
STRUCTURED_PAYLOAD_MEDIA_TYPE = "application/vnd.scopecat.pydantic-buffer-bundle"

_MAGIC = b"SCPBNDL1"
_PREFIX_SIZE = len(_MAGIC) + 8
_MAX_HEADER_BYTES = 16 * 1024 * 1024
_ALLOWED_ARRAY_KINDS = frozenset("buifc")

type _NonNegativeInt = Annotated[int, Field(ge=0)]


class StructuredPayloadError(ValueError):
    """A structured payload cannot be encoded or violates its wire contract."""


class _ArrayDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    index: _NonNegativeInt
    dtype: str = Field(min_length=1)
    shape: tuple[_NonNegativeInt, ...]
    size_bytes: _NonNegativeInt


class _BundleHeader(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    codec: Literal["scopecat.structured-payload.v1"] = "scopecat.structured-payload.v1"
    root: JsonValue
    arrays: tuple[_ArrayDescriptor, ...] = ()


@dataclass(slots=True)
class _Encoder:
    attachments: list[memoryview]
    descriptors: list[_ArrayDescriptor]

    def node(self, value: object) -> JsonValue:
        if value is None:
            return {"type": "null"}
        if isinstance(value, bool):
            return {"type": "bool", "value": value}
        if isinstance(value, int):
            return {"type": "int", "value": value}
        if isinstance(value, float):
            if not math.isfinite(value):
                raise StructuredPayloadError(
                    "structured payload scalar floats must be finite"
                )
            return {"type": "float", "value": value}
        if isinstance(value, complex):
            if not math.isfinite(value.real) or not math.isfinite(value.imag):
                raise StructuredPayloadError(
                    "structured payload scalar complex values must be finite"
                )
            return {
                "type": "complex",
                "real": value.real,
                "imag": value.imag,
            }
        if isinstance(value, str):
            return {"type": "string", "value": value}
        if isinstance(value, enum.Enum):
            return self.node(cast("object", value.value))
        if isinstance(value, np.generic):
            return self.node(value.item())
        if isinstance(value, np.ndarray):
            return self._array(value)
        if isinstance(value, bytes | bytearray | memoryview):
            encoded = value.tobytes() if isinstance(value, memoryview) else bytes(value)
            selected = np.frombuffer(encoded, dtype=np.uint8)
            return self._array(selected, node_type="bytes")
        if isinstance(value, BaseModel):
            return {
                "type": "record",
                "fields": {
                    name: self.node(cast("object", getattr(value, name)))
                    for name in type(value).model_fields
                },
            }
        if is_dataclass(value) and not isinstance(value, type):
            return {
                "type": "record",
                "fields": {
                    member.name: self.node(cast("object", getattr(value, member.name)))
                    for member in fields(value)
                    if member.init
                },
            }
        if isinstance(value, tuple):
            selected_tuple = cast("tuple[object, ...]", value)
            return {
                "type": "tuple",
                "items": [self.node(item) for item in selected_tuple],
            }
        if isinstance(value, list):
            selected_list = cast("list[object]", value)
            return {
                "type": "list",
                "items": [self.node(item) for item in selected_list],
            }
        if isinstance(value, Mapping):
            selected = cast("Mapping[object, object]", value)
            if any(not isinstance(key, str) for key in selected):
                raise StructuredPayloadError(
                    "structured payload mappings require string keys"
                )
            mapping = cast("Mapping[str, object]", selected)
            return {
                "type": "mapping",
                "items": [[key, self.node(mapping[key])] for key in sorted(mapping)],
            }
        if isinstance(value, Sequence):
            return {
                "type": "list",
                "items": [self.node(item) for item in value],
            }
        raise StructuredPayloadError(
            f"{type(value).__qualname__} is not supported by the structured codec"
        )

    def _array(
        self,
        value: NDArray[np.generic],
        *,
        node_type: Literal["ndarray", "bytes"] = "ndarray",
    ) -> JsonValue:
        if value.dtype.hasobject or value.dtype.kind not in _ALLOWED_ARRAY_KINDS:
            raise StructuredPayloadError(
                f"structured payload array dtype {value.dtype} is not supported"
            )
        wire_dtype = value.dtype.newbyteorder("<")
        selected = value.astype(wire_dtype, order="C", copy=False)
        frozen = freeze_ndarray(selected)
        content = memoryview(frozen).cast("B") if frozen.size else memoryview(b"")
        index = len(self.attachments)
        self.attachments.append(content)
        self.descriptors.append(
            _ArrayDescriptor(
                index=index,
                dtype=wire_dtype.str,
                shape=cast("tuple[int, ...]", frozen.shape),
                size_bytes=len(content),
            )
        )
        return {"type": node_type, "attachment": index}


def pydantic_buffer_bundle_codec[ModelT: BaseModel](
    model_type: type[ModelT],
    /,
    *,
    id: str = STRUCTURED_PAYLOAD_CODEC_ID,
    version: int = 1,
) -> PayloadCodec[ModelT]:
    """Build a strict model codec that keeps NumPy arrays in binary buffers."""

    def encode(value: ModelT) -> bytes:
        try:
            selected = model_type.model_validate(value, strict=True)
        except ValidationError as error:
            raise StructuredPayloadError(
                f"invalid {model_type.__qualname__} payload"
            ) from error
        encoder = _Encoder([], [])
        header = _BundleHeader(
            root=encoder.node(selected),
            arrays=tuple(encoder.descriptors),
        )
        header_bytes = canonical_json(header.model_dump(mode="json")).encode("utf-8")
        if len(header_bytes) > _MAX_HEADER_BYTES:
            raise StructuredPayloadError("structured payload header is too large")
        return b"".join(
            (
                _MAGIC,
                struct.pack("<Q", len(header_bytes)),
                header_bytes,
                *encoder.attachments,
            )
        )

    def decode(content: bytes) -> ModelT:
        header, attachments = _unpack(content)
        value = _decode_node(header.root, attachments)
        try:
            return model_type.model_validate(value, strict=True)
        except ValidationError as error:
            raise StructuredPayloadError(
                f"decoded payload does not match {model_type.__qualname__}"
            ) from error

    return PayloadCodec(
        id=id,
        version=version,
        media_type=STRUCTURED_PAYLOAD_MEDIA_TYPE,
        encoder=encode,
        decoder=decode,
    )


def _unpack(content: bytes) -> tuple[_BundleHeader, tuple[NDArray[np.generic], ...]]:
    if len(content) < _PREFIX_SIZE or content[: len(_MAGIC)] != _MAGIC:
        raise StructuredPayloadError("structured payload prefix is invalid")
    header_size = struct.unpack_from("<Q", content, len(_MAGIC))[0]
    if header_size > _MAX_HEADER_BYTES or _PREFIX_SIZE + header_size > len(content):
        raise StructuredPayloadError("structured payload header size is invalid")
    try:
        header = _BundleHeader.model_validate_json(
            content[_PREFIX_SIZE : _PREFIX_SIZE + header_size]
        )
    except ValidationError as error:
        raise StructuredPayloadError("structured payload header is invalid") from error
    descriptors = tuple(sorted(header.arrays, key=lambda item: item.index))
    if tuple(item.index for item in descriptors) != tuple(range(len(descriptors))):
        raise StructuredPayloadError("structured payload array indexes are invalid")
    body = memoryview(content)[_PREFIX_SIZE + header_size :]
    arrays: list[NDArray[np.generic]] = []
    offset = 0
    for descriptor in descriptors:
        try:
            dtype = np.dtype(descriptor.dtype)
        except TypeError as error:
            raise StructuredPayloadError(
                "structured payload array dtype is invalid"
            ) from error
        if dtype.hasobject or dtype.kind not in _ALLOWED_ARRAY_KINDS:
            raise StructuredPayloadError(
                f"structured payload array dtype {dtype} is not supported"
            )
        count = math.prod(descriptor.shape)
        expected_size = count * dtype.itemsize
        if expected_size != descriptor.size_bytes:
            raise StructuredPayloadError(
                "structured payload array shape does not match its byte size"
            )
        end = offset + descriptor.size_bytes
        if end > len(body):
            raise StructuredPayloadError("structured payload array is truncated")
        arrays.append(
            np.frombuffer(body[offset:end], dtype=dtype).reshape(descriptor.shape)
        )
        offset = end
    if offset != len(body):
        raise StructuredPayloadError("structured payload has trailing array bytes")
    return header, tuple(arrays)


def _decode_node(
    raw: JsonValue,
    attachments: tuple[NDArray[np.generic], ...],
) -> object:
    if not isinstance(raw, dict) or not isinstance(node_type := raw.get("type"), str):
        raise StructuredPayloadError("structured payload value node is invalid")
    if node_type == "null":
        return None
    if node_type in {"bool", "int", "float", "string"}:
        return raw.get("value")
    if node_type == "complex":
        real = raw.get("real")
        imag = raw.get("imag")
        if not isinstance(real, int | float) or not isinstance(imag, int | float):
            raise StructuredPayloadError("structured complex value is invalid")
        return complex(real, imag)
    if node_type in {"ndarray", "bytes"}:
        index = raw.get("attachment")
        if not isinstance(index, int) or isinstance(index, bool):
            raise StructuredPayloadError("structured payload attachment is invalid")
        try:
            selected = attachments[index]
        except IndexError as error:
            raise StructuredPayloadError(
                "structured payload attachment is missing"
            ) from error
        return (
            bytes(memoryview(selected).cast("B")) if node_type == "bytes" else selected
        )
    if node_type in {"tuple", "list"}:
        items = raw.get("items")
        if not isinstance(items, list):
            raise StructuredPayloadError("structured payload sequence is invalid")
        decoded = [_decode_node(item, attachments) for item in items]
        return tuple(decoded) if node_type == "tuple" else decoded
    if node_type == "record":
        fields_value = raw.get("fields")
        if not isinstance(fields_value, dict):
            raise StructuredPayloadError("structured payload record is invalid")
        return {
            name: _decode_node(item, attachments) for name, item in fields_value.items()
        }
    if node_type == "mapping":
        items = raw.get("items")
        if not isinstance(items, list):
            raise StructuredPayloadError("structured payload mapping is invalid")
        result: dict[str, object] = {}
        for entry in items:
            if (
                not isinstance(entry, list)
                or len(entry) != 2
                or not isinstance(entry[0], str)
            ):
                raise StructuredPayloadError(
                    "structured payload mapping entry is invalid"
                )
            result[entry[0]] = _decode_node(entry[1], attachments)
        return result
    raise StructuredPayloadError(f"unknown structured payload node type {node_type!r}")


__all__ = [
    "STRUCTURED_PAYLOAD_CODEC_ID",
    "STRUCTURED_PAYLOAD_MEDIA_TYPE",
    "StructuredPayloadError",
    "pydantic_buffer_bundle_codec",
]
