"""Typed adapters that project declared state onto logical resources."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from scopecat.authoring._module_context import DefinitionResource
from scopecat.kernel.instrument_members import PropertyRef
from scopecat.program.state import StateBinding

type StateTarget = tuple[
    DefinitionResource,
    Mapping[PropertyRef, StateBinding],
]


class StateProjector[StateT](Protocol):
    """A typed authoring object that can lower one declared state.

    Instrument packages implement this protocol on their scalar and grouped
    symbolic clients.  This keeps the root authoring layer independent of any
    particular state declaration frontend.
    """

    def state_targets(
        self,
        state: StateT,
        /,
    ) -> Sequence[StateTarget]:
        """Pair each owned logical resource with its property assignments."""
        ...


__all__ = [
    "StateProjector",
    "StateTarget",
]
