"""Immutable model for the demo list-mode quantum target.

Artifacts are content-addressed immutable values. Their canonical fingerprint
covers the opaque target payload and all identities needed to prevent an
artifact from being paired with another target, compiler, capability set, or
prepared entry inventory.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

from scopecat_quantum import (
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlotId,
    DriveSignal,
    FluxSignal,
    PulseEventId,
    PulseProgramId,
    QubitId,
    ReadoutSignal,
    TargetArtifactId,
    TargetCompileEntryId,
    TargetCompilerId,
    TargetId,
)


def _require_text(value: str, *, field_name: str) -> str:
    if not value.strip():
        msg = f"{field_name} must be a non-empty string"
        raise ValueError(msg)
    return value


def _require_positive_int(value: int, *, field_name: str) -> int:
    if isinstance(value, bool) or value <= 0:
        msg = f"{field_name} must be a positive integer"
        raise ValueError(msg)
    return value


def _require_positive_finite_float(value: float, *, field_name: str) -> float:
    if isinstance(value, bool):
        msg = f"{field_name} must be a positive finite number"
        raise ValueError(msg)
    try:
        selected = float(value)
    except OverflowError as error:
        msg = f"{field_name} must be a positive finite number"
        raise ValueError(msg) from error
    if not math.isfinite(selected) or selected <= 0:
        msg = f"{field_name} must be a positive finite number"
        raise ValueError(msg)
    return selected


@dataclass(frozen=True, slots=True, order=True)
class FakeAwgChannelId:
    """Physical output channel identity owned by the demo target."""

    value: str

    def __post_init__(self) -> None:
        _require_text(self.value, field_name="AWG channel id")


@dataclass(frozen=True, slots=True, order=True)
class FakeDigitizerChannelId:
    """Physical input channel identity owned by the demo target."""

    value: str

    def __post_init__(self) -> None:
        _require_text(self.value, field_name="digitizer channel id")


type FakeOutputSignal = DriveSignal | ReadoutSignal | FluxSignal


def signal_key(
    signal: FakeOutputSignal | AcquireSignal,
) -> tuple[str, str, str]:
    """Return a canonical hardware-independent key for one logical signal."""

    if isinstance(signal, DriveSignal):
        return ("drive", "qubit", signal.qubit.value)
    if isinstance(signal, ReadoutSignal):
        return ("readout", "qubit", signal.qubit.value)
    if isinstance(signal, AcquireSignal):
        return ("acquire", "qubit", signal.qubit.value)
    owner_kind = "qubit" if isinstance(signal.owner, QubitId) else "coupler"
    return ("flux", owner_kind, signal.owner.value)


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
    max_waveform_memory_samples: int
    max_capture_memory_samples: int
    max_repetitions: int
    max_frames: int
    max_abs_amplitude: float
    output_bindings: tuple[FakeOutputBinding, ...]
    acquisition_bindings: tuple[FakeAcquisitionBinding, ...]
    _capability_fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        for field_name, value in (
            ("sample_rate_hz", self.sample_rate_hz),
            ("max_list_entries", self.max_list_entries),
            ("max_samples_per_entry", self.max_samples_per_entry),
            ("max_waveform_memory_samples", self.max_waveform_memory_samples),
            ("max_capture_memory_samples", self.max_capture_memory_samples),
            ("max_repetitions", self.max_repetitions),
            ("max_frames", self.max_frames),
        ):
            _require_positive_int(value, field_name=field_name)
        amplitude = _require_positive_finite_float(
            self.max_abs_amplitude,
            field_name="max_abs_amplitude",
        )
        selected_outputs = self.output_bindings
        selected_acquisitions = self.acquisition_bindings
        if not selected_outputs and not selected_acquisitions:
            msg = "fake list targets require at least one signal binding"
            raise ValueError(msg)
        if len({binding.signal for binding in selected_outputs}) != len(
            selected_outputs
        ):
            msg = "fake output logical signals must be bound exactly once"
            raise ValueError(msg)
        if len({binding.signal for binding in selected_acquisitions}) != len(
            selected_acquisitions
        ):
            msg = "fake acquisition logical signals must be bound exactly once"
            raise ValueError(msg)
        canonical_outputs = tuple(
            sorted(
                selected_outputs,
                key=lambda binding: (*signal_key(binding.signal), binding.channel_id),
            )
        )
        canonical_acquisitions = tuple(
            sorted(
                selected_acquisitions,
                key=lambda binding: (*signal_key(binding.signal), binding.channel_id),
            )
        )
        object.__setattr__(self, "max_abs_amplitude", amplitude)
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
            "schema": "quantum_lab_demo.fake_list_target.capabilities.v1",
            "target_id": self.id.value,
            "sample_rate_hz": self.sample_rate_hz,
            "max_list_entries": self.max_list_entries,
            "max_samples_per_entry": self.max_samples_per_entry,
            "max_waveform_memory_samples": self.max_waveform_memory_samples,
            "max_capture_memory_samples": self.max_capture_memory_samples,
            "max_repetitions": self.max_repetitions,
            "max_frames": self.max_frames,
            "max_abs_amplitude": self.max_abs_amplitude.hex(),
            "supported_envelopes": list(self.supported_envelopes),
            "supported_acquisition_kinds": [kind.value for kind in AcquisitionKind],
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
    kind: AcquisitionKind

    def __post_init__(self) -> None:
        if isinstance(self.start_sample, bool) or self.start_sample < 0:
            msg = "fake acquisition start_sample must be a non-negative integer"
            raise ValueError(msg)
        _require_positive_int(self.sample_count, field_name="acquisition sample_count")


@dataclass(frozen=True, slots=True)
class FakeListEntry:
    """One compiled AWG list row and its digitizer segment plan."""

    list_index: int
    entry_id: TargetCompileEntryId
    program_id: PulseProgramId
    sample_count: int
    waveforms: tuple[FakeChannelWaveform, ...]
    acquisitions: tuple[FakeAcquisitionWindow, ...]

    def __post_init__(self) -> None:
        if isinstance(self.list_index, bool) or self.list_index < 0:
            msg = "fake list_index must be a non-negative integer"
            raise ValueError(msg)
        _require_positive_int(self.sample_count, field_name="list entry sample_count")
        selected_waveforms = self.waveforms
        selected_acquisitions = self.acquisitions
        if len({waveform.channel_id for waveform in selected_waveforms}) != len(
            selected_waveforms
        ):
            msg = "fake list waveform channels must be unique"
            raise ValueError(msg)
        if any(
            len(waveform.samples) != self.sample_count
            for waveform in selected_waveforms
        ):
            msg = "fake list waveform buffers must match the entry sample_count"
            raise ValueError(msg)
        if len({window.slot_id for window in selected_acquisitions}) != len(
            selected_acquisitions
        ):
            msg = "fake list acquisition slots must be unique"
            raise ValueError(msg)
        if len({window.event_id for window in selected_acquisitions}) != len(
            selected_acquisitions
        ):
            msg = "fake list acquisition event ids must be unique"
            raise ValueError(msg)
        if any(
            window.start_sample + window.sample_count > self.sample_count
            for window in selected_acquisitions
        ):
            msg = "fake acquisition windows must fit within the list entry"
            raise ValueError(msg)
        object.__setattr__(
            self,
            "waveforms",
            tuple(sorted(selected_waveforms, key=lambda item: item.channel_id)),
        )
        object.__setattr__(
            self,
            "acquisitions",
            tuple(
                sorted(
                    selected_acquisitions,
                    key=lambda item: (
                        item.start_sample,
                        item.channel_id,
                        item.slot_id.scope,
                        item.slot_id.local_id,
                    ),
                )
            ),
        )


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

    def __post_init__(self) -> None:
        _require_text(
            self.capability_fingerprint,
            field_name="capability_fingerprint",
        )
        _require_text(
            self.artifact_fingerprint,
            field_name="artifact_fingerprint",
        )
        _require_positive_int(self.repetitions, field_name="artifact repetitions")
        _require_positive_int(self.sample_rate_hz, field_name="artifact sample_rate_hz")
        selected_entries = self.entries
        if not selected_entries:
            msg = "fake artifacts require at least one list entry"
            raise ValueError(msg)
        if tuple(entry.list_index for entry in selected_entries) != tuple(
            range(len(selected_entries))
        ):
            msg = "fake artifact list indices must be contiguous and ordered"
            raise ValueError(msg)
        selected_source_ids = self.source_entry_ids
        if len(set(selected_source_ids)) != len(selected_source_ids):
            msg = "fake artifact source_entry_ids must be unique"
            raise ValueError(msg)
        if tuple(entry.entry_id for entry in selected_entries) != selected_source_ids:
            msg = "fake artifact entries must exactly cover source_entry_ids in order"
            raise ValueError(msg)


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
