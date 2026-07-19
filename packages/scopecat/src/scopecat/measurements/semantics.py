"""Dependency-light semantic contracts for pure measurement transforms."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import ClassVar, Literal

from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.frozen import (
    FrozenMapping,
    freeze_json_mapping,
    thaw_json_value,
)
from scopecat.kernel.json_types import JsonValue

type MeasurementTransformPortability = Literal["portable", "host_only"]

_SEMANTIC_CONTRACT_SCHEMA = "scopecat.measurement_transform_semantic.v1"
_PORTABILITY_VALUES = frozenset({"portable", "host_only"})


def _empty_semantic_parameters() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True)
class MeasurementTransformSemanticContract:
    """Data-only pure meaning that a host or domain realization may satisfy."""

    schema_version: ClassVar[Literal["scopecat.measurement_transform_semantic.v1"]] = (
        _SEMANTIC_CONTRACT_SCHEMA
    )
    purity: ClassVar[Literal["pure"]] = "pure"

    id: str
    version: str
    portability: MeasurementTransformPortability = "portable"
    parameters: Mapping[str, JsonValue] = field(
        default_factory=_empty_semantic_parameters
    )

    def __post_init__(self) -> None:
        if not self.id:
            msg = "measurement transform semantic id must be non-empty"
            raise ValueError(msg)
        if not self.version:
            msg = "measurement transform semantic version must be non-empty"
            raise ValueError(msg)
        if self.portability not in _PORTABILITY_VALUES:
            msg = "measurement transform portability must be portable or host_only"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "parameters",
            freeze_json_mapping(
                self.parameters,
                path="measurement transform semantic parameters",
            ),
        )

    @property
    def contract_fingerprint(self) -> str:
        return stable_content_hash(
            {
                "schema": self.schema_version,
                "id": self.id,
                "version": self.version,
                "purity": self.purity,
                "portability": self.portability,
                "parameters": thaw_json_value(self.parameters),
            }
        )
