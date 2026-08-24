"""Versioned, domain-separated randomness for replayable circuit families."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

_KEY_DOMAIN = b"scopecat.quantum.sequence-key.v1\0"
_STREAM_DOMAIN = b"scopecat.quantum.random-stream.v1\0"
_WORD_BITS = 256
_WORD_RANGE = 1 << _WORD_BITS


@dataclass(frozen=True, slots=True)
class SequenceKey:
    """Stable identity for one independently sampled logical circuit.

    ``length`` is present when different lengths are independent experiments and
    absent when callers deliberately request a shared random prefix.
    """

    protocol: str
    root_seed: int
    sample_index: int = 0
    members: tuple[str, ...] = ()
    length: int | None = None
    variant: str = "reference"

    def __post_init__(self) -> None:
        if not self.protocol:
            raise ValueError("sequence protocol must be non-empty")
        if self.root_seed < 0:
            raise ValueError("sequence root seed must be non-negative")
        if self.sample_index < 0:
            raise ValueError("sequence sample index must be non-negative")
        if self.length is not None and self.length < 0:
            raise ValueError("sequence length key must be non-negative")
        if any(not member for member in self.members):
            raise ValueError("sequence member ids must be non-empty")
        if not self.variant:
            raise ValueError("sequence variant must be non-empty")

    def digest(self) -> bytes:
        """Return the portable v1 key digest used by all reference samplers."""

        payload = json.dumps(
            {
                "length": self.length,
                "members": self.members,
                "protocol": self.protocol,
                "root_seed": self.root_seed,
                "sample_index": self.sample_index,
                "variant": self.variant,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        return hashlib.sha256(_KEY_DOMAIN + payload).digest()

    @property
    def derived_seed(self) -> int:
        """Expose a compact replay label without defining sampling by it."""

        return int.from_bytes(self.digest()[:16], "big")


class RandomStream:
    """Specified SHA-256 counter stream with unbiased bounded integer draws."""

    def __init__(self, key: SequenceKey) -> None:
        self._key_digest = key.digest()
        self._counter = 0

    def randbelow(self, upper_bound: int) -> int:
        """Draw uniformly from ``range(upper_bound)`` using rejection sampling."""

        if upper_bound <= 0:
            raise ValueError("random upper bound must be positive")
        acceptance_limit = _WORD_RANGE - (_WORD_RANGE % upper_bound)
        while True:
            block = hashlib.sha256(
                _STREAM_DOMAIN + self._key_digest + self._counter.to_bytes(16, "big")
            ).digest()
            self._counter += 1
            value = int.from_bytes(block, "big")
            if value < acceptance_limit:
                return value % upper_bound


__all__ = ["RandomStream", "SequenceKey"]
