"""Deterministic conditional-phase Ramsey response for the CZ reference lab."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, override

from scopecat import Quantity
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

DEFAULT_CZ_AMPLITUDE = Quantity(0.24, "arb")
DEFAULT_CZ_CONTRAST = 0.90
DEFAULT_CZ_IQ_JITTER = 0.025
CZ_PHASE_RESPONSE_MODEL_VERSION = "cz-conditional-phase-ramsey.v1"


@dataclass(frozen=True, slots=True)
class CzPhaseResponsePoint:
    """Two result addresses and authored coordinates for one Ramsey point."""

    control_address: TargetAcquisitionAddress
    target_address: TargetAcquisitionAddress
    amplitude: Quantity
    control_state: int
    analyzer_phase: Quantity

    def __post_init__(self) -> None:
        if self.control_address == self.target_address:
            msg = "CZ phase response control and target addresses must differ"
            raise ValueError(msg)
        _amplitude(self.amplitude)
        _control_state(self.control_state)
        _phase(self.analyzer_phase)

    @property
    def amplitude_arb(self) -> float:
        return _amplitude(self.amplitude)

    @property
    def analyzer_phase_rad(self) -> float:
        return _phase(self.analyzer_phase)


type _ResultRole = Literal["control", "target"]


@dataclass(frozen=True, slots=True)
class CzPhaseAcquisitionResponse(FakeAcquisitionResponse):
    """Address-keyed deterministic IQ frames for conditional-phase Ramsey."""

    points: tuple[CzPhaseResponsePoint, ...]
    shots: int
    optimum_amplitude: Quantity = DEFAULT_CZ_AMPLITUDE
    contrast: float = DEFAULT_CZ_CONTRAST
    iq_jitter: float = DEFAULT_CZ_IQ_JITTER
    model_version: str = CZ_PHASE_RESPONSE_MODEL_VERSION
    _by_address: MappingProxyType[
        TargetAcquisitionAddress,
        tuple[CzPhaseResponsePoint, _ResultRole],
    ] = field(init=False, repr=False, compare=False, hash=False)
    _state_one_shots: MappingProxyType[
        TargetAcquisitionAddress,
        frozenset[int],
    ] = field(init=False, repr=False, compare=False, hash=False)
    _fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        selected = tuple(self.points)
        if not selected:
            msg = "CZ phase responses require response points"
            raise ValueError(msg)
        shots = _positive_int(self.shots, field_name="shots")
        optimum = _amplitude(self.optimum_amplitude)
        contrast = _finite_float(self.contrast, field_name="contrast")
        jitter = _finite_float(self.iq_jitter, field_name="iq_jitter")
        if not 0.0 < contrast <= 1.0:
            msg = "CZ phase response contrast must lie in (0, 1]"
            raise ValueError(msg)
        if not 0.0 <= jitter < 0.5:
            msg = "CZ phase response IQ jitter must lie in [0, 0.5)"
            raise ValueError(msg)
        if not self.model_version:
            msg = "CZ phase response model_version must be non-empty"
            raise ValueError(msg)

        by_address: dict[
            TargetAcquisitionAddress,
            tuple[CzPhaseResponsePoint, _ResultRole],
        ] = {}
        for point in selected:
            result_addresses: tuple[
                tuple[TargetAcquisitionAddress, _ResultRole], ...
            ] = (
                (point.control_address, "control"),
                (point.target_address, "target"),
            )
            for address, role in result_addresses:
                if address in by_address:
                    msg = "CZ phase response addresses must be unique"
                    raise ValueError(msg)
                by_address[address] = (point, role)

        payload = {
            "schema": "quantum_lab_demo.cz_phase_response_plan.v1",
            "model_version": self.model_version,
            "shots": shots,
            "optimum_amplitude_arb": optimum.hex(),
            "contrast": contrast.hex(),
            "iq_jitter": jitter.hex(),
            "points": [
                {
                    "control_entry": point.control_address.entry_id.value,
                    "control_slot": acquisition_slot_identity_payload(
                        point.control_address.slot_id
                    ),
                    "target_entry": point.target_address.entry_id.value,
                    "target_slot": acquisition_slot_identity_payload(
                        point.target_address.slot_id
                    ),
                    "amplitude_arb": point.amplitude_arb.hex(),
                    "control_state": point.control_state,
                    "analyzer_phase_rad": point.analyzer_phase_rad.hex(),
                }
                for point in selected
            ],
        }
        fingerprint = canonical_fingerprint(payload)
        state_one_shots: dict[TargetAcquisitionAddress, frozenset[int]] = {}
        for address, (point, role) in by_address.items():
            probability = _probability_one(
                point,
                role=role,
                optimum_amplitude=optimum,
                contrast=contrast,
            )
            count = math.floor(shots * probability + 0.5)
            ranked = sorted(
                range(shots),
                key=lambda shot_index: _shot_digest(
                    fingerprint,
                    address,
                    shot_index,
                    purpose="state",
                ),
            )
            state_one_shots[address] = frozenset(ranked[:count])

        object.__setattr__(self, "points", selected)
        object.__setattr__(self, "shots", shots)
        object.__setattr__(self, "contrast", contrast)
        object.__setattr__(self, "iq_jitter", jitter)
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

    @property
    def addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        return tuple(
            address
            for point in self.points
            for address in (point.control_address, point.target_address)
        )

    @property
    def intent(self) -> dict[str, object]:
        return {
            "schema": "quantum_lab_demo.cz_phase_response_intent.v1",
            "model_version": self.model_version,
            "response_fingerprint": self.fingerprint,
            "shots": self.shots,
            "optimum_amplitude_arb": _amplitude(self.optimum_amplitude).hex(),
            "contrast": self.contrast.hex(),
        }

    def probability_one(self, address: TargetAcquisitionAddress) -> float:
        try:
            point, role = self._by_address[address]
        except KeyError as error:
            msg = f"CZ phase response does not cover result address {address!r}"
            raise KeyError(msg) from error
        return _probability_one(
            point,
            role=role,
            optimum_amplitude=_amplitude(self.optimum_amplitude),
            contrast=self.contrast,
        )

    @override
    def value_for(
        self,
        *,
        playback: FakeAwgPlayback,
        window: FakeAcquisitionWindow,
    ) -> FakeDigitizerValue:
        if window.kind is not AcquisitionKind.INTEGRATED_IQ:
            msg = "CZ phase responses only implement integrated-IQ acquisitions"
            raise ValueError(msg)
        address = TargetAcquisitionAddress(
            entry_id=playback.entry_id,
            slot_id=window.slot_id,
        )
        if address not in self._by_address:
            msg = f"CZ phase response does not cover result address {address!r}"
            raise ValueError(msg)
        if playback.shot_index >= self.shots:
            msg = "CZ phase response playback exceeds the prepared shot count"
            raise ValueError(msg)
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


def conditional_phase(amplitude: Quantity) -> float:
    """Return the deterministic device conditional phase in radians."""

    return math.pi * _amplitude(amplitude) / _amplitude(DEFAULT_CZ_AMPLITUDE)


def _probability_one(
    point: CzPhaseResponsePoint,
    *,
    role: _ResultRole,
    optimum_amplitude: float,
    contrast: float,
) -> float:
    delta = abs(point.amplitude_arb - optimum_amplitude)
    control_error = min(0.08, 0.02 + 0.25 * delta)
    if role == "control":
        return control_error if point.control_state == 0 else 1.0 - control_error
    selected_contrast = max(0.70, contrast - 1.5 * delta)
    phase_shift = (
        math.pi * point.amplitude_arb / optimum_amplitude
        if point.control_state == 1
        else 0.0
    )
    probability = 0.5 - 0.5 * selected_contrast * math.cos(
        point.analyzer_phase_rad - phase_shift
    )
    return min(1.0, max(0.0, probability))


def _shot_digest(
    fingerprint: str,
    address: TargetAcquisitionAddress,
    shot_index: int,
    *,
    purpose: str,
) -> bytes:
    encoded = json.dumps(
        {
            "schema": "quantum_lab_demo.cz_phase_shot.v1",
            "response_fingerprint": fingerprint,
            "entry_id": address.entry_id.value,
            "slot_id": acquisition_slot_identity_payload(address.slot_id),
            "shot_index": shot_index,
            "purpose": purpose,
        },
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).digest()


def _symmetric_fraction(raw: bytes) -> float:
    denominator = float((1 << (8 * len(raw))) - 1)
    return 2.0 * int.from_bytes(raw, "big") / denominator - 1.0


def _positive_int(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        msg = f"CZ phase response {field_name} must be a positive integer"
        raise ValueError(msg)
    return value


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"CZ phase response {field_name} must be a finite number"
        raise TypeError(msg)
    selected = float(value)
    if not math.isfinite(selected):
        msg = f"CZ phase response {field_name} must be a finite number"
        raise ValueError(msg)
    return selected


def _amplitude(value: object) -> float:
    if not isinstance(value, Quantity):
        msg = "CZ phase amplitudes must be quantities"
        raise TypeError(msg)
    try:
        selected = float(value.to("arb").value)
    except ValueError as error:
        msg = "CZ phase amplitudes must use amplitude units"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "CZ phase amplitudes must be finite"
        raise ValueError(msg)
    return selected


def _phase(value: object) -> float:
    if not isinstance(value, Quantity):
        msg = "CZ analyzer phases must be quantities"
        raise TypeError(msg)
    try:
        selected = float(value.to("rad").value)
    except ValueError as error:
        msg = "CZ analyzer phases must use phase units"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "CZ analyzer phases must be finite"
        raise ValueError(msg)
    return selected


def _control_state(value: object) -> int:
    if type(value) is not int or value not in (0, 1):
        msg = "CZ control states must be 0 or 1"
        raise ValueError(msg)
    return value


__all__ = [
    "CZ_PHASE_RESPONSE_MODEL_VERSION",
    "DEFAULT_CZ_AMPLITUDE",
    "DEFAULT_CZ_CONTRAST",
    "DEFAULT_CZ_IQ_JITTER",
    "CzPhaseAcquisitionResponse",
    "CzPhaseResponsePoint",
    "conditional_phase",
]
