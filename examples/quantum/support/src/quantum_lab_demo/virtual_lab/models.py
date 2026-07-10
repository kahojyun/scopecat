"""Virtual-lab profile models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from scopecat.instruments import StateValue


class VirtualResponseProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    parameters: dict[str, Any]


class VirtualDeviceProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    response_model_id: str | None = None
    initial_state: dict[str, StateValue] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VirtualLabProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["quantum_lab_demo.virtual_lab_profile.v1"] = (
        "quantum_lab_demo.virtual_lab_profile.v1"
    )
    id: str
    devices: list[VirtualDeviceProfile]
    response_models: list[VirtualResponseProfile] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def device_profile(self, device_id: str) -> VirtualDeviceProfile:
        for device in self.devices:
            if device.id == device_id:
                return device
        raise KeyError(f"virtual lab profile has no device {device_id!r}")

    def response_profile(self, response_id: str) -> VirtualResponseProfile:
        for response in self.response_models:
            if response.id == response_id:
                return response
        raise KeyError(f"virtual lab profile has no response model {response_id!r}")


__all__ = [
    "VirtualDeviceProfile",
    "VirtualLabProfile",
    "VirtualResponseProfile",
]
