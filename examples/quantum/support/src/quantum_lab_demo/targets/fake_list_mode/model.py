"""Immutable model for the demo list-mode quantum target.

Artifacts are content-addressed immutable values. Their canonical fingerprint
covers the opaque target payload and all identities needed to prevent an
artifact from being paired with another target, compiler, capability set, or
prepared entry inventory.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    PulseEventId,
    PulseProgramId,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)
from scopecat_quantum.pulses import (
    AcquireSignal,
    DriveSignal,
    ReadoutSignal,
)


@dataclass(frozen=True, slots=True, order=True)
class FakeAwgChannelId:
    """Physical output channel identity owned by the demo target."""

    value: str


@dataclass(frozen=True, slots=True, order=True)
class FakeDigitizerChannelId:
    """Physical input channel identity owned by the demo target."""

    value: str


type FakeOutputSignal = DriveSignal | ReadoutSignal


def signal_key(
    signal: FakeOutputSignal | AcquireSignal,
) -> tuple[str, str, str]:
    """Return a canonical hardware-independent key for one logical signal."""

    if isinstance(signal, DriveSignal):
        return ("drive", "qubit", signal.qubit.value)
    if isinstance(signal, ReadoutSignal):
        return ("readout", "qubit", signal.qubit.value)
    return ("acquire", "qubit", signal.qubit.value)


@dataclass(frozen=True, slots=True)
class FakeOutputBinding:
    """Bind one logical pulse-output signal to a fake AWG channel."""

    signal: FakeOutputSignal
    channel_id: FakeAwgChannelId


@dataclass(frozen=True, slots=True)
class FakeAcquisitionBinding:
    """Bind one logical acquisition signal to a fake digitizer channel."""

    signal: AcquireSignal
    channel_id: FakeDigitizerChannelId


def canonical_fingerprint(payload: object) -> str:
    """Hash canonical JSON data with a stable schema-independent envelope."""

    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def pulse_event_identity_payload(event_id: PulseEventId) -> dict[str, object]:
    """Project structural event identity without coupling hashes to its display."""

    return {
        "scope": list(event_id.scope),
        "local_id": event_id.local_id,
    }


def acquisition_slot_identity_payload(
    slot_id: AcquisitionSlotId,
) -> dict[str, object]:
    """Project structural result identity without coupling hashes to display."""

    return {
        "scope": list(slot_id.scope),
        "local_id": slot_id.local_id,
    }


@dataclass(frozen=True, slots=True)
class FakeListTarget:
    """Capabilities and physical signal bindings of the demo target."""

    id: TargetId
    sample_rate_hz: int
    max_list_entries: int
    max_samples_per_entry: int
    max_repetitions: int
    max_abs_amplitude: float
    output_bindings: tuple[FakeOutputBinding, ...]
    acquisition_bindings: tuple[FakeAcquisitionBinding, ...]
    _capability_fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        canonical_outputs = tuple(
            sorted(
                self.output_bindings,
                key=lambda binding: (*signal_key(binding.signal), binding.channel_id),
            )
        )
        canonical_acquisitions = tuple(
            sorted(
                self.acquisition_bindings,
                key=lambda binding: (*signal_key(binding.signal), binding.channel_id),
            )
        )
        object.__setattr__(self, "output_bindings", canonical_outputs)
        object.__setattr__(self, "acquisition_bindings", canonical_acquisitions)
        object.__setattr__(
            self,
            "_capability_fingerprint",
            canonical_fingerprint(self._capability_payload()),
        )

    @property
    def capability_fingerprint(self) -> str:
        return self._capability_fingerprint

    @property
    def supported_envelopes(self) -> tuple[str, ...]:
        """Return the analytic envelope kinds compiled by this target."""

        return ("constant", "drag")

    def output_channel(self, signal: FakeOutputSignal) -> FakeAwgChannelId | None:
        for binding in self.output_bindings:
            if binding.signal == signal:
                return binding.channel_id
        return None

    def acquisition_channel(
        self, signal: AcquireSignal
    ) -> FakeDigitizerChannelId | None:
        for binding in self.acquisition_bindings:
            if binding.signal == signal:
                return binding.channel_id
        return None

    def _capability_payload(self) -> dict[str, object]:
        return {
            "schema": "quantum_lab_demo.fake_list_target.capabilities.v2",
            "target_id": self.id.value,
            "sample_rate_hz": self.sample_rate_hz,
            "max_list_entries": self.max_list_entries,
            "max_samples_per_entry": self.max_samples_per_entry,
            "max_repetitions": self.max_repetitions,
            "max_abs_amplitude": float(self.max_abs_amplitude).hex(),
            "supported_envelopes": list(self.supported_envelopes),
            "output_bindings": [
                {
                    "signal": signal_key(binding.signal),
                    "channel_id": binding.channel_id.value,
                }
                for binding in self.output_bindings
            ],
            "acquisition_bindings": [
                {
                    "signal": signal_key(binding.signal),
                    "channel_id": binding.channel_id.value,
                }
                for binding in self.acquisition_bindings
            ],
        }


@dataclass(frozen=True, slots=True)
class FakeChannelWaveform:
    """One immutable, zero-padded AWG channel buffer."""

    channel_id: FakeAwgChannelId
    samples: tuple[complex, ...]


@dataclass(frozen=True, slots=True)
class FakeAcquisitionWindow:
    """One physical segmented-digitizer window in a list entry."""

    event_id: PulseEventId
    slot_id: AcquisitionSlotId
    signal: AcquireSignal
    channel_id: FakeDigitizerChannelId
    start_sample: int
    sample_count: int


@dataclass(frozen=True, slots=True)
class FakeListEntry:
    """One compiled AWG list row and its digitizer segment plan."""

    list_index: int
    entry_id: TargetCompileEntryId
    program_id: PulseProgramId
    sample_count: int
    waveforms: tuple[FakeChannelWaveform, ...]
    acquisitions: tuple[FakeAcquisitionWindow, ...]


@dataclass(frozen=True, slots=True)
class FakeListArtifact:
    """Deeply immutable target artifact for fake list playback."""

    id: TargetArtifactId
    target_id: TargetId
    compiler_id: TargetCompilerId
    capability_fingerprint: str
    artifact_fingerprint: str
    source_entry_ids: tuple[TargetCompileEntryId, ...]
    repetitions: int
    sample_rate_hz: int
    entries: tuple[FakeListEntry, ...]


__all__ = [
    "FakeAcquisitionBinding",
    "FakeAcquisitionWindow",
    "FakeAwgChannelId",
    "FakeChannelWaveform",
    "FakeDigitizerChannelId",
    "FakeListArtifact",
    "FakeListEntry",
    "FakeListTarget",
    "FakeOutputBinding",
    "FakeOutputSignal",
]
