"""Internal instrument state used only while preflighting a command batch."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.records.instrument import InstrumentStateObservation


@dataclass(frozen=True, slots=True)
class ProjectedInstrumentState:
    """Trusted partial physical state that is not a hardware observation."""

    instrument_id: str
    observations: tuple[InstrumentStateObservation, ...] = ()


__all__ = ["ProjectedInstrumentState"]
