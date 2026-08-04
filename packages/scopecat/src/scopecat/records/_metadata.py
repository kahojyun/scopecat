"""Shared validation for durable open JSON metadata objects."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, cast

from pydantic import (
    AfterValidator,
    BeforeValidator,
    ConfigDict,
    JsonValue,
    PlainSerializer,
    TypeAdapter,
)

from scopecat.kernel.frozen import freeze_json_mapping, thaw_json_value

_METADATA_ADAPTER = TypeAdapter(
    dict[str, JsonValue],
    config=ConfigDict(allow_inf_nan=False),
)


def validate_json_metadata(value: object) -> dict[str, JsonValue]:
    """Return one strictly validated, finite JSON metadata object."""

    return _METADATA_ADAPTER.validate_python(value)


def freeze_json_metadata(value: Mapping[str, object]) -> Mapping[str, object]:
    """Return one recursively immutable, finite JSON metadata object."""

    validated = validate_json_metadata(thaw_json_value(value))
    return freeze_json_mapping(
        cast("Mapping[str, object]", validated),
        path="metadata",
    )


def _serialize_frozen_json_metadata(value: Mapping[str, object]) -> object:
    return thaw_json_value(value)


type JsonMetadata = Annotated[
    dict[str, JsonValue],
    BeforeValidator(validate_json_metadata),
]

type FrozenJsonMetadata = Annotated[
    Mapping[str, object],
    AfterValidator(freeze_json_metadata),
    PlainSerializer(
        _serialize_frozen_json_metadata,
        return_type=dict[str, JsonValue],
    ),
]


__all__ = [
    "FrozenJsonMetadata",
    "JsonMetadata",
    "freeze_json_metadata",
    "validate_json_metadata",
]
