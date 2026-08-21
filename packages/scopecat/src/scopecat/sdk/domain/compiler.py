"""Compiler contract for complete, bounded domain batches."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from scopecat.sdk.domain.batch import DomainBatchRequest

if TYPE_CHECKING:
    from scopecat.sdk.domain.execution import PreparedDomainExecution


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

    def compatible_batch_size(self, request: DomainBatchRequest) -> int:
        """Return the largest compatible prefix length of one candidate batch.

        The compiler may inspect or lower every candidate point, but must not
        perform external effects. Every non-empty contiguous subrange of the
        accepted prefix must be independently compilable. Core may shorten or
        split that prefix to align host-state regions or another domain call
        before invoking ``compile_batch`` with each exact final batch.
        """
        ...

    def compile_batch(
        self,
        request: DomainBatchRequest,
    ) -> PreparedDomainExecution: ...


__all__ = [
    "DomainCompiler",
]
