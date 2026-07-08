"""Configuration lifecycle models."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scopecat.models.entity import EntityRef
from scopecat.models.parameter import (
    ParameterCatalog,
    ParameterState,
    ParameterTable,
    ParameterViewSnapshot,
)
from scopecat.parameters import ParameterDerivationSet, build_parameter_view


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


class TopologyLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    signal: str | None = None
    endpoints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SharedResourceGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    members: list[str] = Field(default_factory=list)
    max_resources_per_point: int | None = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Channel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    device_id: str | None = None
    direction: str | None = None
    signal: str | None = None
    port: str | None = None
    line_id: str | None = None
    group_ids: list[str] = Field(default_factory=list)
    max_route_ports_per_point: int | None = Field(default=1, ge=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Topology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[EntityRef] = Field(default_factory=list)
    devices: list[Device]
    links: list[Link] = Field(default_factory=list)
    lines: list[TopologyLine] = Field(default_factory=list)
    channels: list[Channel] = Field(default_factory=list)
    groups: list[SharedResourceGroup] = Field(default_factory=list)

    @field_validator("entities")
    @classmethod
    def validate_entities(cls, value: list[EntityRef]) -> list[EntityRef]:
        return _ensure_unique(value, "entity")

    @field_validator("devices")
    @classmethod
    def validate_devices(cls, value: list[Device]) -> list[Device]:
        return _ensure_unique(value, "device")

    @field_validator("links")
    @classmethod
    def validate_links(cls, value: list[Link]) -> list[Link]:
        return _ensure_unique(value, "link")

    @field_validator("lines")
    @classmethod
    def validate_lines(cls, value: list[TopologyLine]) -> list[TopologyLine]:
        return _ensure_unique(value, "line")

    @field_validator("channels")
    @classmethod
    def validate_channels(cls, value: list[Channel]) -> list[Channel]:
        return _ensure_unique(value, "channel")

    @field_validator("groups")
    @classmethod
    def validate_groups(
        cls, value: list[SharedResourceGroup]
    ) -> list[SharedResourceGroup]:
        return _ensure_unique(value, "group")

    def entity(self, entity_id: str) -> EntityRef | None:
        for entity in self.entities:
            if entity.id == entity_id:
                return entity
        return None


class InstrumentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class InstrumentRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruments: list[InstrumentSpec]

    @field_validator("instruments")
    @classmethod
    def validate_instruments(cls, value: list[InstrumentSpec]) -> list[InstrumentSpec]:
        return _ensure_unique(value, "instrument")


class RoutingResource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str = "instrument"
    capabilities: list[str] = Field(default_factory=list)
    served_entities: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoutingChannelBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entity_id: str
    channel_id: str
    line_id: str | None = None
    capability: str | None = None
    group_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoutingEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    resource_id: str
    entity_ids: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    channels: list[str] = Field(default_factory=list)
    bindings: list[RoutingChannelBinding] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoutingGraph(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resources: list[RoutingResource] = Field(default_factory=list)
    edges: list[RoutingEdge] = Field(default_factory=list)

    @field_validator("resources")
    @classmethod
    def validate_resources(cls, value: list[RoutingResource]) -> list[RoutingResource]:
        return _ensure_unique(value, "routing resource")

    @field_validator("edges")
    @classmethod
    def validate_edges(cls, value: list[RoutingEdge]) -> list[RoutingEdge]:
        return _ensure_unique(value, "routing edge")


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
    primary_entity_id: str
    topology: Topology
    instrument_registry: InstrumentRegistry
    routing: RoutingGraph = Field(default_factory=RoutingGraph)
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
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def workspace_id(self) -> str:
        return self.system.workspace_id

    @property
    def primary_entity_id(self) -> str:
        return self.system.primary_entity_id

    @property
    def topology(self) -> Topology:
        return self.system.topology

    @property
    def instrument_registry(self) -> InstrumentRegistry:
        return self.system.instrument_registry

    @property
    def routing(self) -> RoutingGraph:
        return self.system.routing

    @property
    def parameter_catalog(self) -> ParameterCatalog:
        return self.system.parameter_catalog

    @property
    def connection_profile(self) -> ConnectionProfile:
        return self.environment.connection_profile

    @property
    def parameter_tables(self) -> list[ParameterTable]:
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

    return ConfigProfileSnapshot(
        id=profile_id,
        system=system,
        environment=environment,
        parameter_state=parameter_state,
        metadata=dict(metadata or {}),
    )


def build_config_parameters(
    config: ConfigProfileSnapshot,
    *,
    derivations: ParameterDerivationSet | None = None,
) -> ParameterViewSnapshot:
    """Build the in-memory parameter view for planning and authoring."""

    return build_parameter_view(
        catalog=config.parameter_catalog,
        parameter_state=config.parameter_state,
        derivations=derivations,
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
