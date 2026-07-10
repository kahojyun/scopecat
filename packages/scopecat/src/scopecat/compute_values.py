"""Small immutable runtime values supplied to public compute functions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ResolvedRoute:
    """A resolved route stripped of runtime graph and configuration internals."""

    port_id: str
    resource_id: str
    capabilities: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    product_axis_order: tuple[str, ...] = ()


__all__ = ["ResolvedRoute"]
