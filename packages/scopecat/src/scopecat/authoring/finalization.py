"""Typed adapters for normal-completion instrument state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from scopecat.authoring._module_context import DefinitionResource
from scopecat.kernel.instrument_members import PropertyRef
from scopecat.program.state import StateBinding

type FinalizationTarget = tuple[
    DefinitionResource,
    Mapping[PropertyRef, StateBinding],
]


class Finalizable[StateT](Protocol):
    """A typed authoring object that can lower state for finalization.

    Instrument packages implement this protocol on their scalar and grouped
    symbolic clients.  This keeps the root authoring layer independent of any
    particular state declaration frontend.
    """

    def finalization_targets(
        self,
        state: StateT,
        /,
    ) -> Sequence[FinalizationTarget]:
        """Pair each owned logical resource with its property assignments."""
        ...


__all__ = [
    "Finalizable",
    "FinalizationTarget",
]
