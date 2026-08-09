"""Execution results and stable identities for the list-mode target.

Every frame retains the entry, acquisition slot, and shot used for logical
result correlation.
"""

from __future__ import annotations

from dataclasses import dataclass
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
class ListModeRun:
    """Immutable result of one complete list-mode execution."""

    frames: tuple[DigitizerFrame, ...]
    artifact: ListModeArtifact
    fingerprint: str


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
    "AwgPlayback",
    "DigitizerFrame",
    "DigitizerValue",
    "ListModeRun",
    "run_fingerprint",
    "waveform_fingerprint",
]
