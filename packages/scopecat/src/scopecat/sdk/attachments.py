"""Carrier-neutral JSON-header and binary-attachment bundles."""

from __future__ import annotations

import struct
from collections.abc import Buffer
from dataclasses import dataclass
from hashlib import sha256
from typing import Self, cast

type BinaryBuffer = Buffer
type ImmutableBuffer = bytes | memoryview

_MAGIC = b"SCATBND1"
_PREFIX = struct.Struct("<8sQI")
_ATTACHMENT_SIZE = struct.Struct("<Q")


class AttachmentBundleError(ValueError):
    """An attachment bundle is malformed or exceeds its declared limits."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AttachmentBundleLimits:
    max_header_bytes: int = 16 * 1024 * 1024
    max_attachments: int = 1024
    max_attachment_bytes: int = 128 * 1024 * 1024
    max_total_attachment_bytes: int = 512 * 1024 * 1024

    def __post_init__(self) -> None:
        if (
            self.max_header_bytes < 1
            or self.max_attachments < 1
            or self.max_attachment_bytes < 1
            or self.max_total_attachment_bytes < 1
        ):
            raise ValueError("attachment bundle limits must be positive")


DEFAULT_ATTACHMENT_BUNDLE_LIMITS = AttachmentBundleLimits()


@dataclass(frozen=True, slots=True)
class AttachmentBundle:
    """One immutable header and its ordered opaque binary attachments.

    The in-memory form keeps attachments separate. ``to_bytes`` is the carrier
    adapter for boundaries that require one contiguous object; multipart
    transports can consume ``header`` and ``attachments`` directly.
    """

    header: bytes
    attachments: tuple[ImmutableBuffer, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "header", bytes(self.header))
        object.__setattr__(
            self,
            "attachments",
            tuple(_immutable_buffer(item) for item in self.attachments),
        )

    @property
    def attachment_size_bytes(self) -> int:
        return sum(len(attachment) for attachment in self.attachments)

    @property
    def size_bytes(self) -> int:
        return (
            _PREFIX.size
            + len(self.attachments) * _ATTACHMENT_SIZE.size
            + len(self.header)
            + self.attachment_size_bytes
        )

    def validate(
        self,
        limits: AttachmentBundleLimits = DEFAULT_ATTACHMENT_BUNDLE_LIMITS,
    ) -> None:
        _validate_sizes(
            header_size=len(self.header),
            attachment_sizes=tuple(map(len, self.attachments)),
            limits=limits,
        )

    def segments(
        self,
        limits: AttachmentBundleLimits = DEFAULT_ATTACHMENT_BUNDLE_LIMITS,
    ) -> tuple[ImmutableBuffer, ...]:
        """Return the canonical flat representation without joining its parts."""

        self.validate(limits)
        prefix = bytearray(_PREFIX.size + len(self.attachments) * _ATTACHMENT_SIZE.size)
        _PREFIX.pack_into(
            prefix,
            0,
            _MAGIC,
            len(self.header),
            len(self.attachments),
        )
        offset = _PREFIX.size
        for attachment in self.attachments:
            _ATTACHMENT_SIZE.pack_into(prefix, offset, len(attachment))
            offset += _ATTACHMENT_SIZE.size
        return bytes(prefix), self.header, *self.attachments

    def to_bytes(
        self,
        limits: AttachmentBundleLimits = DEFAULT_ATTACHMENT_BUNDLE_LIMITS,
    ) -> bytes:
        """Flatten the canonical representation for a single-object carrier."""

        segments = self.segments(limits)
        content = bytearray(self.size_bytes)
        offset = 0
        for segment in segments:
            end = offset + len(segment)
            content[offset:end] = segment
            offset = end
        return bytes(content)

    def content_hash(
        self,
        limits: AttachmentBundleLimits = DEFAULT_ATTACHMENT_BUNDLE_LIMITS,
    ) -> str:
        """Hash the canonical flat representation without materializing it."""

        digest = sha256()
        for segment in self.segments(limits):
            digest.update(segment)
        return f"sha256:{digest.hexdigest()}"

    @classmethod
    def from_bytes(
        cls,
        content: BinaryBuffer,
        limits: AttachmentBundleLimits = DEFAULT_ATTACHMENT_BUNDLE_LIMITS,
    ) -> Self:
        """Adopt immutable slices from one canonical flat representation."""

        body = _immutable_view(content)
        if len(body) < _PREFIX.size:
            raise AttachmentBundleError("attachment bundle prefix is truncated")
        magic, header_size, attachment_count = cast(
            "tuple[bytes, int, int]",
            _PREFIX.unpack_from(body),
        )
        if magic != _MAGIC:
            raise AttachmentBundleError("attachment bundle prefix is invalid")
        if attachment_count > limits.max_attachments:
            raise AttachmentBundleError("attachment bundle has too many attachments")
        table_end = _PREFIX.size + attachment_count * _ATTACHMENT_SIZE.size
        if table_end > len(body):
            raise AttachmentBundleError("attachment bundle size table is truncated")
        attachment_sizes = tuple(
            cast(
                "tuple[int]",
                _ATTACHMENT_SIZE.unpack_from(
                    body,
                    _PREFIX.size + index * _ATTACHMENT_SIZE.size,
                ),
            )[0]
            for index in range(attachment_count)
        )
        _validate_sizes(
            header_size=header_size,
            attachment_sizes=attachment_sizes,
            limits=limits,
        )
        expected_size = table_end + header_size + sum(attachment_sizes)
        if len(body) < expected_size:
            raise AttachmentBundleError("attachment bundle is truncated")
        if len(body) > expected_size:
            raise AttachmentBundleError("attachment bundle has trailing bytes")
        header_end = table_end + header_size
        header = bytes(body[table_end:header_end])
        attachments: list[memoryview] = []
        offset = header_end
        for size in attachment_sizes:
            end = offset + size
            attachments.append(body[offset:end])
            offset = end
        return cls(header=header, attachments=tuple(attachments))


def _validate_sizes(
    *,
    header_size: int,
    attachment_sizes: tuple[int, ...],
    limits: AttachmentBundleLimits,
) -> None:
    if header_size > limits.max_header_bytes:
        raise AttachmentBundleError("attachment bundle header exceeds its size limit")
    if len(attachment_sizes) > limits.max_attachments:
        raise AttachmentBundleError("attachment bundle has too many attachments")
    if any(size > limits.max_attachment_bytes for size in attachment_sizes):
        raise AttachmentBundleError("attachment exceeds its size limit")
    if sum(attachment_sizes) > limits.max_total_attachment_bytes:
        raise AttachmentBundleError("attachment bundle body exceeds its size limit")


def _immutable_buffer(content: BinaryBuffer) -> ImmutableBuffer:
    view = memoryview(content)
    if not view.c_contiguous:
        return view.tobytes()
    selected = view.cast("B")
    return selected if selected.readonly else selected.tobytes()


def _immutable_view(content: BinaryBuffer) -> memoryview:
    selected = _immutable_buffer(content)
    return memoryview(selected).cast("B")


__all__ = [
    "DEFAULT_ATTACHMENT_BUNDLE_LIMITS",
    "AttachmentBundle",
    "AttachmentBundleError",
    "AttachmentBundleLimits",
    "BinaryBuffer",
    "ImmutableBuffer",
]
