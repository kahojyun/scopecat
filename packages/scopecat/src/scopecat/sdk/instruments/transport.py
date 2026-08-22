"""Protocol-neutral instrument transport contracts."""

from __future__ import annotations

from typing import Protocol


class BinaryTransport(Protocol):
    """Synchronous binary I/O owned by one driver generation."""

    def send(self, request: bytes, /) -> None: ...

    def exchange(self, request: bytes, response_size: int, /) -> bytes: ...

    def close(self) -> None: ...


__all__ = ["BinaryTransport"]
