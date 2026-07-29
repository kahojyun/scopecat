"""Virtual-lab profile models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from scopecat.sdk.instruments import StateValue


class VirtualDeviceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    seed_state: dict[str, StateValue] = Field(default_factory=dict)


class VirtualLabProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format_version: Literal["quantum_lab_demo.virtual_lab_profile.v1"] = (
        "quantum_lab_demo.virtual_lab_profile.v1"
    )
    id: str
    devices: list[VirtualDeviceProfile]


__all__ = [
    "VirtualDeviceProfile",
    "VirtualLabProfile",
]
