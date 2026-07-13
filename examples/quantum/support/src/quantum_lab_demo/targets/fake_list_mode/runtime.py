"""Deterministic runtime for the demo list-mode quantum target."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import cast

from scopecat_quantum import (
    AcquisitionKind,
    AcquisitionSlotId,
    CompiledTargetArtifact,
    TargetAcquisitionAddress,
    TargetArtifactId,
    TargetCompileEntryId,
)

from quantum_lab_demo.targets.fake_list_mode.model import (
    FakeAcquisitionWindow,
    FakeDigitizerChannelId,
    FakeListArtifact,
    FakeListEntry,
    acquisition_slot_identity_payload,
    canonical_fingerprint,
    pulse_event_identity_payload,
    signal_key,
)

type FakeDigitizerValue = complex | tuple[complex, ...]


def _require_non_negative_int(value: object, *, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        msg = f"{field_name} must be a non-negative integer"
        raise ValueError(msg)


def _require_text(value: object, *, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
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
        _require_non_negative_int(
            cast("object", self.shot_index), field_name="playback shot_index"
        )
        _require_non_negative_int(
            cast("object", self.list_index), field_name="playback list_index"
        )
        if not isinstance(cast("object", self.entry_id), TargetCompileEntryId):
            msg = "fake AWG playback entry_id must be a TargetCompileEntryId"
            raise TypeError(msg)
        _require_text(
            cast("object", self.waveform_fingerprint),
            field_name="playback waveform_fingerprint",
        )


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
    kind: AcquisitionKind
    value: FakeDigitizerValue

    def __post_init__(self) -> None:
        for field_name in (
            "frame_index",
            "segment_index",
            "shot_index",
            "list_index",
        ):
            _require_non_negative_int(
                cast("object", getattr(self, field_name)),
                field_name=f"digitizer {field_name}",
            )
        if not isinstance(cast("object", self.entry_id), TargetCompileEntryId):
            msg = "fake digitizer frame entry_id must be a TargetCompileEntryId"
            raise TypeError(msg)
        if not isinstance(cast("object", self.slot_id), AcquisitionSlotId):
            msg = "fake digitizer frame slot_id must be an AcquisitionSlotId"
            raise TypeError(msg)
        if not isinstance(cast("object", self.channel_id), FakeDigitizerChannelId):
            msg = "fake digitizer frame channel_id must be a FakeDigitizerChannelId"
            raise TypeError(msg)
        if not isinstance(cast("object", self.kind), AcquisitionKind):
            msg = "fake digitizer frame kind must be an AcquisitionKind"
            raise TypeError(msg)

        value = cast("object", self.value)
        if self.kind is AcquisitionKind.INTEGRATED_IQ:
            if not isinstance(value, complex) or not _is_finite_complex(value):
                msg = "integrated-IQ frames require one finite complex value"
                raise TypeError(msg)
            return
        if self.kind is AcquisitionKind.RAW_TRACE:
            if (
                not isinstance(value, tuple)
                or not value
                or not all(
                    isinstance(sample, complex) and _is_finite_complex(sample)
                    for sample in cast("tuple[object, ...]", value)
                )
            ):
                msg = "raw-trace frames require a non-empty tuple of complex samples"
                raise TypeError(msg)
            return
        msg = f"unsupported acquisition kind: {self.kind!r}"
        raise ValueError(msg)

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

    def __post_init__(self) -> None:
        playbacks = cast("object", self.playbacks)
        if not isinstance(playbacks, tuple) or not all(
            isinstance(playback, FakeAwgPlayback)
            for playback in cast("tuple[object, ...]", playbacks)
        ):
            msg = "fake list run playbacks must be FakeAwgPlayback values"
            raise TypeError(msg)
        if not playbacks:
            msg = "fake list runs require at least one AWG playback"
            raise ValueError(msg)

        frames = cast("object", self.frames)
        if not isinstance(frames, tuple) or not all(
            isinstance(frame, FakeDigitizerFrame)
            for frame in cast("tuple[object, ...]", frames)
        ):
            msg = "fake list run frames must be FakeDigitizerFrame values"
            raise TypeError(msg)
        selected_playbacks = cast("tuple[FakeAwgPlayback, ...]", playbacks)
        selected_frames = cast("tuple[FakeDigitizerFrame, ...]", frames)
        if tuple(frame.frame_index for frame in selected_frames) != tuple(
            range(len(selected_frames))
        ):
            msg = "fake digitizer frame indices must be contiguous and ordered"
            raise ValueError(msg)

        playback_addresses = {
            (playback.shot_index, playback.list_index, playback.entry_id)
            for playback in selected_playbacks
        }
        if len(playback_addresses) != len(selected_playbacks):
            msg = "fake list run playback addresses must be unique"
            raise ValueError(msg)
        if any(
            (frame.shot_index, frame.list_index, frame.entry_id)
            not in playback_addresses
            for frame in selected_frames
        ):
            msg = "fake digitizer frames must reference a run playback"
            raise ValueError(msg)
        frame_addresses = {
            (
                frame.shot_index,
                frame.list_index,
                frame.entry_id,
                frame.segment_index,
                frame.slot_id,
            )
            for frame in selected_frames
        }
        if len(frame_addresses) != len(selected_frames):
            msg = "fake digitizer frame addresses must be unique"
            raise ValueError(msg)

        if not isinstance(cast("object", self.artifact), FakeListArtifact):
            msg = "fake list run artifact must be a FakeListArtifact"
            raise TypeError(msg)
        _validate_artifact(self.artifact)
        resolved = _resolve_playbacks(self.artifact, selected_playbacks)
        _validate_frame_coverage(
            resolved=resolved,
            frames=selected_frames,
        )
        _require_text(cast("object", self.fingerprint), field_name="run fingerprint")
        expected_fingerprint = _run_fingerprint(
            artifact=self.artifact,
            playbacks=selected_playbacks,
            frames=selected_frames,
        )
        if self.fingerprint != expected_fingerprint:
            msg = "fake list run fingerprint does not cover its artifact and frames"
            raise ValueError(msg)

    @property
    def artifact_id(self) -> TargetArtifactId:
        return self.artifact.id


@dataclass(frozen=True, slots=True)
class FakeListAwg:
    """Stateless fake AWG that loops the complete list for every shot."""

    def play(self, artifact: FakeListArtifact) -> tuple[FakeAwgPlayback, ...]:
        _validate_artifact(artifact)
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

    def capture(
        self,
        artifact: FakeListArtifact,
        playbacks: tuple[FakeAwgPlayback, ...],
    ) -> tuple[FakeDigitizerFrame, ...]:
        _validate_artifact(artifact)
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
                        kind=window.kind,
                        value=_capture_value(
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

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.awg), FakeListAwg):
            msg = "fake list runtime requires a FakeListAwg"
            raise TypeError(msg)
        if not isinstance(cast("object", self.digitizer), FakeSegmentedDigitizer):
            msg = "fake list runtime requires a FakeSegmentedDigitizer"
            raise TypeError(msg)

    def execute(
        self,
        compiled: CompiledTargetArtifact[FakeListArtifact],
    ) -> FakeListRun:
        artifact = _verified_fake_artifact(compiled)
        playbacks = self.awg.play(artifact)
        frames = self.digitizer.capture(artifact, playbacks)
        return FakeListRun(
            playbacks=playbacks,
            frames=frames,
            artifact=artifact,
            fingerprint=_run_fingerprint(
                artifact=artifact,
                playbacks=playbacks,
                frames=frames,
            ),
        )


def _verified_fake_artifact(
    compiled: CompiledTargetArtifact[FakeListArtifact],
) -> FakeListArtifact:
    if not isinstance(cast("object", compiled), CompiledTargetArtifact):
        msg = "fake list runtime requires a CompiledTargetArtifact"
        raise TypeError(msg)
    artifact = cast("object", compiled.artifact)
    if not isinstance(artifact, FakeListArtifact):
        msg = "compiled artifact is not a FakeListArtifact"
        raise TypeError(msg)

    mismatches: list[str] = []
    if compiled.artifact_id != artifact.id:
        mismatches.append("artifact id")
    if compiled.target_id != artifact.target_id:
        mismatches.append("target id")
    if compiled.compiler_id != artifact.compiler_id:
        mismatches.append("compiler id")
    if compiled.capability_fingerprint != artifact.capability_fingerprint:
        mismatches.append("capability fingerprint")
    if compiled.artifact_fingerprint != artifact.artifact_fingerprint:
        mismatches.append("artifact fingerprint")
    if compiled.source_entry_ids != artifact.source_entry_ids:
        mismatches.append("source entry coverage")
    if compiled.repetitions != artifact.repetitions:
        mismatches.append("repetitions")
    if mismatches:
        msg = "compiled fake artifact correlation mismatch: " + ", ".join(mismatches)
        raise ValueError(msg)
    _validate_artifact(artifact)
    return artifact


def _validate_artifact(artifact: FakeListArtifact) -> None:
    if not isinstance(cast("object", artifact), FakeListArtifact):
        msg = "fake target runtime requires a FakeListArtifact"
        raise TypeError(msg)
    if not artifact.entries:
        msg = "fake list artifacts require at least one entry at runtime"
        raise ValueError(msg)
    if tuple(entry.list_index for entry in artifact.entries) != tuple(
        range(len(artifact.entries))
    ):
        msg = "fake list artifact indices are not contiguous and ordered"
        raise ValueError(msg)
    if tuple(entry.entry_id for entry in artifact.entries) != artifact.source_entry_ids:
        msg = "fake list artifact entry coverage does not match source_entry_ids"
        raise ValueError(msg)
    if artifact.repetitions <= 0:
        msg = "fake list artifact repetitions must be positive"
        raise ValueError(msg)
    if artifact.sample_rate_hz <= 0:
        msg = "fake list artifact sample_rate_hz must be positive"
        raise ValueError(msg)

    for entry in artifact.entries:
        if entry.sample_count <= 0:
            msg = f"fake list entry {entry.entry_id.value!r} has no samples"
            raise ValueError(msg)
        for waveform in entry.waveforms:
            if len(waveform.samples) != entry.sample_count:
                msg = (
                    f"fake list entry {entry.entry_id.value!r} has a malformed "
                    "waveform buffer"
                )
                raise ValueError(msg)
            if any(not _is_finite_complex(sample) for sample in waveform.samples):
                msg = (
                    f"fake list entry {entry.entry_id.value!r} has non-finite "
                    "waveform samples"
                )
                raise ValueError(msg)
        for window in entry.acquisitions:
            if window.start_sample + window.sample_count > entry.sample_count:
                msg = (
                    f"fake list entry {entry.entry_id.value!r} has an acquisition "
                    "window outside its sample buffer"
                )
                raise ValueError(msg)


def _waveform_fingerprint(entry: FakeListEntry) -> str:
    return canonical_fingerprint(
        {
            "schema": "quantum_lab_demo.fake_awg_waveforms.v1",
            "sample_count": entry.sample_count,
            "waveforms": [
                {
                    "channel_id": waveform.channel_id.value,
                    "samples": [
                        [sample.real.hex(), sample.imag.hex()]
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
    raw_playbacks = cast("object", playbacks)
    if not isinstance(raw_playbacks, tuple) or not all(
        isinstance(playback, FakeAwgPlayback)
        for playback in cast("tuple[object, ...]", raw_playbacks)
    ):
        msg = "fake digitizer playbacks must be FakeAwgPlayback values"
        raise TypeError(msg)
    selected = cast("tuple[FakeAwgPlayback, ...]", raw_playbacks)
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
    for playback in selected:
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


def _validate_frame_coverage(
    *,
    resolved: tuple[tuple[FakeAwgPlayback, FakeListEntry], ...],
    frames: tuple[FakeDigitizerFrame, ...],
) -> None:
    expected = tuple(
        (playback, entry, segment_index, window)
        for playback, entry in resolved
        for segment_index, window in enumerate(entry.acquisitions)
    )
    if len(frames) != len(expected):
        msg = "fake digitizer frames do not exactly cover artifact acquisition windows"
        raise ValueError(msg)
    for frame_index, (frame, expected_item) in enumerate(
        zip(frames, expected, strict=True)
    ):
        playback, entry, segment_index, window = expected_item
        if (
            frame.frame_index != frame_index
            or frame.segment_index != segment_index
            or frame.shot_index != playback.shot_index
            or frame.list_index != entry.list_index
            or frame.entry_id != entry.entry_id
            or frame.slot_id != window.slot_id
            or frame.channel_id != window.channel_id
            or frame.kind is not window.kind
        ):
            msg = "fake digitizer frame does not match its artifact acquisition window"
            raise ValueError(msg)
        expected_value = _capture_value(
            playback=playback,
            window=window,
        )
        if frame.value != expected_value:
            msg = "fake digitizer frame value does not match its logical address"
            raise ValueError(msg)


def _capture_value(
    *,
    playback: FakeAwgPlayback,
    window: FakeAcquisitionWindow,
) -> FakeDigitizerValue:
    address = {
        "schema": "quantum_lab_demo.fake_digitizer_address.v1",
        "shot_index": playback.shot_index,
        "entry_id": playback.entry_id.value,
        "waveform_fingerprint": playback.waveform_fingerprint,
        "event_id": pulse_event_identity_payload(window.event_id),
        "slot_id": acquisition_slot_identity_payload(window.slot_id),
        "signal": signal_key(window.signal),
        "channel_id": window.channel_id.value,
        "start_sample": window.start_sample,
        "sample_count": window.sample_count,
        "kind": window.kind.value,
    }
    if window.kind is AcquisitionKind.INTEGRATED_IQ:
        return _deterministic_complex(address=address, sample_index=None)
    if window.kind is AcquisitionKind.RAW_TRACE:
        return tuple(
            _deterministic_complex(address=address, sample_index=sample_index)
            for sample_index in range(window.sample_count)
        )
    msg = f"unsupported acquisition kind: {window.kind!r}"
    raise ValueError(msg)


def _deterministic_complex(
    *,
    address: dict[str, object],
    sample_index: int | None,
) -> complex:
    encoded = json.dumps(
        {**address, "sample_index": sample_index},
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
) -> str:
    return canonical_fingerprint(
        {
            "schema": "quantum_lab_demo.fake_list_run.v1",
            "artifact_id": artifact.id.value,
            "artifact_fingerprint": artifact.artifact_fingerprint,
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
                    "kind": frame.kind.value,
                    "value": _value_payload(frame.value),
                }
                for frame in frames
            ],
        }
    )


def _value_payload(value: FakeDigitizerValue) -> object:
    if isinstance(value, tuple):
        return [[sample.real.hex(), sample.imag.hex()] for sample in value]
    selected = cast("complex", value)
    return [selected.real.hex(), selected.imag.hex()]


__all__ = [
    "FakeAwgPlayback",
    "FakeDigitizerFrame",
    "FakeDigitizerValue",
    "FakeListAwg",
    "FakeListRun",
    "FakeListRuntime",
    "FakeSegmentedDigitizer",
]
