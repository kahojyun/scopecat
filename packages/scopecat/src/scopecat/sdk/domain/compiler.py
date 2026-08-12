"""Compiler contract for complete, bounded domain batches."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from scopecat.sdk.domain.batch import DomainBatchRequest

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

    def initial_batch_size(self, point_count: int) -> int:
        """Choose the bounded probe compiled before continuation feedback exists."""
        ...

    def compile_batch(
        self,
        request: DomainBatchRequest,
    ) -> PreparedDomainExecution: ...


__all__ = [
    "DomainCompiler",
]
