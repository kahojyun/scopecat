"""Explicit codecs for process-safe opaque payloads."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol, Self, cast, override

from pydantic import BaseModel, ConfigDict, Field, model_validator

from scopecat.kernel.content_identity import sha256_content_hash
from scopecat.kernel.payloads import PayloadValue
from scopecat.records.content import CommandPayload, InlinePayloadBody
from scopecat.sdk.attachments import (
    AttachmentBundle,
    AttachmentBundleLimits,
    ImmutableBuffer,
)

type PayloadContentFormat = Literal["bytes", "attachment_bundle"]


@dataclass(frozen=True, slots=True)
class EncodedPayloadContent:
    """Exact codec output, kept as raw bytes or separate binary attachments."""

    _content: bytes | AttachmentBundle = field(repr=False)

    @classmethod
    def from_bytes(cls, content: bytes, /) -> Self:
        return cls(bytes(content))

    @classmethod
    def from_bundle(cls, bundle: AttachmentBundle, /) -> Self:
        return cls(bundle)

    @classmethod
    def from_flat_bytes(
        cls,
        content: bytes,
        content_format: PayloadContentFormat,
        /,
        *,
        limits: AttachmentBundleLimits | None = None,
    ) -> Self:
        if content_format == "bytes":
            return cls.from_bytes(content)
        return cls.from_bundle(
            AttachmentBundle.from_bytes(content)
            if limits is None
            else AttachmentBundle.from_bytes(content, limits)
        )

    @classmethod
    def from_parts(
        cls,
        content_format: PayloadContentFormat,
        parts: tuple[ImmutableBuffer, ...],
        /,
    ) -> Self:
        if content_format == "bytes":
            if len(parts) != 1:
                raise ValueError("raw payload content requires exactly one part")
            return cls.from_bytes(bytes(parts[0]))
        if not parts:
            raise ValueError("attachment payload content requires a header part")
        return cls.from_bundle(
            AttachmentBundle(
                header=bytes(parts[0]),
                attachments=parts[1:],
            )
        )

    @property
    def format(self) -> PayloadContentFormat:
        return (
            "attachment_bundle"
            if isinstance(self._content, AttachmentBundle)
            else "bytes"
        )

    @property
    def size_bytes(self) -> int:
        if isinstance(self._content, AttachmentBundle):
            return self._content.size_bytes
        return len(self._content)

    def __len__(self) -> int:
        return self.size_bytes

    @property
    def parts(self) -> tuple[ImmutableBuffer, ...]:
        if isinstance(self._content, AttachmentBundle):
            return self._content.header, *self._content.attachments
        return (self._content,)

    def to_bytes(self) -> bytes:
        if isinstance(self._content, AttachmentBundle):
            return self._content.to_bytes()
        return self._content

    def content_hash(self) -> str:
        if isinstance(self._content, AttachmentBundle):
            return self._content.content_hash()
        return sha256_content_hash(self._content)

    def require_bytes(self) -> bytes:
        if isinstance(self._content, AttachmentBundle):
            raise TypeError("payload content is an attachment bundle")
        return self._content

    def require_bundle(self) -> AttachmentBundle:
        if not isinstance(self._content, AttachmentBundle):
            raise TypeError("payload content is raw bytes")
        return self._content


type PayloadEncoder[ValueT] = Callable[[ValueT], EncodedPayloadContent]
type PayloadDecoder[ValueT] = Callable[[EncodedPayloadContent], ValueT]
type BytePayloadEncoder[ValueT] = Callable[[ValueT], bytes]
type BytePayloadDecoder[ValueT] = Callable[[bytes], ValueT]


class PayloadDescriptor(Protocol):
    @property
    def schema_id(self) -> str: ...

    @property
    def codec_id(self) -> str: ...

    @property
    def codec_version(self) -> int: ...

    @property
    def media_type(self) -> str: ...

    @property
    def content_format(self) -> PayloadContentFormat: ...


class PayloadContractRegistration(Protocol):
    def registration(self) -> tuple[str, PayloadCodec[object]]: ...


class PayloadCodecDescription(BaseModel):
    """Serializable codec identity for one payload schema."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_id: str = Field(min_length=1)
    codec_id: str = Field(min_length=1)
    codec_version: int = Field(ge=1)
    media_type: str = Field(min_length=1)
    content_format: PayloadContentFormat


class PayloadCodecCatalog(BaseModel):
    """Serializable payload codecs available at one execution boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    codecs: tuple[PayloadCodecDescription, ...] = ()

    @model_validator(mode="after")
    def validate_unique_schemas(self) -> PayloadCodecCatalog:
        schema_ids = tuple(codec.schema_id for codec in self.codecs)
        if len(schema_ids) != len(set(schema_ids)):
            raise ValueError("payload codec catalog schema ids must be unique")
        return self

    def validate_descriptor(
        self,
        payload: PayloadDescriptor,
    ) -> PayloadCodecDescription:
        codec = self._require(payload.schema_id)
        mismatches = (
            ("codec_id", codec.codec_id, payload.codec_id),
            ("codec_version", codec.codec_version, payload.codec_version),
            ("media_type", codec.media_type, payload.media_type),
            ("content_format", codec.content_format, payload.content_format),
        )
        for field_name, expected, actual in mismatches:
            if actual != expected:
                raise ValueError(
                    f"payload {field_name} mismatch for schema "
                    f"{payload.schema_id!r}: expected {expected!r}, got {actual!r}"
                )
        return codec

    def _require(self, schema_id: str) -> PayloadCodecDescription:
        for codec in self.codecs:
            if codec.schema_id == schema_id:
                return codec
        raise LookupError(f"no payload codec registered for schema {schema_id!r}")


@dataclass(frozen=True, slots=True, kw_only=True)
class PayloadCodec[ValueT = object]:
    """Bidirectional content codec registered for one or more payload schemas."""

    id: str
    version: int
    media_type: str
    content_format: PayloadContentFormat
    encoder: PayloadEncoder[ValueT] = field(repr=False, compare=False)
    decoder: PayloadDecoder[ValueT] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("payload codec id must not be empty")
        if self.version < 1:
            raise ValueError("payload codec version must be positive")
        if not self.media_type:
            raise ValueError("payload codec media_type must not be empty")


def byte_payload_codec[ValueT](
    *,
    id: str,
    version: int,
    media_type: str,
    encoder: BytePayloadEncoder[ValueT],
    decoder: BytePayloadDecoder[ValueT],
) -> PayloadCodec[ValueT]:
    """Adapt an ordinary bytes codec to the structured payload pipeline."""

    return PayloadCodec(
        id=id,
        version=version,
        media_type=media_type,
        content_format="bytes",
        encoder=lambda value: EncodedPayloadContent.from_bytes(encoder(value)),
        decoder=lambda content: decoder(content.require_bytes()),
    )


@dataclass(frozen=True, slots=True)
class EncodedPayload:
    """Exact codec output and the descriptor required to decode it."""

    schema_id: str
    codec_id: str
    codec_version: int
    media_type: str
    content_format: PayloadContentFormat
    content: EncodedPayloadContent = field(repr=False)


@dataclass(frozen=True, slots=True, kw_only=True)
class PayloadContract[ValueT = object]:
    """One typed payload contract shared by authoring and worker adapters."""

    schema_id: str
    codec: PayloadCodec[ValueT] = field(repr=False)

    def __post_init__(self) -> None:
        if not self.schema_id:
            raise ValueError("payload contract schema_id must not be empty")

    def value(self, value: ValueT, /) -> PayloadValue:
        """Tag a typed local value without repeating its schema at call sites."""

        return PayloadValue(schema_id=self.schema_id, payload=value)

    def __call__(self, value: ValueT, /) -> PayloadValue:
        return self.value(value)

    def encode(self, value: ValueT, /) -> EncodedPayload:
        """Encode a typed value without repeating schema or codec metadata."""

        content = self.codec.encoder(value)
        if content.format != self.codec.content_format:
            raise ValueError("payload codec returned an undeclared content format")
        return EncodedPayload(
            schema_id=self.schema_id,
            codec_id=self.codec.id,
            codec_version=self.codec.version,
            media_type=self.codec.media_type,
            content_format=self.codec.content_format,
            content=content,
        )

    def decode_content(self, content: EncodedPayloadContent, /) -> ValueT:
        """Decode content when its descriptor was validated externally."""

        return self.codec.decoder(content)

    def decode(self, payload: CommandPayload, /) -> ValueT:
        """Validate and decode one command payload through this typed contract."""

        if payload.schema_id != self.schema_id:
            raise ValueError(
                f"payload schema mismatch: expected {self.schema_id!r}, "
                f"got {payload.schema_id!r}"
            )
        mismatches = (
            ("codec_id", self.codec.id, payload.codec_id),
            ("codec_version", self.codec.version, payload.codec_version),
            ("media_type", self.codec.media_type, payload.media_type),
            ("content_format", self.codec.content_format, payload.content_format),
        )
        for field_name, expected, actual in mismatches:
            if actual != expected:
                raise ValueError(
                    f"payload {field_name} mismatch for schema "
                    f"{self.schema_id!r}: expected {expected!r}, got {actual!r}"
                )
        flat_content = payload.inline_bytes()
        payload.verify_content(flat_content)
        return self.decode_content(
            EncodedPayloadContent.from_flat_bytes(
                flat_content,
                payload.content_format,
            )
        )

    def command_payload(
        self,
        id: str,
        value: ValueT,
        /,
    ) -> CommandPayload:
        """Build one transport payload without exposing descriptor plumbing."""

        encoded = self.encode(value)
        return _command_payload_from_encoded(id, encoded)

    def registration(self) -> tuple[str, PayloadCodec[object]]:
        return self.schema_id, cast("PayloadCodec[object]", self.codec)


class PayloadCodecRegistry(Mapping[str, PayloadCodec[object]]):
    """Immutable schema-to-codec registry shared by compute and driver workers."""

    __slots__ = ("_catalog", "_codecs")

    _catalog: PayloadCodecCatalog
    _codecs: Mapping[str, PayloadCodec[object]]

    def __init__[ValueT](
        self,
        codecs: Mapping[str, PayloadCodec[ValueT]] | None = None,
    ) -> None:
        selected = {
            schema_id: cast("PayloadCodec[object]", codec)
            for schema_id, codec in (codecs or {}).items()
        }
        if any(not schema_id for schema_id in selected):
            raise ValueError("payload codec schema id must not be empty")
        self._codecs = MappingProxyType(selected)
        self._catalog = PayloadCodecCatalog(
            codecs=tuple(
                PayloadCodecDescription(
                    schema_id=schema_id,
                    codec_id=codec.id,
                    codec_version=codec.version,
                    media_type=codec.media_type,
                    content_format=codec.content_format,
                )
                for schema_id, codec in sorted(selected.items())
            )
        )

    @property
    def catalog(self) -> PayloadCodecCatalog:
        return self._catalog

    @classmethod
    def from_contracts(
        cls,
        *contracts: PayloadContractRegistration,
    ) -> PayloadCodecRegistry:
        """Build a registry from declarations that already own schema identity."""

        codecs: dict[str, PayloadCodec[object]] = {}
        for contract in contracts:
            schema_id, codec = contract.registration()
            if schema_id in codecs:
                raise ValueError(f"duplicate payload contract schema {schema_id!r}")
            codecs[schema_id] = codec
        return cls(codecs)

    @override
    def __getitem__(self, schema_id: str) -> PayloadCodec[object]:
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
        if content.format != codec.content_format:
            raise ValueError("payload codec returned an undeclared content format")
        return EncodedPayload(
            schema_id=schema_id,
            codec_id=codec.id,
            codec_version=codec.version,
            media_type=codec.media_type,
            content_format=codec.content_format,
            content=content,
        )

    def command_payload(
        self,
        id: str,
        schema_id: str,
        value: object,
        /,
    ) -> CommandPayload:
        """Encode a dynamically selected schema into its transport envelope."""

        encoded = self.encode(schema_id, value)
        return _command_payload_from_encoded(id, encoded)

    def validate_descriptor(
        self,
        payload: PayloadDescriptor,
    ) -> PayloadCodec[object]:
        """Resolve and validate the codec declared by a payload descriptor."""

        codec = self._require(payload.schema_id)
        self._catalog.validate_descriptor(payload)
        return codec

    def decode_content(
        self,
        descriptor: PayloadDescriptor,
        content: EncodedPayloadContent,
    ) -> object:
        """Decode verified content using its exact declared codec."""

        codec = self.validate_descriptor(descriptor)
        if content.format != descriptor.content_format:
            raise ValueError("payload content does not match its declared format")
        return codec.decoder(content)

    def decode(self, payload: CommandPayload) -> object:
        flat_content = payload.inline_bytes()
        payload.verify_content(flat_content)
        return self.decode_content(
            payload,
            EncodedPayloadContent.from_flat_bytes(
                flat_content,
                payload.content_format,
            ),
        )

    def _require(self, schema_id: str) -> PayloadCodec[object]:
        try:
            return self._codecs[schema_id]
        except KeyError as error:
            raise LookupError(
                f"no payload codec registered for schema {schema_id!r}"
            ) from error


EMPTY_PAYLOAD_CODECS = PayloadCodecRegistry()


def _command_payload_from_encoded(
    id: str,
    encoded: EncodedPayload,
) -> CommandPayload:
    flat_content = encoded.content.to_bytes()
    content_hash = encoded.content.content_hash()
    payload = CommandPayload.model_construct(
        id=id,
        schema_id=encoded.schema_id,
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content_format=encoded.content_format,
        content_hash=content_hash,
        size_bytes=encoded.content.size_bytes,
        body=InlinePayloadBody.from_bytes(flat_content),
    )
    object.__setattr__(payload, "_verified_content", (content_hash, flat_content))
    return payload


def command_payload_from_encoded_content(
    *,
    id: str,
    schema_id: str,
    codec_id: str,
    codec_version: int,
    media_type: str,
    content: EncodedPayloadContent,
) -> CommandPayload:
    """Build a transport envelope from raw or attachment-backed content."""

    return _command_payload_from_encoded(
        id,
        EncodedPayload(
            schema_id=schema_id,
            codec_id=codec_id,
            codec_version=codec_version,
            media_type=media_type,
            content_format=content.format,
            content=content,
        ),
    )


__all__ = [
    "EMPTY_PAYLOAD_CODECS",
    "BytePayloadDecoder",
    "BytePayloadEncoder",
    "EncodedPayload",
    "EncodedPayloadContent",
    "PayloadCodec",
    "PayloadCodecCatalog",
    "PayloadCodecDescription",
    "PayloadCodecRegistry",
    "PayloadContentFormat",
    "PayloadContract",
    "PayloadContractRegistration",
    "PayloadDecoder",
    "PayloadDescriptor",
    "PayloadEncoder",
    "byte_payload_codec",
    "command_payload_from_encoded_content",
]
