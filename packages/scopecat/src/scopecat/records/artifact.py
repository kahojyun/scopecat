"""Artifact, dataset, record, and opaque command payload models."""

from __future__ import annotations

from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat.kernel.content_identity import sha256_content_hash
from scopecat.records._metadata import JsonMetadata

type Sha256ContentHash = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]
type _NonEmptyText = Annotated[str, Field(min_length=1)]


class RunContentEntry(BaseModel):
    """One content-addressable run-local manifest entry."""

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
        return _validate_run_segment(value)

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value or "\\" in value:
            raise ValueError("run content filename must be a basename")
        path = PurePosixPath(value)
        if path.name != value or path.is_absolute() or ".." in path.parts:
            raise ValueError("run content filename must be a basename")
        return value


class InlinePayloadBody(BaseModel):
    """Base64 wire representation of one complete encoded payload."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    kind: Literal["inline"] = "inline"
    content_base64: str

    @field_validator("content_base64")
    @classmethod
    def validate_canonical_base64(cls, value: str) -> str:
        try:
            decoded = b64decode(value, validate=True)
        except (BinasciiError, ValueError) as error:
            raise ValueError("inline payload content must be valid base64") from error
        if b64encode(decoded).decode("ascii") != value:
            raise ValueError("inline payload content must use canonical base64")
        return value

    @classmethod
    def from_bytes(cls, content: bytes) -> InlinePayloadBody:
        return cls(content_base64=b64encode(content).decode("ascii"))

    def content_bytes(self) -> bytes:
        return b64decode(self.content_base64, validate=True)


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
    operation_id: str | None = None
    semantic_operation_id: str | None = None
    implementation_id: str | None = None
    point_index: int | None = Field(default=None, ge=0)
    metadata: JsonMetadata = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_inline_content(self) -> CommandPayload:
        if isinstance(self.body, InlinePayloadBody):
            self.verify_content(self.body.content_bytes())
        elif self.body.ref != self.content_hash:
            raise ValueError("payload blob ref must equal content_hash")
        return self

    def verify_content(self, content: bytes) -> None:
        if len(content) != self.size_bytes:
            raise ValueError(
                "payload byte length does not match its declared size_bytes"
            )
        if sha256_content_hash(content) != self.content_hash:
            raise ValueError("payload bytes do not match their declared content_hash")

    def inline_bytes(self) -> bytes:
        if isinstance(self.body, BlobPayloadBody):
            raise ValueError("blob payload content must be resolved before decoding")
        return self.body.content_bytes()


def command_payload_from_bytes(
    *,
    id: str,
    schema_id: str,
    codec_id: str,
    codec_version: int,
    media_type: str,
    content: bytes,
    blob_ref: str | None = None,
    operation_id: str | None = None,
    semantic_operation_id: str | None = None,
    implementation_id: str | None = None,
    point_index: int | None = None,
    metadata: Mapping[str, JsonValue] | None = None,
) -> CommandPayload:
    """Build an inline or externally stored envelope from exact encoded bytes."""

    body: CommandPayloadBody = (
        InlinePayloadBody.from_bytes(content)
        if blob_ref is None
        else BlobPayloadBody(ref=blob_ref)
    )
    return CommandPayload(
        id=id,
        schema_id=schema_id,
        codec_id=codec_id,
        codec_version=codec_version,
        media_type=media_type,
        content_hash=sha256_content_hash(content),
        size_bytes=len(content),
        body=body,
        operation_id=operation_id,
        semantic_operation_id=semantic_operation_id,
        implementation_id=implementation_id,
        point_index=point_index,
        metadata=dict(metadata or {}),
    )


def _validate_run_segment(value: str) -> str:
    if not value or "\\" in value:
        msg = "run-local ref field must be a single path segment"
        raise ValueError(msg)
    path = PurePosixPath(value)
    if path.name != value or path.is_absolute() or ".." in path.parts:
        msg = "run-local ref field must be a single path segment"
        raise ValueError(msg)
    return value
