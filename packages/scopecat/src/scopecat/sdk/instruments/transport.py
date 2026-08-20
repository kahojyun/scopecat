"""Protocol-neutral instrument transport contracts."""

from __future__ import annotations

from typing import Protocol


class BinaryTransport(Protocol):
    """Synchronous request/response bytes owned by one driver generation."""

    def exchange(self, request: bytes, response_size: int, /) -> bytes: ...

    def close(self) -> None: ...


__all__ = ["BinaryTransport"]
