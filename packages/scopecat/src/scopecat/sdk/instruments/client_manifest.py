"""Lightweight package manifest contract for generated instrument clients."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from scopecat.sdk.instruments.declarations import Member, MemberObservation


@dataclass(frozen=True, slots=True)
class AcquisitionPublicNames:
    """Optional package-local names for one generated acquisition surface."""

    acquisition: Callable[..., object] | MemberObservation
    readback: str | None = None
    products: str | None = None


@dataclass(frozen=True, slots=True)
class InterfaceSurfaceRegistration:
    """Select one declared interface for public client generation."""

    interface_type: type[object]
    acquisition_names: tuple[AcquisitionPublicNames, ...] = ()


type CompositeMemberNameOverride = tuple[Member[object], str]
type CompositeMethodNameOverride = tuple[Callable[..., object] | MemberObservation, str]


@dataclass(frozen=True, slots=True)
class CompositeSurfaceRegistration:
    """Select an explicit package-local composition of existing interfaces."""

    name: str
    interface_types: tuple[type[object], ...]
    driver_optional_flag: str | None = None
    member_name_overrides: tuple[CompositeMemberNameOverride, ...] = ()
    method_name_overrides: tuple[CompositeMethodNameOverride, ...] = ()
    acquisition_names: tuple[AcquisitionPublicNames, ...] = ()


type SurfaceRegistration = InterfaceSurfaceRegistration | CompositeSurfaceRegistration


@dataclass(frozen=True, slots=True)
class ClientPackageManifest:
    """Standalone manifest for a package that only publishes client surfaces."""

    surfaces: tuple[SurfaceRegistration, ...]
    public_types: tuple[object, ...] = ()
    static_exports: tuple[tuple[str, str], ...] = ()


class InstrumentClientManifest(Protocol):
    """Structural input required to generate one importable client package."""

    surfaces: tuple[SurfaceRegistration, ...]
    public_types: tuple[object, ...]
    static_exports: tuple[tuple[str, str], ...]


__all__ = [
    "AcquisitionPublicNames",
    "ClientPackageManifest",
    "CompositeMemberNameOverride",
    "CompositeMethodNameOverride",
    "CompositeSurfaceRegistration",
    "InstrumentClientManifest",
    "InterfaceSurfaceRegistration",
    "SurfaceRegistration",
]
