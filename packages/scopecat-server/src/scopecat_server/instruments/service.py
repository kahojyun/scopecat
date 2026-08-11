"""Application-service facade for daemon-owned instruments."""

from __future__ import annotations

from .runtime import InstrumentRuntime


class InstrumentService(InstrumentRuntime):
    """Unify instrument catalog, direct-session, and run execution operations.

    The facade is the dependency used by HTTP and daemon application services;
    volatile ownership and reconciliation mechanics remain in the instrument
    runtime module.
    """


__all__ = ["InstrumentService"]
