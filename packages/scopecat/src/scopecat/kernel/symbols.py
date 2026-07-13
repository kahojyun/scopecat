"""Structural identities inside one transient Scopecat program."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, field_validator

from scopecat.kernel.qualified_name import qualified_name


class SymbolId(BaseModel):
    """Hygienic address for a declaration in one typed symbol space."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: tuple[str, ...] = ()
    local_id: str

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, scope: tuple[str, ...]) -> tuple[str, ...]:
        if any(not segment for segment in scope):
            msg = "symbol scope segments must be non-empty"
            raise ValueError(msg)
        return scope

    @field_validator("local_id")
    @classmethod
    def validate_local_id(cls, local_id: str) -> str:
        if not local_id:
            msg = "symbol local id must be non-empty"
            raise ValueError(msg)
        return local_id

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

    def __str__(self) -> str:
        return self.qualified_name

    def __hash__(self) -> int:
        return hash((self.scope, self.local_id))


__all__ = ["SymbolId"]
