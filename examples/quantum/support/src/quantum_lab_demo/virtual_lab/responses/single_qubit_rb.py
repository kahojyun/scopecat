"""Deterministic survival-decay response for the single-qubit RB example."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import override

from scopecat_quantum import AcquisitionKind, TargetAcquisitionAddress

from quantum_lab_demo.targets.fake_list_mode.model import (
    FakeAcquisitionWindow,
    acquisition_slot_identity_payload,
    canonical_fingerprint,
)
from quantum_lab_demo.targets.fake_list_mode.runtime import (
    FakeAcquisitionResponse,
    FakeAwgPlayback,
    FakeDigitizerValue,
)


@dataclass(frozen=True, slots=True)
class SingleQubitRbResponsePoint:
    """One result address and its Clifford length and seed coordinates."""

    address: TargetAcquisitionAddress
    length: int
    seed: int


@dataclass(frozen=True, slots=True)
class SingleQubitRbAcquisitionResponse(FakeAcquisitionResponse):
    """Return state populations following an exponential RB survival curve."""

    points: tuple[SingleQubitRbResponsePoint, ...]
    shots: int
    depolarizing_parameter: float = 0.985
    asymptote: float = 0.5
    contrast: float = 0.48
    iq_jitter: float = 0.025
    _by_address: MappingProxyType[
        TargetAcquisitionAddress,
        SingleQubitRbResponsePoint,
    ] = field(init=False, repr=False, compare=False, hash=False)
    _state_one_shots: MappingProxyType[
        TargetAcquisitionAddress,
        frozenset[int],
    ] = field(init=False, repr=False, compare=False, hash=False)
    _fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        by_address = {point.address: point for point in self.points}
        payload = {
            "schema": "quantum_lab_demo.single_qubit_rb_response.v1",
            "shots": self.shots,
            "depolarizing_parameter": self.depolarizing_parameter.hex(),
            "asymptote": self.asymptote.hex(),
            "contrast": self.contrast.hex(),
            "iq_jitter": self.iq_jitter.hex(),
            "points": [
                {
                    "entry_id": point.address.entry_id.value,
                    "slot_id": acquisition_slot_identity_payload(point.address.slot_id),
                    "length": point.length,
                    "seed": point.seed,
                }
                for point in self.points
            ],
        }
        fingerprint = canonical_fingerprint(payload)
        state_one_shots: dict[TargetAcquisitionAddress, frozenset[int]] = {}
        for point in self.points:
            probability_one = 1.0 - self.survival_probability(point.length)
            count = math.floor(self.shots * probability_one + 0.5)
            ranked = sorted(
                range(self.shots),
                key=lambda shot: _shot_digest(
                    fingerprint,
                    point.address,
                    shot,
                    purpose="state",
                ),
            )
            state_one_shots[point.address] = frozenset(ranked[:count])
        object.__setattr__(self, "_by_address", MappingProxyType(by_address))
        object.__setattr__(
            self,
            "_state_one_shots",
            MappingProxyType(state_one_shots),
        )
        object.__setattr__(self, "_fingerprint", fingerprint)

    @property
    @override
    def fingerprint(self) -> str:
        return self._fingerprint

    def survival_probability(self, length: int) -> float:
        """Return the ideal state-zero probability at one Clifford length."""

        return self.asymptote + self.contrast * self.depolarizing_parameter**length

    @override
    def value_for(
        self,
        *,
        playback: FakeAwgPlayback,
        window: FakeAcquisitionWindow,
    ) -> FakeDigitizerValue:
        if window.kind is not AcquisitionKind.INTEGRATED_IQ:
            raise ValueError("single-qubit RB requires integrated-IQ acquisitions")
        address = TargetAcquisitionAddress(playback.entry_id, window.slot_id)
        if address not in self._by_address:
            raise ValueError("single-qubit RB response does not cover acquisition")
        state_one = playback.shot_index in self._state_one_shots[address]
        digest = _shot_digest(
            self.fingerprint,
            address,
            playback.shot_index,
            purpose="jitter",
        )
        real_jitter = _symmetric_fraction(digest[:8]) * self.iq_jitter
        imag_jitter = _symmetric_fraction(digest[8:16]) * self.iq_jitter
        return complex((1.0 if state_one else -1.0) + real_jitter, imag_jitter)


def _shot_digest(
    fingerprint: str,
    address: TargetAcquisitionAddress,
    shot_index: int,
    *,
    purpose: str,
) -> bytes:
    encoded = json.dumps(
        {
            "response_fingerprint": fingerprint,
            "entry_id": address.entry_id.value,
            "slot_id": acquisition_slot_identity_payload(address.slot_id),
            "shot_index": shot_index,
            "purpose": purpose,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).digest()


def _symmetric_fraction(raw: bytes) -> float:
    return 2.0 * int.from_bytes(raw, "big") / float((1 << (8 * len(raw))) - 1) - 1.0


__all__ = [
    "SingleQubitRbAcquisitionResponse",
    "SingleQubitRbResponsePoint",
]
