"""Compiler contract for complete, bounded domain batches."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from scopecat.sdk.domain.batch import (
    DomainBatchPartition,
    DomainBatchRequest,
    DomainCompileRequest,
)

if TYPE_CHECKING:
    from scopecat.sdk.domain.execution import PreparedDomainExecution


class DomainCompiler(Protocol):
    """Compile complete bounded batches for one configured domain target."""

    @property
    def target_id(self) -> str: ...

    @property
    def target_kind(self) -> str: ...

    def partition(self, request: DomainCompileRequest) -> DomainBatchPartition:
        """Choose contiguous batches whose boundaries do not change semantics."""
        ...

    def compile_batch(
        self,
        request: DomainBatchRequest,
    ) -> PreparedDomainExecution: ...


__all__ = [
    "DomainCompiler",
]
