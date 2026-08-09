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
from scopecat.records.instrument import (
    InstrumentPropertyState,
    property_target_identity,
)
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


class InstrumentBindingSpec(BaseModel):
    """Provider-visible identity and connection for one configured instrument."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(min_length=1)]
    driver_id: Annotated[str, Field(min_length=1)]
    connection: InstrumentConnection


type InstrumentRunStartPolicy = Literal["preserve", "apply_default_state"]
type InstrumentSuccessAction = Literal["release", "restore_prepared_state"]
type InstrumentFailureAction = Literal[
    "abort_and_release",
    "abort_then_safe_state",
]


class InstrumentSpec(BaseModel):
    """Configured instrument with a stable physical access domain.

    Default and safe states are sparse patches over freshly observed state.
    """

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(min_length=1)]
    exclusivity_key: Annotated[str, Field(min_length=1)]
    driver_id: Annotated[str, Field(min_length=1)]
    connection: InstrumentConnection
    default_state: list[InstrumentPropertyState] = Field(default_factory=list)
    run_start: InstrumentRunStartPolicy
    success_action: InstrumentSuccessAction
    safe_state: list[InstrumentPropertyState] = Field(default_factory=list)
    failure_action: InstrumentFailureAction

    @field_validator("default_state", "safe_state")
    @classmethod
    def validate_unique_state_targets(
        cls,
        value: list[InstrumentPropertyState],
    ) -> list[InstrumentPropertyState]:
        identities = [
            property_target_identity(
                item.interface_id,
                item.component_path,
                item.property_id,
            )
            for item in value
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("configured state property targets must be unique")
        return value

    @model_validator(mode="after")
    def validate_lifecycle_state(self) -> InstrumentSpec:
        if self.run_start == "apply_default_state" and not self.default_state:
            raise ValueError("apply_default_state requires a non-empty default state")
        if self.failure_action == "abort_then_safe_state" and not self.safe_state:
            raise ValueError("abort_then_safe_state requires a non-empty safe state")
        return self


class InstrumentRegistry(BaseModel):
    """Logical instruments with one owner for each physical access domain."""

    model_config = ConfigDict(extra="forbid")

    instruments: list[InstrumentSpec]

    @field_validator("instruments")
    @classmethod
    def validate_instruments(cls, value: list[InstrumentSpec]) -> list[InstrumentSpec]:
        instruments = _ensure_unique(value, "instrument")
        exclusivity_keys = [instrument.exclusivity_key for instrument in instruments]
        if len(exclusivity_keys) != len(set(exclusivity_keys)):
            raise ValueError("instrument exclusivity keys must be unique")
        return instruments


class ResourceRoleSpec(BaseModel):
    """One documented purpose that authors may select explicitly."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    description: str | None = Field(default=None, min_length=1)


class RoutingEndpoint(BaseModel):
    """One logical binding onto a physical interface component."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    interface_id: InterfaceId
    entity_id: str | None = None
    channel_id: str | None = None
    component_path: tuple[
        Annotated[str, Field(min_length=1)],
        ...,
    ] = ()


class ResourceRoute(BaseModel):
    """A selectable physical resource and all endpoints it owns together."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)
    role_id: str | None = Field(default=None, min_length=1)
    endpoints: list[RoutingEndpoint] = Field(min_length=1)

    @field_validator("endpoints")
    @classmethod
    def validate_endpoints(cls, value: list[RoutingEndpoint]) -> list[RoutingEndpoint]:
        seen: set[tuple[str, str | None, str | None, tuple[str, ...]]] = set()
        for endpoint in value:
            identity = (
                endpoint.interface_id,
                endpoint.entity_id,
                endpoint.channel_id,
                endpoint.component_path,
            )
            if identity in seen:
                msg = (
                    "duplicate resource route endpoint: "
                    f"interface={endpoint.interface_id}, entity={endpoint.entity_id}, "
                    f"channel={endpoint.channel_id}, "
                    f"component_path={endpoint.component_path}"
                )
                raise ValueError(msg)
            seen.add(identity)
        return value


class RoutingGraph(BaseModel):
    """Finite static resource-route catalog in an accepted system snapshot.

    Planning may project logical interface and entity selections through this
    catalog, but it never uses it for live availability, load balancing, or
    implicit failover.
    """

    model_config = ConfigDict(extra="forbid")

    roles: list[ResourceRoleSpec] = Field(default_factory=list)
    routes: list[ResourceRoute] = Field(default_factory=list)

    @field_validator("roles")
    @classmethod
    def validate_roles(cls, value: list[ResourceRoleSpec]) -> list[ResourceRoleSpec]:
        return _ensure_unique(value, "resource role")

    @field_validator("routes")
    @classmethod
    def validate_routes(cls, value: list[ResourceRoute]) -> list[ResourceRoute]:
        return _ensure_unique(value, "resource route")

    @model_validator(mode="after")
    def validate_role_references_and_ownership(self) -> RoutingGraph:
        role_ids = {role.id for role in self.roles}
        ownership: dict[tuple[str | None, str, str | None], str] = {}
        for route in self.routes:
            if route.role_id is not None and route.role_id not in role_ids:
                msg = (
                    f"resource route {route.id!r} references unknown role "
                    f"{route.role_id!r}"
                )
                raise ValueError(msg)
            for endpoint in route.endpoints:
                identity = (route.role_id, endpoint.interface_id, endpoint.entity_id)
                owner = ownership.get(identity)
                if owner is not None and owner != route.id:
                    msg = (
                        "resource endpoint has multiple routes for the same role: "
                        f"routes={owner!r}, {route.id!r}, role={route.role_id!r}, "
                        f"interface={endpoint.interface_id}, "
                        f"entity={endpoint.entity_id!r}"
                    )
                    raise ValueError(msg)
                ownership[identity] = route.id
        return self


class DomainTargetInstrumentMember(BaseModel):
    """One independently addressable instrument coordinated by a domain target."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["instrument"] = "instrument"
    role: str = Field(min_length=1)
    instrument_id: str = Field(min_length=1)


class DomainTargetPrivateEndpoint(BaseModel):
    """One target-owned connection with no standalone instrument contract."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["private_endpoint"] = "private_endpoint"
    role: str = Field(min_length=1)
    connection: InstrumentConnection


type DomainTargetMember = Annotated[
    DomainTargetInstrumentMember | DomainTargetPrivateEndpoint,
    Field(discriminator="kind"),
]


class DomainTargetBinding(BaseModel):
    """One composite target instance and its complete physical membership."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    exclusivity_key: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    members: list[DomainTargetMember] = Field(default_factory=list)

    @field_validator("members")
    @classmethod
    def validate_members(
        cls,
        value: list[DomainTargetMember],
    ) -> list[DomainTargetMember]:
        roles = [member.role for member in value]
        if len(roles) != len(set(roles)):
            raise ValueError("domain target member roles must be unique")
        instrument_ids = [
            member.instrument_id
            for member in value
            if isinstance(member, DomainTargetInstrumentMember)
        ]
        if len(instrument_ids) != len(set(instrument_ids)):
            raise ValueError("domain target instrument members must be unique")
        return value

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        """Return only independently registered members used for resource claims."""

        return tuple(
            member.instrument_id
            for member in self.members
            if isinstance(member, DomainTargetInstrumentMember)
        )

    @property
    def private_endpoints(self) -> tuple[DomainTargetPrivateEndpoint, ...]:
        """Return connections visible only to the selected target backend."""

        return tuple(
            member
            for member in self.members
            if isinstance(member, DomainTargetPrivateEndpoint)
        )


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
    def validate_domain_target_members(self) -> SystemSpec:
        target = self.domain_target
        if target is None:
            return self
        known_instrument_ids = {
            instrument.id for instrument in self.instrument_registry.instruments
        }
        for instrument_id in target.instrument_ids:
            if instrument_id not in known_instrument_ids:
                raise ValueError(
                    f"unknown domain target instrument member: {instrument_id}"
                )
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


def instrument_bindings(
    config: ConfigProfileSnapshot,
) -> tuple[InstrumentBindingSpec, ...]:
    """Project configured instruments onto the provider-visible binding ABI."""

    return tuple(
        InstrumentBindingSpec(
            id=instrument.id,
            driver_id=instrument.driver_id,
            connection=instrument.connection.model_copy(deep=True),
        )
        for instrument in config.instrument_registry.instruments
    )


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
