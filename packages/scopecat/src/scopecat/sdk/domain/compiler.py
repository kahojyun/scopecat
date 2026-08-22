"""Compiler contract for complete, bounded domain batches."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from scopecat.sdk.domain.batch import DomainBatchRequest
from scopecat.sdk.domain.execution import PreparedDomainExecution


@dataclass(frozen=True, slots=True)
class DomainBatchCandidate:
    """Reusable analysis of one candidate point prefix.

    Core may shorten or split the compatible prefix around host-state regions
    before closing exact executions. The compiler-owned closure retains any
    lowering or packing work shared by those final subranges.
    """

    compatible_point_count: int
    _compile: Callable[[DomainBatchRequest], PreparedDomainExecution] = field(
        repr=False,
        compare=False,
    )

    def compile(self, request: DomainBatchRequest) -> PreparedDomainExecution:
        """Close one exact contiguous subrange of the compatible prefix."""

        return self._compile(request)


class DomainCompiler(Protocol):
    """Negotiate and compile bounded batches for one configured domain target."""

    @property
    def target_id(self) -> str: ...

    @property
    def target_kind(self) -> str: ...

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        """Return the physical footprint reserved before batch compilation."""
        ...

    def initial_batch_max_points(self, point_count: int) -> int:
        """Bound the first candidate without resolving its point-local inputs."""
        ...

    def prepare_batch(self, request: DomainBatchRequest) -> DomainBatchCandidate:
        """Analyze a candidate and retain work needed to close its executions.

        The compiler may inspect or lower every candidate point, but must not
        perform external effects. Every non-empty contiguous subrange of the
        accepted prefix must be independently compilable. Core may shorten or
        split that prefix to align host-state regions or another domain call
        before asking the returned candidate to compile each exact final batch.
        """
        ...


__all__ = [
    "DomainBatchCandidate",
    "DomainCompiler",
]
