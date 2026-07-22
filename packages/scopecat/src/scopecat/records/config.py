"""Configuration lifecycle models."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from scopecat.records._metadata import JsonMetadata
from scopecat.records.entity import EntityRef
from scopecat.records.parameter import (
    ParameterCatalog,
    ParameterSnapshot,
)

type ConfigContentHash = Annotated[
    str,
    Field(pattern=r"^sha256:[0-9a-f]{64}$"),
]


class _HasId(Protocol):
    @property
    def id(self) -> str: ...


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


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    endpoints: list[str] = Field(min_length=2)
    kind: str = "link"


class TopologyLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    signal: str | None = None
    endpoints: list[str] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)


class SharedResourceGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: str
    members: list[str] = Field(default_factory=list)
    metadata: JsonMetadata = Field(default_factory=dict)


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
    metadata: JsonMetadata = Field(default_factory=dict)


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


class InstrumentRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instruments: list[InstrumentSpec]

    @field_validator("instruments")
    @classmethod
    def validate_instruments(cls, value: list[InstrumentSpec]) -> list[InstrumentSpec]:
        return _ensure_unique(value, "instrument")


class RoutingEndpointBinding(BaseModel):
    """Accepted physical ownership fact for one instrument endpoint.

    A binding is reproducible configuration, not a runtime alternative. Devices
    that change a physical path, such as switches or valves, are modeled as
    explicit state or action effects instead of replacing this ownership fact.
    """

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    entity_id: str | None = None
    channel_id: str | None = None
    metadata: JsonMetadata = Field(default_factory=dict)


class RoutingGraph(BaseModel):
    """Finite static endpoint index stored in an accepted system snapshot.

    Planning may project logical capability and entity selections through this
    index, but it never uses it for live availability, load balancing, or
    implicit failover.
    """

    model_config = ConfigDict(extra="forbid")

    bindings: list[RoutingEndpointBinding] = Field(default_factory=list)

    @field_validator("bindings")
    @classmethod
    def validate_bindings(
        cls, value: list[RoutingEndpointBinding]
    ) -> list[RoutingEndpointBinding]:
        seen: set[tuple[str, str, str | None, str | None]] = set()
        for binding in value:
            identity = (
                binding.instrument_id,
                binding.capability,
                binding.entity_id,
                binding.channel_id,
            )
            if identity in seen:
                msg = (
                    "duplicate routing endpoint binding: "
                    f"instrument={binding.instrument_id}, "
                    f"capability={binding.capability}, "
                    f"entity={binding.entity_id}, channel={binding.channel_id}"
                )
                raise ValueError(msg)
            seen.add(identity)
        return value


class DomainTargetBinding(BaseModel):
    """The one target instance and adapter family selected by a system."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    instrument_ids: list[Annotated[str, Field(min_length=1)]] = Field(
        default_factory=list
    )

    @field_validator("instrument_ids")
    @classmethod
    def validate_instrument_ids(
        cls,
        value: list[str],
    ) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("domain target instrument ids must be unique")
        return value


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

    schema_version: Literal["scopecat.system_spec.v3"] = "scopecat.system_spec.v3"
    id: str
    workspace_id: str
    primary_entity_id: str
    topology: Topology
    instrument_registry: InstrumentRegistry
    routing: RoutingGraph = Field(default_factory=RoutingGraph)
    domain_target: DomainTargetBinding | None
    parameter_catalog: ParameterCatalog

    @model_validator(mode="after")
    def validate_domain_target_instruments(self) -> SystemSpec:
        target = self.domain_target
        if target is None:
            return self
        known_instrument_ids = {
            instrument.id for instrument in self.instrument_registry.instruments
        }
        for instrument_id in target.instrument_ids:
            if instrument_id not in known_instrument_ids:
                raise ValueError(f"unknown domain target instrument: {instrument_id}")
        return self


class EnvironmentSpec(BaseModel):
    """Environment-specific connection resources."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.environment_spec.v1"] = (
        "scopecat.environment_spec.v1"
    )
    id: str
    workspace_id: str
    connection_profile: ConnectionProfile = Field(default_factory=ConnectionProfile)


class ConfigProfileSnapshot(BaseModel):
    """Immutable config profile snapshot used by runs and ConfigRegistry entries."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["scopecat.config_profile_snapshot.v2"] = (
        "scopecat.config_profile_snapshot.v2"
    )
    id: str
    system: SystemSpec
    environment: EnvironmentSpec
    parameter_snapshot: ParameterSnapshot

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
    def domain_target(self) -> DomainTargetBinding | None:
        return self.system.domain_target

    @property
    def parameter_catalog(self) -> ParameterCatalog:
        return self.system.parameter_catalog

    @property
    def connection_profile(self) -> ConnectionProfile:
        return self.environment.connection_profile


def snapshot_config_profile(
    *,
    profile_id: str,
    system: SystemSpec,
    environment: EnvironmentSpec,
    parameter_snapshot: ParameterSnapshot,
) -> ConfigProfileSnapshot:
    """Freeze split config content as an immutable runtime snapshot."""

    return ConfigProfileSnapshot(
        id=profile_id,
        system=system,
        environment=environment,
        parameter_snapshot=parameter_snapshot,
    )


def config_content_equal(
    left: ConfigProfileSnapshot,
    right: ConfigProfileSnapshot,
) -> bool:
    """Compare config content while ignoring lifecycle schema fields."""

    return _config_content(left) == _config_content(right)


def config_content_hash(config: ConfigProfileSnapshot) -> ConfigContentHash:
    """Return a stable content address for a complete config snapshot."""

    content = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _config_content(config: ConfigProfileSnapshot) -> dict[str, object]:
    return config.model_dump(
        mode="python",
        exclude={"schema_version"},
    )
