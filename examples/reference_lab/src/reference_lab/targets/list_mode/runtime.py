"""Deterministic runtime for the demo list-mode quantum target.

Every frame retains the entry, acquisition slot, and shot used for logical
result correlation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    TargetCompileEntryId,
)
from scopecat_quantum.targets import TargetAcquisitionAddress

from reference_lab.targets.list_mode.model import (
    DigitizerAcquisitionWindow,
    ListModeArtifact,
    ListModeEntry,
    acquisition_slot_identity_payload,
    canonical_fingerprint,
    signal_key,
)

type DigitizerValue = complex | None


@dataclass(frozen=True, slots=True)
class AwgPlayback:
    """One physical AWG playback retaining its logical list-entry identity."""

    shot_index: int
    entry_id: TargetCompileEntryId
    waveform_fingerprint: str


class AcquisitionResponse(Protocol):
    """Pluggable deterministic response model for virtual acquisitions.

    The fingerprint is part of every run identity and must change whenever
    response behavior or configuration changes.
    """

    @property
    def fingerprint(self) -> str:
        """Return the stable identity of this response behavior."""
        ...

    def value_for(
        self,
        *,
        playback: AwgPlayback,
        window: DigitizerAcquisitionWindow,
    ) -> DigitizerValue:
        """Return one response for an acquisition window and playback."""
        ...


class AwgDevice(Protocol):
    """Device boundary that accepts one compiled AWG list entry."""

    def play(self, *, shot_index: int, entry: ListModeEntry) -> AwgPlayback:
        """Play one entry and return addressable playback evidence."""
        ...


class DigitizerDevice(Protocol):
    """Device boundary that accepts compiled segmented-acquisition windows."""

    @property
    def response_fingerprint(self) -> str:
        """Return the stable identity of the configured response behavior."""
        ...

    def capture(
        self,
        *,
        playback: AwgPlayback,
        windows: Sequence[DigitizerAcquisitionWindow],
    ) -> tuple[DigitizerFrame, ...]:
        """Capture every armed window for one physical playback."""
        ...


@dataclass(frozen=True, slots=True)
class DeterministicAcquisitionResponse:
    """Default address- and waveform-sensitive virtual response behavior."""

    @property
    def fingerprint(self) -> str:
        return canonical_fingerprint(
            {"schema": "reference_lab.virtual_acquisition_response.address_hash.v1"}
        )

    def value_for(
        self,
        *,
        playback: AwgPlayback,
        window: DigitizerAcquisitionWindow,
    ) -> DigitizerValue:
        return _capture_value(playback=playback, window=window)


@dataclass(frozen=True, slots=True)
class DigitizerFrame:
    """One entry-, slot-, and shot-qualified integrated-IQ result."""

    shot_index: int
    entry_id: TargetCompileEntryId
    slot_id: AcquisitionSlotId
    value: DigitizerValue

    @property
    def address(self) -> TargetAcquisitionAddress:
        """Return the entry-qualified acquisition identity of this frame."""

        return TargetAcquisitionAddress(
            entry_id=self.entry_id,
            slot_id=self.slot_id,
        )


@dataclass(frozen=True, slots=True)
class VirtualAwgDevice:
    """Deterministic virtual AWG consuming real per-channel buffers."""

    def play(self, *, shot_index: int, entry: ListModeEntry) -> AwgPlayback:
        return AwgPlayback(
            shot_index=shot_index,
            entry_id=entry.entry_id,
            waveform_fingerprint=waveform_fingerprint(entry),
        )


@dataclass(frozen=True, slots=True)
class VirtualDigitizerDevice:
    """Deterministic virtual digitizer consuming physical capture windows."""

    response: AcquisitionResponse = field(
        default_factory=DeterministicAcquisitionResponse
    )

    @property
    def response_fingerprint(self) -> str:
        return self.response.fingerprint

    def capture(
        self,
        *,
        playback: AwgPlayback,
        windows: Sequence[DigitizerAcquisitionWindow],
    ) -> tuple[DigitizerFrame, ...]:
        return tuple(
            DigitizerFrame(
                shot_index=playback.shot_index,
                entry_id=playback.entry_id,
                slot_id=window.slot_id,
                value=self.response.value_for(
                    playback=playback,
                    window=window,
                ),
            )
            for window in windows
        )


@dataclass(frozen=True, slots=True)
class ListModeRun:
    """Immutable result of one complete list-mode execution."""

    frames: tuple[DigitizerFrame, ...]
    artifact: ListModeArtifact
    fingerprint: str


@dataclass(frozen=True, slots=True)
class VirtualListModeRuntime:
    """Simulate an immutable device artifact in shot-major list order."""

    awg: AwgDevice = field(default_factory=VirtualAwgDevice)
    digitizer: DigitizerDevice = field(default_factory=VirtualDigitizerDevice)

    def execute(
        self,
        artifact: ListModeArtifact,
    ) -> ListModeRun:
        playbacks: list[AwgPlayback] = []
        frames: list[DigitizerFrame] = []
        for shot_index in range(artifact.repetitions):
            for entry in artifact.entries:
                playback = self.awg.play(
                    shot_index=shot_index,
                    entry=entry,
                )
                playbacks.append(playback)
                frames.extend(
                    self.digitizer.capture(
                        playback=playback,
                        windows=entry.acquisitions,
                    )
                )
        selected_playbacks = tuple(playbacks)
        selected_frames = tuple(frames)
        return ListModeRun(
            frames=selected_frames,
            artifact=artifact,
            fingerprint=run_fingerprint(
                artifact=artifact,
                playbacks=selected_playbacks,
                frames=selected_frames,
                response_fingerprint=self.digitizer.response_fingerprint,
            ),
        )


def waveform_fingerprint(entry: ListModeEntry) -> str:
    return canonical_fingerprint(
        {
            "schema": "reference_lab.virtual_awg_waveforms.v1",
            "sample_count": entry.sample_count,
            "waveforms": [
                {
                    "channel_id": waveform.channel_id.value,
                    "instrument_id": waveform.channel_id.instrument_id,
                    "component_path": list(waveform.channel_id.component_path),
                    "samples": [float(sample).hex() for sample in waveform.samples],
                }
                for waveform in entry.waveforms
            ],
        }
    )


def _capture_value(
    *,
    playback: AwgPlayback,
    window: DigitizerAcquisitionWindow,
) -> DigitizerValue:
    address = {
        "schema": "reference_lab.virtual_digitizer_address.v3",
        "shot_index": playback.shot_index,
        "waveform_fingerprint": playback.waveform_fingerprint,
        "signal": signal_key(window.signal),
        "input_id": window.input_id.value,
        "instrument_id": window.input_id.instrument_id,
        "component_path": list(window.input_id.component_path),
        "demodulator_slot_id": window.demodulator_slot_id.value,
        "intent": {
            "output_representation": window.intent.output_representation,
            "demodulation_frequency_hz": float(
                window.intent.demodulation_frequency_hz
            ).hex(),
            "integration_weight": window.intent.integration_weight,
            "normalization": window.intent.normalization,
        },
        "start_sample": window.start_sample,
        "sample_count": window.sample_count,
    }
    return _deterministic_complex(address=address)


def _deterministic_complex(
    *,
    address: Mapping[str, object],
) -> complex:
    encoded = json.dumps(
        address,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    digest = hashlib.sha256(encoded).digest()
    denominator = float((1 << 64) - 1)
    real = 2.0 * int.from_bytes(digest[:8], "big") / denominator - 1.0
    imag = 2.0 * int.from_bytes(digest[8:16], "big") / denominator - 1.0
    return complex(real, imag)


def run_fingerprint(
    *,
    artifact: ListModeArtifact,
    playbacks: tuple[AwgPlayback, ...],
    frames: tuple[DigitizerFrame, ...],
    response_fingerprint: str,
) -> str:
    return canonical_fingerprint(
        {
            "schema": "reference_lab.virtual_list_mode_run.v2",
            "artifact_id": artifact.id.value,
            "artifact_fingerprint": artifact.artifact_fingerprint,
            "response_fingerprint": response_fingerprint,
            "playbacks": [
                {
                    "shot_index": playback.shot_index,
                    "entry_id": playback.entry_id.value,
                    "waveform_fingerprint": playback.waveform_fingerprint,
                }
                for playback in playbacks
            ],
            "frames": [
                {
                    "shot_index": frame.shot_index,
                    "entry_id": frame.entry_id.value,
                    "slot_id": acquisition_slot_identity_payload(frame.slot_id),
                    "value": _value_payload(frame.value),
                }
                for frame in frames
            ],
        }
    )


def _value_payload(value: DigitizerValue) -> object:
    if value is None:
        return None
    return [float(value.real).hex(), float(value.imag).hex()]


__all__ = [
    "AcquisitionResponse",
    "AwgDevice",
    "AwgPlayback",
    "DeterministicAcquisitionResponse",
    "DigitizerDevice",
    "DigitizerFrame",
    "DigitizerValue",
    "ListModeRun",
    "VirtualAwgDevice",
    "VirtualDigitizerDevice",
    "VirtualListModeRuntime",
]
