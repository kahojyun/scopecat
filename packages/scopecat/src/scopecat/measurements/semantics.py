"""Dependency-light semantic contracts for pure measurement transforms."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_serializer,
    field_validator,
)

from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.frozen import (
    FrozenMapping,
    freeze_json_mapping,
    thaw_json_value,
)

type MeasurementTransformRate = Literal["point"]


def _empty_semantic_parameters() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


class MeasurementTransformSemanticContract(BaseModel):
    """Data-only pure meaning that a host or domain realization may satisfy."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["scopecat.measurement_transform_semantic.v1"] = (
        "scopecat.measurement_transform_semantic.v1"
    )
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    purity: Literal["pure"] = "pure"
    portability: Literal["portable", "host_only"] = "portable"
    parameters: Mapping[str, JsonValue] = Field(
        default_factory=_empty_semantic_parameters,
    )

    @field_validator("parameters", mode="after")
    @classmethod
    def freeze_parameters(
        cls,
        value: Mapping[str, JsonValue],
    ) -> FrozenMapping[str, JsonValue]:
        return freeze_json_mapping(
            value,
            path="measurement transform semantic parameters",
        )

    @field_serializer("parameters")
    def serialize_parameters(self, value: Mapping[str, JsonValue]) -> object:
        return thaw_json_value(value)

    @property
    def contract_fingerprint(self) -> str:
        return stable_content_hash(content_fingerprint(self))
