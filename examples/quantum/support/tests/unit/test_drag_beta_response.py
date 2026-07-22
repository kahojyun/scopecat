from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest
from scopecat import Quantity
from scopecat_quantum import (
    AcquireSignal,
    AcquisitionKind,
    AcquisitionSlotId,
    PulseEventId,
    QubitId,
    TargetAcquisitionAddress,
    TargetCompileEntryId,
)

from quantum_lab_demo.targets.fake_list_mode import (
    FakeAcquisitionResponse,
    FakeAcquisitionWindow,
    FakeAwgPlayback,
    FakeDigitizerChannelId,
)
from quantum_lab_demo.virtual_lab.responses.drag_beta import (
    DragBetaAcquisitionResponse,
    DragBetaResponsePoint,
)


def _address(entry: str) -> TargetAcquisitionAddress:
    return TargetAcquisitionAddress(
        entry_id=TargetCompileEntryId(entry),
        slot_id=AcquisitionSlotId("iq_shots"),
    )


def _window(*, kind: AcquisitionKind = AcquisitionKind.INTEGRATED_IQ):
    return FakeAcquisitionWindow(
        event_id=PulseEventId("capture"),
        slot_id=AcquisitionSlotId("iq_shots"),
        signal=AcquireSignal(QubitId("q0")),
        channel_id=FakeDigitizerChannelId("digitizer-q0"),
        start_sample=4,
        sample_count=8,
        kind=kind,
    )


def _playback(entry: str, shot: int) -> FakeAwgPlayback:
    return FakeAwgPlayback(
        shot_index=shot,
        list_index=0,
        entry_id=TargetCompileEntryId(entry),
        waveform_fingerprint="waveform:v1",
    )


def test_drag_response_generates_exact_deterministic_probability_counts() -> None:
    address = _address("entry-a")
    response = DragBetaAcquisitionResponse(
        points=(
            DragBetaResponsePoint(
                address,
                Quantity(0.5, "ns"),
                amplification=5,
            ),
        ),
        shots=200,
    )

    first = tuple(
        response.value_for(playback=_playback("entry-a", shot), window=_window())
        for shot in range(response.shots)
    )
    second = tuple(
        response.value_for(playback=_playback("entry-a", shot), window=_window())
        for shot in range(response.shots)
    )
    probability = response.probability_one(address)

    assert isinstance(response, FakeAcquisitionResponse)
    assert first == second
    assert all(isinstance(value, complex) for value in first)
    iq_values = cast("tuple[complex, ...]", first)
    assert sum(value.real > 0 for value in iq_values) == round(
        response.shots * probability
    )
    assert probability == pytest.approx(0.0525)
    assert all(abs(value.imag) <= response.iq_jitter for value in iq_values)


def test_drag_response_identity_covers_coordinates_and_model_configuration() -> None:
    point = DragBetaResponsePoint(
        _address("entry-a"),
        Quantity(0.5, "ns"),
        amplification=5,
    )
    response = DragBetaAcquisitionResponse((point,), shots=64)

    assert response.fingerprint.startswith("sha256:")
    assert response.intent["response_fingerprint"] == response.fingerprint
    assert (
        replace(response, curvature=response.curvature * 2.0).fingerprint
        != response.fingerprint
    )
    assert (
        DragBetaAcquisitionResponse(
            (replace(point, amplification=7),),
            shots=64,
        ).fingerprint
        != response.fingerprint
    )


def test_drag_response_rejects_uncovered_and_non_iq_acquisitions() -> None:
    response = DragBetaAcquisitionResponse(
        (
            DragBetaResponsePoint(
                _address("entry-a"),
                Quantity(0.75, "ns"),
                amplification=3,
            ),
        ),
        shots=16,
    )

    with pytest.raises(ValueError, match="does not cover"):
        response.value_for(
            playback=_playback("entry-b", 0),
            window=_window(),
        )
    with pytest.raises(ValueError, match="integrated-IQ"):
        response.value_for(
            playback=_playback("entry-a", 0),
            window=_window(kind=AcquisitionKind.RAW_TRACE),
        )


def test_drag_response_requires_total_unique_sensible_points() -> None:
    point = DragBetaResponsePoint(
        _address("entry-a"),
        Quantity(0.75, "ns"),
        amplification=3,
    )

    with pytest.raises(ValueError, match="unique"):
        DragBetaAcquisitionResponse((point, point), shots=16)
    with pytest.raises(ValueError, match="narrow the scan"):
        DragBetaAcquisitionResponse(
            (
                DragBetaResponsePoint(
                    _address("entry-b"),
                    Quantity(10, "ns"),
                    amplification=20,
                ),
            ),
            shots=16,
        )
