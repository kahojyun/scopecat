"""Deterministic device-response plan for the DRAG-beta reference experiment.

The fake target compiler remains a waveform compiler.  This lab-owned model is
bound later, at the acquisition effect boundary, where one exact target result
address is already correlated with its authored beta and amplification count.
Its fingerprint is included in both invocation intent and raw-run identity.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import override

from scopecat import Quantity
from scopecat_quantum import (
    AcquisitionKind,
    TargetAcquisitionAddress,
)

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

DEFAULT_OPTIMUM_BETA = Quantity(0.75, "ns")
DEFAULT_BASELINE = 0.04
DEFAULT_CURVATURE = 0.008
DEFAULT_IQ_JITTER = 0.025
DRAG_BETA_RESPONSE_MODEL_VERSION = "drag-beta-quadratic.v1"


@dataclass(frozen=True, slots=True)
class DragBetaResponsePoint:
    """Physical result address and the authored coordinates that drive it."""

    address: TargetAcquisitionAddress
    beta: Quantity
    amplification: int

    def __post_init__(self) -> None:
        _beta_ns(self.beta)
        _positive_int(self.amplification, field_name="amplification")

    @property
    def beta_ns(self) -> float:
        """Return beta in the canonical response-model unit."""

        return _beta_ns(self.beta)


@dataclass(frozen=True, slots=True)
class DragBetaAcquisitionResponse(FakeAcquisitionResponse):
    """Address-keyed deterministic IQ response for one prepared target batch.

    Exactly ``round(shots * p1)`` shots at each point are assigned to state 1.
    A stable hash permutes those assignments across shot order, while small
    bounded IQ jitter keeps the frames device-like without changing binary
    discrimination at the ``-1`` and ``+1`` centroids.
    """

    points: tuple[DragBetaResponsePoint, ...]
    shots: int
    optimum_beta: Quantity = DEFAULT_OPTIMUM_BETA
    baseline: float = DEFAULT_BASELINE
    curvature: float = DEFAULT_CURVATURE
    iq_jitter: float = DEFAULT_IQ_JITTER
    model_version: str = DRAG_BETA_RESPONSE_MODEL_VERSION
    _by_address: MappingProxyType[
        TargetAcquisitionAddress,
        DragBetaResponsePoint,
    ] = field(init=False, repr=False, compare=False, hash=False)
    _state_one_shots: MappingProxyType[
        TargetAcquisitionAddress,
        frozenset[int],
    ] = field(init=False, repr=False, compare=False, hash=False)
    _fingerprint: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        selected = tuple(self.points)
        if not selected:
            msg = "DRAG acquisition responses require response points"
            raise ValueError(msg)
        by_address = {point.address: point for point in selected}
        if len(by_address) != len(selected):
            msg = "DRAG response point addresses must be unique"
            raise ValueError(msg)
        shots = _positive_int(self.shots, field_name="shots")
        optimum_beta_ns = _beta_ns(self.optimum_beta)
        baseline = _finite_float(self.baseline, field_name="baseline")
        curvature = _finite_float(self.curvature, field_name="curvature")
        jitter = _finite_float(self.iq_jitter, field_name="iq_jitter")
        if not 0.0 <= baseline <= 1.0:
            msg = "DRAG response baseline must lie in [0, 1]"
            raise ValueError(msg)
        if curvature <= 0.0:
            msg = "DRAG response curvature must be positive"
            raise ValueError(msg)
        if not 0.0 <= jitter < 0.5:
            msg = "DRAG response IQ jitter must lie in [0, 0.5)"
            raise ValueError(msg)
        if not self.model_version:
            msg = "DRAG response model_version must be a non-empty string"
            raise ValueError(msg)

        payload = {
            "schema": "quantum_lab_demo.drag_beta_response_plan.v1",
            "model_version": self.model_version,
            "shots": shots,
            "optimum_beta_ns": optimum_beta_ns.hex(),
            "baseline": baseline.hex(),
            "curvature": curvature.hex(),
            "iq_jitter": jitter.hex(),
            "points": [
                {
                    "entry_id": point.address.entry_id.value,
                    "slot_id": acquisition_slot_identity_payload(point.address.slot_id),
                    "beta_ns": point.beta_ns.hex(),
                    "amplification": point.amplification,
                }
                for point in selected
            ],
        }
        fingerprint = canonical_fingerprint(payload)
        state_one_shots: dict[TargetAcquisitionAddress, frozenset[int]] = {}
        for point in selected:
            probability = _probability_one(
                beta_ns=point.beta_ns,
                amplification=point.amplification,
                optimum_beta_ns=optimum_beta_ns,
                baseline=baseline,
                curvature=curvature,
            )
            count = math.floor(shots * probability + 0.5)
            ranked = sorted(
                range(shots),
                key=lambda shot_index: _shot_digest(
                    fingerprint,
                    point.address,
                    shot_index,
                    purpose="state",
                ),
            )
            state_one_shots[point.address] = frozenset(ranked[:count])

        object.__setattr__(self, "points", selected)
        object.__setattr__(self, "shots", shots)
        object.__setattr__(self, "baseline", baseline)
        object.__setattr__(self, "curvature", curvature)
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
        """Return the stable identity of all response-affecting facts."""

        return self._fingerprint

    @property
    def addresses(self) -> tuple[TargetAcquisitionAddress, ...]:
        """Return exact result-address coverage in prepared point order."""

        return tuple(point.address for point in self.points)

    @property
    def intent(self) -> dict[str, object]:
        """Return the stable invocation-intent fragment for this response."""

        return {
            "schema": "quantum_lab_demo.drag_beta_response_intent.v1",
            "model_version": self.model_version,
            "response_fingerprint": self.fingerprint,
            "shots": self.shots,
            "optimum_beta_ns": _beta_ns(self.optimum_beta).hex(),
            "baseline": self.baseline.hex(),
            "curvature": self.curvature.hex(),
            "iq_jitter": self.iq_jitter.hex(),
            "points": [
                {
                    "entry_id": point.address.entry_id.value,
                    "slot_id": acquisition_slot_identity_payload(point.address.slot_id),
                    "beta_ns": point.beta_ns.hex(),
                    "amplification": point.amplification,
                }
                for point in self.points
            ],
        }

    def probability_one(self, address: TargetAcquisitionAddress) -> float:
        """Return the ideal model probability for one covered address."""

        try:
            point = self._by_address[address]
        except KeyError as error:
            msg = f"DRAG response plan does not cover result address {address!r}"
            raise KeyError(msg) from error
        return _probability_one(
            beta_ns=point.beta_ns,
            amplification=point.amplification,
            optimum_beta_ns=_beta_ns(self.optimum_beta),
            baseline=self.baseline,
            curvature=self.curvature,
        )

    @override
    def value_for(
        self,
        *,
        playback: FakeAwgPlayback,
        window: FakeAcquisitionWindow,
    ) -> FakeDigitizerValue:
        """Generate one deterministic integrated-IQ frame."""

        if window.kind is not AcquisitionKind.INTEGRATED_IQ:
            msg = "DRAG response plans only implement integrated-IQ acquisitions"
            raise ValueError(msg)
        address = TargetAcquisitionAddress(
            entry_id=playback.entry_id,
            slot_id=window.slot_id,
        )
        if address not in self._by_address:
            msg = f"DRAG response plan does not cover result address {address!r}"
            raise ValueError(msg)
        if playback.shot_index >= self.shots:
            msg = "DRAG response playback shot exceeds the prepared shot count"
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


def _probability_one(
    *,
    beta_ns: float,
    amplification: int,
    optimum_beta_ns: float,
    baseline: float,
    curvature: float,
) -> float:
    probability = (
        baseline + curvature * amplification**2 * (beta_ns - optimum_beta_ns) ** 2
    )
    if not 0.0 <= probability <= 1.0:
        msg = "DRAG response probability lies outside [0, 1]; narrow the scan"
        raise ValueError(msg)
    return probability


def _shot_digest(
    fingerprint: str,
    address: TargetAcquisitionAddress,
    shot_index: int,
    *,
    purpose: str,
) -> bytes:
    encoded = json.dumps(
        {
            "schema": "quantum_lab_demo.drag_beta_shot.v1",
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
        msg = f"DRAG response {field_name} must be a positive integer"
        raise ValueError(msg)
    return value


def _finite_float(value: object, *, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        msg = f"DRAG response {field_name} must be a finite number"
        raise TypeError(msg)
    selected = float(value)
    if not math.isfinite(selected):
        msg = f"DRAG response {field_name} must be a finite number"
        raise ValueError(msg)
    return selected


def _beta_ns(value: object) -> float:
    if not isinstance(value, Quantity):
        msg = "DRAG response beta values must be time quantities"
        raise TypeError(msg)
    try:
        selected = float(value.to("ns").value)
    except ValueError as error:
        msg = "DRAG response beta values must be time quantities"
        raise ValueError(msg) from error
    if not math.isfinite(selected):
        msg = "DRAG response beta values must be finite"
        raise ValueError(msg)
    return selected


__all__ = [
    "DEFAULT_BASELINE",
    "DEFAULT_CURVATURE",
    "DEFAULT_IQ_JITTER",
    "DEFAULT_OPTIMUM_BETA",
    "DRAG_BETA_RESPONSE_MODEL_VERSION",
    "DragBetaAcquisitionResponse",
    "DragBetaResponsePoint",
]
