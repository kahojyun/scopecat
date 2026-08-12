"""Compiler contract for complete, bounded domain batches."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from scopecat.sdk.domain.batch import (
    DomainBatchPartition,
    DomainBatchRequest,
)

if TYPE_CHECKING:
    from scopecat.sdk.domain.execution import PreparedDomainExecution


class DomainCompiler(Protocol):
    """Compile complete bounded batches for one configured domain target."""

    @property
    def target_id(self) -> str: ...

    @property
    def target_kind(self) -> str: ...

    @property
    def instrument_ids(self) -> tuple[str, ...]:
        """Return the physical footprint reserved before batch compilation."""
        ...

    def partition(self, point_count: int) -> DomainBatchPartition:
        """Choose contiguous batch sizes without materializing point inputs."""
        ...

    def compile_batch(
        self,
        request: DomainBatchRequest,
    ) -> PreparedDomainExecution: ...


__all__ = [
    "DomainCompiler",
]
