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


def validate_json_metadata(value: object) -> dict[str, JsonValue]:
    """Return one strictly validated, finite JSON metadata object."""

    return _METADATA_ADAPTER.validate_python(value)


type JsonMetadata = Annotated[
    dict[str, JsonValue],
    BeforeValidator(validate_json_metadata),
]


__all__ = ["JsonMetadata", "validate_json_metadata"]
