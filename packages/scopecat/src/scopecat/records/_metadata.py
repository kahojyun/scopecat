"""Shared validation for durable open JSON metadata objects."""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BeforeValidator,
    ConfigDict,
    JsonValue,
    TypeAdapter,
)

_METADATA_ADAPTER = TypeAdapter(
    dict[str, JsonValue],
    config=ConfigDict(allow_inf_nan=False),
)


def _validate_json_metadata(value: object) -> dict[str, JsonValue]:
    return _METADATA_ADAPTER.validate_python(value)


type JsonMetadata = Annotated[
    dict[str, JsonValue],
    BeforeValidator(_validate_json_metadata),
]
