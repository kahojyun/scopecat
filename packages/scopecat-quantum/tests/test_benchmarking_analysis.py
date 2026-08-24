from __future__ import annotations

import numpy as np
import pytest

from scopecat_quantum.benchmarking import (
    fit_parallel_rb_decay,
    fit_rb_decay,
    fit_xeb_decay,
    interleaved_rb_error,
    linear_xeb_from_distribution,
    linear_xeb_from_samples,
)


def test_rb_decay_recovers_reference_curve_and_error_per_clifford() -> None:
    lengths = (1, 2, 4, 8, 16, 32)
    probabilities = tuple(0.43 * 0.97**length + 0.5 for length in lengths)

    fit = fit_rb_decay(lengths, probabilities)

    assert fit.amplitude == pytest.approx(0.43, abs=1e-9)
    assert fit.decay == pytest.approx(0.97, abs=1e-9)
    assert fit.offset == pytest.approx(0.5, abs=1e-9)
    assert fit.error_per_clifford == pytest.approx(0.015, abs=1e-9)
    assert fit.rmse < 1e-10


def test_parallel_rb_decay_preserves_entity_identity() -> None:
    lengths = (1, 2, 4, 8, 16)
    probabilities = np.column_stack(
        (
            tuple(0.4 * 0.98**length + 0.5 for length in lengths),
            tuple(0.45 * 0.95**length + 0.48 for length in lengths),
        )
    )

    fits = fit_parallel_rb_decay(lengths, probabilities, ("q0", "q7"))

    assert tuple(fit.entity_id for fit in fits) == ("q0", "q7")
    assert fits[0].fit.decay == pytest.approx(0.98, abs=1e-9)
    assert fits[1].fit.decay == pytest.approx(0.95, abs=1e-9)


def test_interleaved_rb_and_linear_xeb_reference_estimators() -> None:
    interleaved_error = interleaved_rb_error(0.98, 0.96)
    samples = linear_xeb_from_samples((0.5, 0.25), dimension=4)
    distribution = linear_xeb_from_distribution(
        (0.5, 0.25, 0.125, 0.125),
        (0.5, 0.25, 0.125, 0.125),
    )

    assert interleaved_error == pytest.approx(0.010204081632653073)
    assert samples.fidelity == pytest.approx(0.5)
    assert samples.sample_count == 2
    assert distribution.fidelity == pytest.approx(0.375)
    assert distribution.dimension == 4


def test_xeb_decay_recovers_cycle_fidelity() -> None:
    cycles = (1, 2, 4, 8, 16)
    fidelities = tuple(0.8 * 0.95**cycle for cycle in cycles)

    fit = fit_xeb_decay(cycles, fidelities)

    assert fit.amplitude == pytest.approx(0.8, abs=1e-9)
    assert fit.cycle_fidelity == pytest.approx(0.95, abs=1e-9)
    assert fit.cycle_error == pytest.approx(0.05, abs=1e-9)
    assert fit.rmse < 1e-10
