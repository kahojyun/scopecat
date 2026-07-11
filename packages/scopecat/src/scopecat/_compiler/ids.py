"""Stable identities inside one transient compiler program."""

from __future__ import annotations

from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, field_validator


class NodeId(BaseModel):
    """Hygienic identity for one compute node in an expanded module tree."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scope: tuple[str, ...] = ()
    local_id: str

    @field_validator("scope")
    @classmethod
    def validate_scope(cls, scope: tuple[str, ...]) -> tuple[str, ...]:
        if any(not segment for segment in scope):
            msg = "compute node scope segments must be non-empty"
            raise ValueError(msg)
        return scope

    @field_validator("local_id")
    @classmethod
    def validate_local_id(cls, local_id: str) -> str:
        if not local_id:
            msg = "compute node local id must be non-empty"
            raise ValueError(msg)
        return local_id

    @property
    def qualified_name(self) -> str:
        # Segment-wise percent encoding keeps the familiar path-like display
        # while making the structural identity injective. In particular,
        # ``("a/b", "c")`` cannot collide with ``("a", "b", "c")``.
        return "/".join(
            quote(segment, safe="-._~[]") for segment in (*self.scope, self.local_id)
        )

    def prefixed(self, *segments: str) -> NodeId:
        if not segments:
            return self
        return NodeId(scope=(*segments, *self.scope), local_id=self.local_id)

    def __str__(self) -> str:
        return self.qualified_name

    def __hash__(self) -> int:
        return hash((self.scope, self.local_id))


__all__ = ["NodeId"]
