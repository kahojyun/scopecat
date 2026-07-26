"""Dependency-light semantic contracts for pure measurement transforms."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.kernel.frozen import (
    FrozenMapping,
    freeze_json_mapping,
)
from scopecat.kernel.json_types import JsonValue


def _empty_semantic_parameters() -> FrozenMapping[str, JsonValue]:
    return FrozenMapping()


@dataclass(frozen=True, slots=True)
class MeasurementTransformSemanticContract:
    """Data-only pure meaning realized by a host transform."""

    id: str
    version: str
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
        object.__setattr__(
            self,
            "parameters",
            freeze_json_mapping(
                self.parameters,
                path="measurement transform semantic parameters",
            ),
        )
