"""Shared identities for independently executable benchmark cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

type BenchmarkKind = Literal["e2e", "component", "micro"]


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One stable benchmark entrypoint and its measurement boundary."""

    id: str
    kind: BenchmarkKind
    module: str
    summary: str


__all__ = ["BenchmarkCase", "BenchmarkKind"]
