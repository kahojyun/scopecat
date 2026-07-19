"""Whole-run resource leasing port."""

from contextlib import AbstractContextManager
from typing import Protocol

from scopecat.kernel.resource_identity import ResourceClaim


class ResourceLeaseManager(Protocol):
    """Acquire all claims before any driver interaction begins."""

    def acquire(
        self, claims: tuple[ResourceClaim, ...]
    ) -> AbstractContextManager[None]: ...
