"""Whole-run resource leasing port."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True, slots=True)
class ResourceClaim:
    """Run-level exclusive claim acquired before external effects."""

    id: str
    kind: Literal["target", "instrument", "channel", "group"] = "instrument"

    def __post_init__(self) -> None:
        if not self.id:
            msg = "resource claim id must be non-empty"
            raise ValueError(msg)


class ResourceLeaseManager(Protocol):
    """Acquire all claims before any driver interaction begins."""

    def acquire(
        self, claims: tuple[ResourceClaim, ...]
    ) -> AbstractContextManager[None]: ...
