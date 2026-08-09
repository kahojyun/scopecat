"""Shared logical-port and run resource-requirement identities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, override

from scopecat.kernel.symbols import SymbolId


@dataclass(frozen=True, slots=True)
class LogicalResourcePortId:
    """Hygienic identity of one logical resource requirement."""

    symbol: SymbolId

    @property
    def qualified_name(self) -> str:
        return self.symbol.qualified_name

    @property
    def scope(self) -> tuple[str, ...]:
        return self.symbol.scope

    @property
    def local_id(self) -> str:
        return self.symbol.local_id

    def prefixed(self, *scope: str) -> LogicalResourcePortId:
        return LogicalResourcePortId(self.symbol.prefixed(*scope))

    @override
    def __str__(self) -> str:
        return self.qualified_name


@dataclass(frozen=True, slots=True)
class ResourceRoleSelector:
    """Structural selection of a configured resource role."""

    kind: Literal["default", "exact", "any"] = "default"
    role_id: str | None = None

    def __post_init__(self) -> None:
        if self.kind == "exact":
            if not self.role_id:
                raise ValueError("an exact resource role requires a non-empty id")
        elif self.role_id is not None:
            raise ValueError(f"resource role kind {self.kind!r} cannot carry an id")

    @property
    def description(self) -> str:
        if self.kind == "exact":
            return f"role {self.role_id!r}"
        return f"{self.kind} role"


DEFAULT_RESOURCE_ROLE = ResourceRoleSelector()
ANY_RESOURCE_ROLE = ResourceRoleSelector(kind="any")

type ResourceRoleInput = str | ResourceRoleSelector | None


def resource_role(value: str) -> ResourceRoleSelector:
    """Select one exact configured resource role."""

    return ResourceRoleSelector(kind="exact", role_id=value)


def normalize_resource_role(value: ResourceRoleInput) -> ResourceRoleSelector:
    """Normalize public shorthand to one explicit structural selector."""

    if value is None:
        return DEFAULT_RESOURCE_ROLE
    if isinstance(value, str):
        return resource_role(value)
    return value


@dataclass(frozen=True, slots=True)
class ResourceRequirement:
    """Logical resource identity required by one complete run."""

    id: str
    kind: Literal["instrument"] = "instrument"

    def __post_init__(self) -> None:
        if not self.id:
            msg = "resource requirement id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DomainTargetRequirement:
    """One domain target and the exact instrument footprint this run requires."""

    id: str
    kind: str
    instrument_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.id or not self.kind:
            msg = "domain target requirement identity must be non-empty"
            raise ValueError(msg)
        if len(self.instrument_ids) != len(set(self.instrument_ids)):
            msg = "domain target requirement instrument ids must be unique"
            raise ValueError(msg)


def logical_resource_port_id(
    value: str | SymbolId,
) -> LogicalResourcePortId:
    """Create an unscoped port id or wrap an existing structural symbol."""

    symbol = value if isinstance(value, SymbolId) else SymbolId(local_id=value)
    return LogicalResourcePortId(symbol)
