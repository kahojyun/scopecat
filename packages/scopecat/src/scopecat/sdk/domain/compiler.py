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
    def max_points_per_batch(self) -> int: ...

    def compile_batch(
        self,
        request: DomainBatchRequest,
    ) -> PreparedDomainExecution: ...


__all__ = [
    "DomainCompiler",
]
