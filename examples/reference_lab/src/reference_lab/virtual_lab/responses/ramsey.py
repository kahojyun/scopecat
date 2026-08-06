"""Deterministic channel-aware Ramsey response model."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import override

from scopecat_quantum.targets import TargetAcquisitionAddress

from reference_lab.targets.fake_list_mode.model import (
    FakeAcquisitionWindow,
    acquisition_slot_identity_payload,
    canonical_fingerprint,
)
from reference_lab.targets.fake_list_mode.runtime import (
    FakeAcquisitionResponse,
    FakeAwgPlayback,
    FakeDigitizerValue,
)


@dataclass(frozen=True, slots=True)
class RamseyResponsePoint:
    address: TargetAcquisitionAddress
    phase_rad: float
    contrast: float
    available: bool = True


@dataclass(frozen=True, slots=True)
class RamseyAcquisitionResponse(FakeAcquisitionResponse):
    """Return stable binary IQ shots for every point and acquisition channel."""

    points: tuple[RamseyResponsePoint, ...]
    shots: int
    _state_one_shots: dict[TargetAcquisitionAddress, frozenset[int]] = field(
        init=False,
        repr=False,
        compare=False,
        hash=False,
    )
    _fingerprint: str = field(init=False, repr=False)
    _unavailable: frozenset[TargetAcquisitionAddress] = field(
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        payload = {
            "schema": "reference_lab.ramsey_response.v1",
            "shots": self.shots,
            "points": [
                {
                    "entry_id": point.address.entry_id.value,
                    "slot_id": acquisition_slot_identity_payload(point.address.slot_id),
                    "phase_rad": float(point.phase_rad).hex(),
                    "contrast": float(point.contrast).hex(),
                    "available": point.available,
                }
                for point in self.points
            ],
        }
        fingerprint = canonical_fingerprint(payload)
        selected: dict[TargetAcquisitionAddress, frozenset[int]] = {}
        for point in self.points:
            if not point.available:
                continue
            probability = 0.5 * (1.0 + point.contrast * math.cos(point.phase_rad))
            count = math.floor(self.shots * probability + 0.5)
            ranked = sorted(
                range(self.shots),
                key=lambda shot: _digest(fingerprint, point.address, shot),
            )
            selected[point.address] = frozenset(ranked[:count])
        object.__setattr__(self, "_state_one_shots", selected)
        object.__setattr__(
            self,
            "_unavailable",
            frozenset(point.address for point in self.points if not point.available),
        )
        object.__setattr__(self, "_fingerprint", fingerprint)

    @property
    @override
    def fingerprint(self) -> str:
        return self._fingerprint

    @override
    def value_for(
        self,
        *,
        playback: FakeAwgPlayback,
        window: FakeAcquisitionWindow,
    ) -> FakeDigitizerValue:
        address = TargetAcquisitionAddress(
            entry_id=playback.entry_id,
            slot_id=window.slot_id,
        )
        if address in self._unavailable:
            return None
        return complex(
            1.0 if playback.shot_index in self._state_one_shots[address] else -1.0,
            0.0,
        )


def _digest(
    fingerprint: str,
    address: TargetAcquisitionAddress,
    shot: int,
) -> bytes:
    encoded = json.dumps(
        {
            "fingerprint": fingerprint,
            "entry_id": address.entry_id.value,
            "slot_id": acquisition_slot_identity_payload(address.slot_id),
            "shot": shot,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).digest()


__all__ = ["RamseyAcquisitionResponse", "RamseyResponsePoint"]
