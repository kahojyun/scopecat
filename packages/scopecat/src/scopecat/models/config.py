"""Configuration lifecycle models."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.models.parameter import (
    ParameterBuildSnapshot,
    ParameterCatalog,
    ParameterState,
    ParameterTable,
)
from scopecat.parameters import build_parameter_snapshot


class _HasId(Protocol):
    id: str


def _ensure_unique[T: _HasId](items: list[T], label: str) -> list[T]:
    seen: set[str] = set()
    for item in items:
        item_id = item.id
        if item_id in seen:
            msg = f"duplicate {label} id: {item_id}"
            raise ValueError(msg)
        seen.add(item_id)
    return items


class Device(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str = "device"
    channels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    endpoints: list[str] = Field(min_length=2)
    kind: str = "link"
    metadata: dict[str, Any] = Field(default_factory=dict)


class Channel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    device_id: str | None = None
    direction: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DeviceTopology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    devices: list[Device]
    links: list[Link] = Field(default_factory=list)
    channels: list[Channel] = Field(default_factory=list)

    @field_validator("devices")
    @classmethod
    def validate_devices(cls, value: list[Device]) -> list[Device]:
        return _ensure_unique(value, "device")

    @field_validator("links")
    @classmethod
    def validate_links(cls, value: list[Link]) -> list[Link]:
        return _ensure_unique(value, "link")

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, value: list[Channel]) -> list[Channel]:
        return _ensure_unique(value, "channel")


class Instrument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    channels: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstrumentRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruments: list[Instrument]

    @field_validator("instruments")
    @classmethod
    def validate_instruments(cls, value: list[Instrument]) -> list[Instrument]:
        return _ensure_unique(value, "instrument")


class ConnectionResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    instrument_id: str
    kind: str = "offline"
    resource_hint: str | None = None


class ConnectionProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connections: list[ConnectionResource] = Field(default_factory=list)

    @field_validator("connections")
    @classmethod
    def validate_connections(
        cls, value: list[ConnectionResource]
    ) -> list[ConnectionResource]:
        return _ensure_unique(value, "connection")


class SystemSpec(BaseModel):
    """Stable system topology and logical parameter definitions."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.system_spec.v0"] = "scopecat.system_spec.v0"
    id: str
    workspace_id: str
    device_under_test_id: str
    device_topology: DeviceTopology
    instrument_registry: InstrumentRegistry
    parameter_catalog: ParameterCatalog
    metadata: dict[str, Any] = Field(default_factory=dict)


class EnvironmentSpec(BaseModel):
    """Environment-specific connection resources."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.environment_spec.v0"] = (
        "scopecat.environment_spec.v0"
    )
    id: str
    workspace_id: str
    connection_profile: ConnectionProfile = Field(default_factory=ConnectionProfile)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConfigProfileSnapshot(BaseModel):
    """Immutable config profile snapshot used by runs and ConfigRegistry entries."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.config_profile_snapshot.v0"] = (
        "scopecat.config_profile_snapshot.v0"
    )
    id: str
    system: SystemSpec
    environment: EnvironmentSpec
    parameter_state: ParameterState
    parameter_build: ParameterBuildSnapshot | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def refresh_parameter_build(self) -> ConfigProfileSnapshot:
        self.parameter_build = build_parameter_snapshot(
            catalog=self.system.parameter_catalog,
            parameter_state=self.parameter_state,
        )
        return self

    @property
    def workspace_id(self) -> str:
        return self.system.workspace_id

    @property
    def device_under_test_id(self) -> str:
        return self.system.device_under_test_id

    @property
    def device_topology(self) -> DeviceTopology:
        return self.system.device_topology

    @property
    def instrument_registry(self) -> InstrumentRegistry:
        return self.system.instrument_registry

    @property
    def parameter_catalog(self) -> ParameterCatalog:
        return self.system.parameter_catalog

    @property
    def connection_profile(self) -> ConnectionProfile:
        return self.environment.connection_profile

    @property
    def parameter_tables(self) -> list[ParameterTable]:
        if self.parameter_build is not None:
            return self.parameter_build.tables
        return self.parameter_state.tables


def snapshot_config_profile(
    *,
    profile_id: str,
    system: SystemSpec,
    environment: EnvironmentSpec,
    parameter_state: ParameterState,
    metadata: dict[str, Any] | None = None,
) -> ConfigProfileSnapshot:
    """Freeze split config content as an immutable runtime snapshot."""

    parameter_build = build_parameter_snapshot(
        catalog=system.parameter_catalog,
        parameter_state=parameter_state,
    )
    return ConfigProfileSnapshot(
        id=profile_id,
        system=system,
        environment=environment,
        parameter_state=parameter_state,
        parameter_build=parameter_build,
        metadata=dict(metadata or {}),
    )


def config_content_equal(
    left: ConfigProfileSnapshot,
    right: ConfigProfileSnapshot,
) -> bool:
    """Compare config content while ignoring lifecycle schema fields."""

    return _config_content(left) == _config_content(right)


def _config_content(config: ConfigProfileSnapshot) -> dict[str, Any]:
    return config.model_dump(
        mode="python",
        exclude={"schema_version"},
    )
