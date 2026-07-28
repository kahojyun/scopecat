"""Project-scoped instrument backend composition."""

from __future__ import annotations

from dataclasses import dataclass, field

from scopecat.sdk.instruments.contracts import InstrumentProvider
from scopecat.sdk.payloads import PayloadCodecRegistry


@dataclass(frozen=True, slots=True)
class InstrumentBackend:
    """Keep one provider and its driver-side payload codecs process-long."""

    provider: InstrumentProvider
    payload_codecs: PayloadCodecRegistry = field(default_factory=PayloadCodecRegistry)


__all__ = ["InstrumentBackend"]
