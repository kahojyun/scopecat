"""Structural identities inside one transient Scopecat program."""

from __future__ import annotations

from dataclasses import dataclass
from typing import override

from scopecat.kernel.qualified_name import qualified_name


@dataclass(frozen=True, slots=True, kw_only=True)
class SymbolId:
    """Hygienic address for a declaration in one typed symbol space."""

    scope: tuple[str, ...] = ()
    local_id: str

    def __post_init__(self) -> None:
        if any(not segment for segment in self.scope):
            msg = "symbol scope segments must be non-empty"
            raise ValueError(msg)
        if not self.local_id:
            msg = "symbol local id must be non-empty"
            raise ValueError(msg)

    @property
    def qualified_name(self) -> str:
        # Segment-wise percent encoding keeps the familiar path-like display
        # while making this address injective within its symbol space. In
        # particular, ``("a/b", "c")`` cannot collide with
        # ``("a", "b", "c")``.
        return qualified_name(self.scope, self.local_id)

    def prefixed(self, *segments: str) -> SymbolId:
        if not segments:
            return self
        return SymbolId(scope=(*segments, *self.scope), local_id=self.local_id)

    @override
    def __str__(self) -> str:
        return self.qualified_name
