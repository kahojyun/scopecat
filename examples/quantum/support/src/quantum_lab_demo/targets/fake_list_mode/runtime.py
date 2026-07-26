"""Deterministic runtime for the demo list-mode quantum target.

The device simulation executes artifact order, but every returned frame echoes
its target entry, shot, acquisition slot, segment, and physical channel. Those
coordinates are evidence for later correlation; their list positions never
replace logical point or product identity.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from scopecat_quantum._ids import (
    AcquisitionSlotId,
    TargetArtifactId,
    TargetCompileEntryId,
)
from scopecat_quantum.targets import TargetAcquisitionAddress

from quantum_lab_demo.targets.fake_list_mode.model import (
    FakeAcquisitionWindow,
    FakeDigitizerChannelId,
    FakeListArtifact,
    FakeListEntry,
    acquisition_slot_identity_payload,
    canonical_fingerprint,
    signal_key,
)

type FakeDigitizerValue = complex


def _require_non_negative_int(value: int, *, field_name: str) -> None:
    if isinstance(value, bool) or value < 0:
        msg = f"{field_name} must be a non-negative integer"
        raise ValueError(msg)


def _require_text(value: str, *, field_name: str) -> None:
    if not value.strip():
        msg = f"{field_name} must be a non-empty string"
        raise ValueError(msg)


def _is_finite_complex(value: complex) -> bool:
    return math.isfinite(value.real) and math.isfinite(value.imag)


@dataclass(frozen=True, slots=True)
class FakeAwgPlayback:
    """One physical AWG playback retaining its logical list-entry identity."""

    shot_index: int
    list_index: int
    entry_id: TargetCompileEntryId
    waveform_fingerprint: str

    def __post_init__(self) -> None:
        _require_non_negative_int(self.shot_index, field_name="playback shot_index")
        _require_non_negative_int(self.list_index, field_name="playback list_index")
        _require_text(
            self.waveform_fingerprint,
            field_name="playback waveform_fingerprint",
        )


@runtime_checkable
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
            {"schema": "quantum_lab_demo.fake_acquisition_response.address_hash.v1"}
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
    """One correlated segmented-digitizer result.

    ``frame_index`` is the global capture order. ``segment_index`` identifies
    the acquisition-window ordinal within the compiled list entry; it is never
    used in place of the entry, shot, or acquisition-slot identities.
    """

    frame_index: int
    segment_index: int
    shot_index: int
    list_index: int
    entry_id: TargetCompileEntryId
    slot_id: AcquisitionSlotId
    channel_id: FakeDigitizerChannelId
    value: FakeDigitizerValue

    def __post_init__(self) -> None:
        for field_name, value in (
            ("frame_index", self.frame_index),
            ("segment_index", self.segment_index),
            ("shot_index", self.shot_index),
            ("list_index", self.list_index),
        ):
            _require_non_negative_int(
                value,
                field_name=f"digitizer {field_name}",
            )

        if not isinstance(self.value, complex) or not _is_finite_complex(self.value):
            msg = "integrated-IQ frames require one finite complex value"
            raise TypeError(msg)

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

    playbacks: tuple[FakeAwgPlayback, ...]
    frames: tuple[FakeDigitizerFrame, ...]
    artifact: FakeListArtifact
    fingerprint: str
    response: FakeAcquisitionResponse = field(
        default_factory=DeterministicFakeAcquisitionResponse
    )

    @property
    def artifact_id(self) -> TargetArtifactId:
        return self.artifact.id


@dataclass(frozen=True, slots=True)
class FakeListAwg:
    """Stateless fake AWG that loops the complete list for every shot."""

    def play(self, artifact: FakeListArtifact) -> tuple[FakeAwgPlayback, ...]:
        return tuple(
            FakeAwgPlayback(
                shot_index=shot_index,
                list_index=entry.list_index,
                entry_id=entry.entry_id,
                waveform_fingerprint=_waveform_fingerprint(entry),
            )
            for shot_index in range(artifact.repetitions)
            for entry in artifact.entries
        )


@dataclass(frozen=True, slots=True)
class FakeSegmentedDigitizer:
    """Stateless fake digitizer driven by explicit playback correlation."""

    response: FakeAcquisitionResponse = field(
        default_factory=DeterministicFakeAcquisitionResponse
    )

    def __post_init__(self) -> None:
        _validated_response(self.response)

    def capture(
        self,
        artifact: FakeListArtifact,
        playbacks: tuple[FakeAwgPlayback, ...],
    ) -> tuple[FakeDigitizerFrame, ...]:
        resolved = _resolve_playbacks(artifact, playbacks)
        frames: list[FakeDigitizerFrame] = []
        for playback, entry in resolved:
            for segment_index, window in enumerate(entry.acquisitions):
                frames.append(
                    FakeDigitizerFrame(
                        frame_index=len(frames),
                        segment_index=segment_index,
                        shot_index=playback.shot_index,
                        list_index=playback.list_index,
                        entry_id=playback.entry_id,
                        slot_id=window.slot_id,
                        channel_id=window.channel_id,
                        value=self.response.value_for(
                            playback=playback,
                            window=window,
                        ),
                    )
                )
        return tuple(frames)


@dataclass(frozen=True, slots=True)
class FakeListRuntime:
    """Execute one verified fake list artifact without provider side effects."""

    awg: FakeListAwg = field(default_factory=FakeListAwg)
    digitizer: FakeSegmentedDigitizer = field(default_factory=FakeSegmentedDigitizer)

    def execute(
        self,
        artifact: FakeListArtifact,
    ) -> FakeListRun:
        playbacks = self.awg.play(artifact)
        frames = self.digitizer.capture(artifact, playbacks)
        return FakeListRun(
            playbacks=playbacks,
            frames=frames,
            artifact=artifact,
            response=self.digitizer.response,
            fingerprint=_run_fingerprint(
                artifact=artifact,
                playbacks=playbacks,
                frames=frames,
                response=self.digitizer.response,
            ),
        )


def _waveform_fingerprint(entry: FakeListEntry) -> str:
    return canonical_fingerprint(
        {
            "schema": "quantum_lab_demo.fake_awg_waveforms.v1",
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


def _resolve_playbacks(
    artifact: FakeListArtifact,
    playbacks: tuple[FakeAwgPlayback, ...],
) -> tuple[tuple[FakeAwgPlayback, FakeListEntry], ...]:
    entries_by_identity = {
        (entry.list_index, entry.entry_id): entry for entry in artifact.entries
    }
    expected_addresses = tuple(
        (shot_index, entry.list_index, entry.entry_id)
        for shot_index in range(artifact.repetitions)
        for entry in artifact.entries
    )
    expected_address_set = set(expected_addresses)
    actual_addresses: set[tuple[int, int, TargetCompileEntryId]] = set()
    actual_address_order: list[tuple[int, int, TargetCompileEntryId]] = []
    resolved: list[tuple[FakeAwgPlayback, FakeListEntry]] = []
    for playback in playbacks:
        entry = entries_by_identity.get((playback.list_index, playback.entry_id))
        if entry is None:
            msg = (
                "fake AWG playback references no artifact entry: "
                f"list={playback.list_index}, entry={playback.entry_id.value!r}"
            )
            raise ValueError(msg)
        address = (playback.shot_index, playback.list_index, playback.entry_id)
        if address not in expected_address_set:
            msg = "fake AWG playback shot is outside artifact repetitions"
            raise ValueError(msg)
        if address in actual_addresses:
            msg = "fake AWG playback coverage contains a duplicate address"
            raise ValueError(msg)
        if playback.waveform_fingerprint != _waveform_fingerprint(entry):
            msg = "fake AWG playback waveform does not match its artifact entry"
            raise ValueError(msg)
        actual_addresses.add(address)
        actual_address_order.append(address)
        resolved.append((playback, entry))

    if tuple(actual_address_order) != expected_addresses:
        msg = (
            "fake AWG playbacks must exactly cover the artifact in shot-major "
            "list order"
        )
        raise ValueError(msg)
    return tuple(resolved)


def _capture_value(
    *,
    playback: FakeAwgPlayback,
    window: FakeAcquisitionWindow,
) -> FakeDigitizerValue:
    address = {
        "schema": "quantum_lab_demo.fake_digitizer_address.v2",
        "shot_index": playback.shot_index,
        "waveform_fingerprint": playback.waveform_fingerprint,
        "signal": signal_key(window.signal),
        "channel_id": window.channel_id.value,
        "start_sample": window.start_sample,
        "sample_count": window.sample_count,
    }
    return _deterministic_complex(address=address)


def _validated_response(response: object) -> FakeAcquisitionResponse:
    if not isinstance(response, FakeAcquisitionResponse):
        msg = "fake digitizer response must implement FakeAcquisitionResponse"
        raise TypeError(msg)
    _require_text(response.fingerprint, field_name="acquisition response fingerprint")
    return response


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
            "schema": "quantum_lab_demo.fake_list_run.v2",
            "artifact_id": artifact.id.value,
            "artifact_fingerprint": artifact.artifact_fingerprint,
            "response_fingerprint": response.fingerprint,
            "playbacks": [
                {
                    "shot_index": playback.shot_index,
                    "list_index": playback.list_index,
                    "entry_id": playback.entry_id.value,
                    "waveform_fingerprint": playback.waveform_fingerprint,
                }
                for playback in playbacks
            ],
            "frames": [
                {
                    "frame_index": frame.frame_index,
                    "segment_index": frame.segment_index,
                    "shot_index": frame.shot_index,
                    "list_index": frame.list_index,
                    "entry_id": frame.entry_id.value,
                    "slot_id": acquisition_slot_identity_payload(frame.slot_id),
                    "channel_id": frame.channel_id.value,
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
    "FakeListAwg",
    "FakeListRun",
    "FakeListRuntime",
    "FakeSegmentedDigitizer",
]
