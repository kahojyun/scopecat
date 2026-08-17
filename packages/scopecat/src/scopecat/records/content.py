"""Artifact, dataset, record, and opaque command payload models."""

from __future__ import annotations

from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, Literal, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from scopecat.kernel.content_identity import sha256_content_hash
from scopecat.records.metadata import JsonMetadata

type Sha256ContentHash = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]
type _NonEmptyText = Annotated[str, Field(min_length=1)]


class ContentEntry(BaseModel):
    """One content-addressable manifest entry."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    role: Literal["artifact", "dataset", "record"]
    id: str
    kind: str
    title: str | None = None
    media_type: str | None = None
    filename: str | None = None
    data_schema: dict[str, object] | None = Field(default=None, alias="schema")
    content_hash: str = Field(min_length=1)
    produced_by: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)

    @field_validator("id", "kind")
    @classmethod
    def validate_storage_segment(cls, value: str) -> str:
        return _validate_content_segment(value)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or "\\" in value:
            raise ValueError("content filename must be a basename")
        path = PurePosixPath(value)
        if path.name != value or path.is_absolute() or ".." in path.parts:
            raise ValueError("content filename must be a basename")
        return value


@dataclass(frozen=True, slots=True)
class ModelWrite:
    """One typed model write prepared for an atomic publication."""

    ref: str
    value: BaseModel
    replace: bool = True


@dataclass(frozen=True, slots=True)
class BytesWrite:
    """One byte payload write prepared for an atomic publication."""

    ref: str
    content: bytes
    replace: bool = True


class InlinePayloadBody(BaseModel):
    """One complete encoded payload with base64 confined to JSON transport."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        serialize_by_alias=True,
        strict=True,
    )

    kind: Literal["inline"] = "inline"
    content: bytes = Field(alias="content_base64", repr=False)

    @field_validator("content", mode="before")
    @classmethod
    def decode_canonical_base64(cls, value: bytes | str) -> bytes:
        if isinstance(value, bytes):
            return value
        try:
            decoded = b64decode(value, validate=True)
        except (BinasciiError, ValueError) as error:
            raise ValueError("inline payload content must be valid base64") from error
        if b64encode(decoded).decode("ascii") != value:
            raise ValueError("inline payload content must use canonical base64")
        return decoded

    @field_serializer("content", when_used="json")
    def encode_base64_for_json(self, content: bytes) -> str:
        return b64encode(content).decode("ascii")

    @classmethod
    def from_bytes(cls, content: bytes) -> InlinePayloadBody:
        return cls(content_base64=content)

    def content_bytes(self) -> bytes:
        return self.content


class BlobPayloadBody(BaseModel):
    """Content-addressed locator resolved by the payload transport boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["blob"] = "blob"
    ref: Sha256ContentHash


type CommandPayloadBody = Annotated[
    InlinePayloadBody | BlobPayloadBody,
    Field(discriminator="kind"),
]


class CommandPayload(BaseModel):
    """Process-safe encoded payload referenced by an instrument command.

    ``content_hash`` identifies the exact codec output bytes, before base64 or
    blob transport. The schema identifies domain meaning while the codec pair
    identifies the byte representation. Arbitrary Python objects are never part
    of this wire model.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: _NonEmptyText
    schema_id: _NonEmptyText
    codec_id: _NonEmptyText
    codec_version: int = Field(ge=1)
    media_type: _NonEmptyText
    content_hash: Sha256ContentHash
    size_bytes: int = Field(ge=0)
    body: CommandPayloadBody

    @model_validator(mode="after")
    def validate_inline_content(self) -> CommandPayload:
        if isinstance(self.body, InlinePayloadBody):
            self.verify_content(self.body.content_bytes())
        elif self.body.ref != self.content_hash:
            raise ValueError("payload blob ref must equal content_hash")
        return self

    def verify_content(self, content: bytes) -> None:
        verified = cast(
            "tuple[str, bytes] | None",
            self.__dict__.get("_verified_content"),
        )
        if (
            verified is not None
            and verified[0] == self.content_hash
            and verified[1] is content
        ):
            return
        if len(content) != self.size_bytes:
            raise ValueError(
                "payload byte length does not match its declared size_bytes"
            )
        if sha256_content_hash(content) != self.content_hash:
            raise ValueError("payload bytes do not match their declared content_hash")
        object.__setattr__(
            self,
            "_verified_content",
            (self.content_hash, content),
        )

    def inline_bytes(self) -> bytes:
        if isinstance(self.body, BlobPayloadBody):
            raise ValueError("blob payload content must be resolved before decoding")
        return self.body.content_bytes()

    @classmethod
    def from_inline_bytes(
        cls,
        *,
        id: str,
        schema_id: str,
        codec_id: str,
        codec_version: int,
        media_type: str,
        content: bytes,
    ) -> CommandPayload:
        """Build a trusted inline payload while hashing immutable bytes once."""

        content_hash = sha256_content_hash(content)
        payload = cls.model_construct(
            id=id,
            schema_id=schema_id,
            codec_id=codec_id,
            codec_version=codec_version,
            media_type=media_type,
            content_hash=content_hash,
            size_bytes=len(content),
            body=InlinePayloadBody.from_bytes(content),
        )
        object.__setattr__(payload, "_verified_content", (content_hash, content))
        return payload


def command_payload_from_bytes(
    *,
    id: str,
    schema_id: str,
    codec_id: str,
    codec_version: int,
    media_type: str,
    content: bytes,
    blob_ref: str | None = None,
) -> CommandPayload:
    """Build an inline or externally stored envelope from exact encoded bytes."""

    if blob_ref is None:
        return CommandPayload.from_inline_bytes(
            id=id,
            schema_id=schema_id,
            codec_id=codec_id,
            codec_version=codec_version,
            media_type=media_type,
            content=content,
        )
    return CommandPayload(
        id=id,
        schema_id=schema_id,
        codec_id=codec_id,
        codec_version=codec_version,
        media_type=media_type,
        content_hash=sha256_content_hash(content),
        size_bytes=len(content),
        body=BlobPayloadBody(ref=blob_ref),
    )


def _validate_content_segment(value: str) -> str:
    if not value or "\\" in value:
        msg = "content ref field must be a single path segment"
        raise ValueError(msg)
    path = PurePosixPath(value)
    if path.name != value or path.is_absolute() or ".." in path.parts:
        msg = "content ref field must be a single path segment"
        raise ValueError(msg)
    return value
