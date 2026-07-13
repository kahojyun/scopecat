"""In-memory whole-run resource leases."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Generator
from contextlib import contextmanager
from threading import Lock, RLock

from scopecat.execution.ports.resources import ResourceClaim


class MemoryResourceLeaseManager:
    """Serialize overlapping claims with the same canonical lock order."""

    def __init__(self) -> None:
        self._locks: defaultdict[ResourceClaim, RLock] = defaultdict(RLock)
        self._manager_lock = Lock()

    @contextmanager
    def acquire(self, claims: tuple[ResourceClaim, ...]) -> Generator[None]:
        ordered_claims = sorted(set(claims), key=lambda claim: (claim.kind, claim.id))
        with self._manager_lock:
            locks = tuple(self._locks[claim] for claim in ordered_claims)
        for lock in locks:
            lock.acquire()
        try:
            yield
        finally:
            for lock in reversed(locks):
                lock.release()


__all__ = ["MemoryResourceLeaseManager"]
