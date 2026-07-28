"""Configuration lifecycle models."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal, Protocol

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    field_validator,
    model_validator,
)

from scopecat.kernel.entity import EntityRef
from scopecat.kernel.interface_identity import InterfaceId
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


class Topology(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entities: list[EntityRef] = Field(default_factory=list)

    @field_validator("entities")
    @classmethod
    def validate_entities(cls, value: list[EntityRef]) -> list[EntityRef]:
        return _ensure_unique(value, "entity")

    def entity(self, entity_id: str) -> EntityRef | None:
        for entity in self.entities:
            if entity.id == entity_id:
                return entity
        return None


class _InstrumentConnection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    options: dict[str, JsonValue] = Field(default_factory=dict)


class VirtualInstrumentConnection(_InstrumentConnection):
    kind: Literal["virtual"] = "virtual"


class TcpipSocketInstrumentConnection(_InstrumentConnection):
    kind: Literal["tcpip_socket"] = "tcpip_socket"
    host: Annotated[str, Field(min_length=1)]
    port: int = Field(ge=1, le=65535)
    timeout_seconds: float = Field(default=5.0, gt=0)


type InstrumentConnection = Annotated[
    VirtualInstrumentConnection | TcpipSocketInstrumentConnection,
    Field(discriminator="kind"),
]


class InstrumentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=1)]
    driver_id: Annotated[str, Field(min_length=1)]
    connection: InstrumentConnection


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
    explicit desired-state effects or domain programs instead of replacing this
    ownership fact.
    """

    model_config = ConfigDict(extra="forbid")

    instrument_id: str = Field(min_length=1)
    interface_id: InterfaceId
    entity_id: str | None = None
    channel_id: str | None = None


class RoutingGraph(BaseModel):
    """Finite static endpoint index stored in an accepted system snapshot.

    Planning may project logical interface and entity selections through this
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
                binding.interface_id,
                binding.entity_id,
                binding.channel_id,
            )
            if identity in seen:
                msg = (
                    "duplicate routing endpoint binding: "
                    f"instrument={binding.instrument_id}, "
                    f"interface={binding.interface_id}, "
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


class SystemSpec(BaseModel):
    """Stable system topology and logical parameter definitions."""

    model_config = ConfigDict(extra="forbid")

    id: str
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


class ConfigProfileSnapshot(BaseModel):
    """Immutable config profile snapshot used by runs and ConfigRegistry entries."""

    model_config = ConfigDict(extra="forbid")

    id: str
    system: SystemSpec
    parameter_snapshot: ParameterSnapshot

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


def snapshot_config_profile(
    *,
    profile_id: str,
    system: SystemSpec,
    parameter_snapshot: ParameterSnapshot,
) -> ConfigProfileSnapshot:
    """Build one immutable runtime configuration snapshot."""

    return ConfigProfileSnapshot(
        id=profile_id,
        system=system,
        parameter_snapshot=parameter_snapshot,
    )


def config_content_equal(
    left: ConfigProfileSnapshot,
    right: ConfigProfileSnapshot,
) -> bool:
    """Compare complete runtime configuration values."""

    return left == right


def config_content_hash(config: ConfigProfileSnapshot) -> ConfigContentHash:
    """Return a stable content address for a complete config snapshot."""

    content = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()
