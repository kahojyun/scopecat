"""Explicit codecs for process-safe opaque payloads."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import override

from scopecat.records.artifact import CommandPayload

type PayloadEncoder = Callable[[object], bytes]
type PayloadDecoder = Callable[[bytes], object]


@dataclass(frozen=True, slots=True, kw_only=True)
class PayloadCodec:
    """Bidirectional byte codec registered for one or more payload schemas."""

    id: str
    version: int
    media_type: str
    encoder: PayloadEncoder = field(repr=False, compare=False)
    decoder: PayloadDecoder = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("payload codec id must not be empty")
        if self.version < 1:
            raise ValueError("payload codec version must be positive")
        if not self.media_type:
            raise ValueError("payload codec media_type must not be empty")


@dataclass(frozen=True, slots=True)
class EncodedPayload:
    """Exact codec output and the descriptor required to decode it."""

    schema_id: str
    codec_id: str
    codec_version: int
    media_type: str
    content: bytes = field(repr=False)


class PayloadCodecRegistry(Mapping[str, PayloadCodec]):
    """Immutable schema-to-codec registry shared by compute and driver workers."""

    __slots__ = ("_codecs",)

    _codecs: Mapping[str, PayloadCodec]

    def __init__(
        self,
        codecs: Mapping[str, PayloadCodec] | None = None,
    ) -> None:
        selected = dict(codecs or {})
        if any(not schema_id for schema_id in selected):
            raise ValueError("payload codec schema id must not be empty")
        self._codecs = MappingProxyType(selected)

    @override
    def __getitem__(self, schema_id: str) -> PayloadCodec:
        return self._codecs[schema_id]

    @override
    def __iter__(self) -> Iterator[str]:
        return iter(self._codecs)

    @override
    def __len__(self) -> int:
        return len(self._codecs)

    def encode(self, schema_id: str, value: object) -> EncodedPayload:
        codec = self._require(schema_id)
        content = codec.encoder(value)
        return EncodedPayload(
            schema_id=schema_id,
            codec_id=codec.id,
            codec_version=codec.version,
            media_type=codec.media_type,
            content=content,
        )

    def validate_descriptor(self, payload: CommandPayload) -> PayloadCodec:
        """Resolve and validate the codec declared by a payload descriptor."""

        codec = self._require(payload.schema_id)
        mismatches = (
            ("codec_id", codec.id, payload.codec_id),
            ("codec_version", codec.version, payload.codec_version),
            ("media_type", codec.media_type, payload.media_type),
        )
        for field_name, expected, actual in mismatches:
            if actual != expected:
                raise ValueError(
                    f"payload {field_name} mismatch for schema "
                    f"{payload.schema_id!r}: expected {expected!r}, got {actual!r}"
                )
        return codec

    def decode(self, payload: CommandPayload) -> object:
        codec = self.validate_descriptor(payload)
        content = payload.inline_bytes()
        payload.verify_content(content)
        return codec.decoder(content)

    def _require(self, schema_id: str) -> PayloadCodec:
        try:
            return self._codecs[schema_id]
        except KeyError as error:
            raise LookupError(
                f"no payload codec registered for schema {schema_id!r}"
            ) from error


EMPTY_PAYLOAD_CODECS = PayloadCodecRegistry()


__all__ = [
    "EMPTY_PAYLOAD_CODECS",
    "EncodedPayload",
    "PayloadCodec",
    "PayloadCodecRegistry",
    "PayloadDecoder",
    "PayloadEncoder",
]
