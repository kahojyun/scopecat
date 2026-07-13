"""Resource lease policies supplied by the execution layer."""

from contextlib import AbstractContextManager, nullcontext

from scopecat.execution.ports.resources import ResourceClaim


class NoopResourceLeaseManager:
    """Lease policy for interpreters whose caller already owns resources."""

    def acquire(
        self, claims: tuple[ResourceClaim, ...]
    ) -> AbstractContextManager[None]:
        del claims
        return nullcontext()


__all__ = ["NoopResourceLeaseManager"]
