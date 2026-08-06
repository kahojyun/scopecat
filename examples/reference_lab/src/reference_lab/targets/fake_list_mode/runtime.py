"""Deterministic runtime for the demo list-mode quantum target.

Every frame retains the entry, acquisition slot, and shot used for logical
result correlation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    TargetCompileEntryId,
)
from scopecat_quantum.targets import TargetAcquisitionAddress

from reference_lab.targets.fake_list_mode.model import (
    FakeAcquisitionWindow,
    FakeListArtifact,
    FakeListEntry,
    acquisition_slot_identity_payload,
    canonical_fingerprint,
    signal_key,
)

type FakeDigitizerValue = complex


@dataclass(frozen=True, slots=True)
class FakeAwgPlayback:
    """One physical AWG playback retaining its logical list-entry identity."""

    shot_index: int
    entry_id: TargetCompileEntryId
    waveform_fingerprint: str


class FakeAcquisitionResponse(Protocol):
    """Pluggable deterministic response model for fake acquisitions.

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
        playback: FakeAwgPlayback,
        window: FakeAcquisitionWindow,
    ) -> FakeDigitizerValue:
        """Return one response for an acquisition window and playback."""
        ...


@dataclass(frozen=True, slots=True)
class DeterministicFakeAcquisitionResponse:
    """Default address- and waveform-sensitive fake response behavior."""

    @property
    def fingerprint(self) -> str:
        return canonical_fingerprint(
            {"schema": "reference_lab.fake_acquisition_response.address_hash.v1"}
        )

    def value_for(
        self,
        *,
        playback: FakeAwgPlayback,
        window: FakeAcquisitionWindow,
    ) -> FakeDigitizerValue:
        return _capture_value(playback=playback, window=window)


@dataclass(frozen=True, slots=True)
class FakeDigitizerFrame:
    """One entry-, slot-, and shot-qualified integrated-IQ result."""

    shot_index: int
    entry_id: TargetCompileEntryId
    slot_id: AcquisitionSlotId
    value: FakeDigitizerValue

    @property
    def address(self) -> TargetAcquisitionAddress:
        """Return the entry-qualified acquisition identity of this frame."""

        return TargetAcquisitionAddress(
            entry_id=self.entry_id,
            slot_id=self.slot_id,
        )


@dataclass(frozen=True, slots=True)
class FakeListRun:
    """Immutable result of one complete fake list-mode execution."""

    frames: tuple[FakeDigitizerFrame, ...]
    artifact: FakeListArtifact
    fingerprint: str


@dataclass(frozen=True, slots=True)
class FakeListRuntime:
    """Execute an immutable fake artifact in shot-major list order."""

    response: FakeAcquisitionResponse = field(
        default_factory=DeterministicFakeAcquisitionResponse
    )

    def execute(
        self,
        artifact: FakeListArtifact,
    ) -> FakeListRun:
        playbacks: list[FakeAwgPlayback] = []
        frames: list[FakeDigitizerFrame] = []
        for shot_index in range(artifact.repetitions):
            for entry in artifact.entries:
                playback = FakeAwgPlayback(
                    shot_index=shot_index,
                    entry_id=entry.entry_id,
                    waveform_fingerprint=_waveform_fingerprint(entry),
                )
                playbacks.append(playback)
                frames.extend(
                    FakeDigitizerFrame(
                        shot_index=shot_index,
                        entry_id=entry.entry_id,
                        slot_id=window.slot_id,
                        value=self.response.value_for(
                            playback=playback,
                            window=window,
                        ),
                    )
                    for window in entry.acquisitions
                )
        selected_playbacks = tuple(playbacks)
        selected_frames = tuple(frames)
        return FakeListRun(
            frames=selected_frames,
            artifact=artifact,
            fingerprint=_run_fingerprint(
                artifact=artifact,
                playbacks=selected_playbacks,
                frames=selected_frames,
                response=self.response,
            ),
        )


def _waveform_fingerprint(entry: FakeListEntry) -> str:
    return canonical_fingerprint(
        {
            "schema": "reference_lab.fake_awg_waveforms.v1",
            "sample_count": entry.sample_count,
            "waveforms": [
                {
                    "channel_id": waveform.channel_id.value,
                    "samples": [
                        [float(sample.real).hex(), float(sample.imag).hex()]
                        for sample in waveform.samples
                    ],
                }
                for waveform in entry.waveforms
            ],
        }
    )


def _capture_value(
    *,
    playback: FakeAwgPlayback,
    window: FakeAcquisitionWindow,
) -> FakeDigitizerValue:
    address = {
        "schema": "reference_lab.fake_digitizer_address.v2",
        "shot_index": playback.shot_index,
        "waveform_fingerprint": playback.waveform_fingerprint,
        "signal": signal_key(window.signal),
        "channel_id": window.channel_id.value,
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


def _run_fingerprint(
    *,
    artifact: FakeListArtifact,
    playbacks: tuple[FakeAwgPlayback, ...],
    frames: tuple[FakeDigitizerFrame, ...],
    response: FakeAcquisitionResponse,
) -> str:
    return canonical_fingerprint(
        {
            "schema": "reference_lab.fake_list_run.v2",
            "artifact_id": artifact.id.value,
            "artifact_fingerprint": artifact.artifact_fingerprint,
            "response_fingerprint": response.fingerprint,
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


def _value_payload(value: FakeDigitizerValue) -> object:
    return [float(value.real).hex(), float(value.imag).hex()]


__all__ = [
    "DeterministicFakeAcquisitionResponse",
    "FakeAcquisitionResponse",
    "FakeAwgPlayback",
    "FakeDigitizerFrame",
    "FakeDigitizerValue",
    "FakeListRun",
    "FakeListRuntime",
]
