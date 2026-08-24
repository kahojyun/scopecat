"""Numerical reference analysis for RB decay and linear XEB fidelity."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np


@dataclass(frozen=True, slots=True)
class RbDecayFit:
    """Fit of ``A * decay**length + B`` and its average Clifford error."""

    amplitude: float
    decay: float
    offset: float
    dimension: int
    error_per_clifford: float
    rmse: float
    point_count: int


@dataclass(frozen=True, slots=True)
class EntityRbDecayFit:
    """One entity-addressed fit from a parallel RB result."""

    entity_id: str
    fit: RbDecayFit


@dataclass(frozen=True, slots=True)
class XebDecayFit:
    """Fit of ``A * cycle_fidelity**cycles`` for XEB fidelity decay."""

    amplitude: float
    cycle_fidelity: float
    cycle_error: float
    rmse: float
    point_count: int


@dataclass(frozen=True, slots=True)
class LinearXebEstimate:
    """A linear-XEB fidelity estimate with its evaluated Hilbert dimension."""

    fidelity: float
    dimension: int
    sample_count: int


def _observations(
    coordinates: Sequence[int],
    values: Sequence[float],
    weights: Sequence[float] | None,
) -> tuple[tuple[int, ...], tuple[float, ...], tuple[float, ...]]:
    x = tuple(coordinates)
    y = tuple(float(value) for value in values)
    if len(x) != len(y) or len(x) < 3:
        raise ValueError("decay fitting requires at least three paired observations")
    if any(not math.isfinite(value) for value in y):
        raise ValueError("decay observations must be finite")
    if any(value < 0 for value in x):
        raise ValueError("decay coordinates must be non-negative integers")
    selected_weights = (
        (1.0,) * len(x)
        if weights is None
        else tuple(float(weight) for weight in weights)
    )
    if len(selected_weights) != len(x) or any(
        not math.isfinite(weight) for weight in selected_weights
    ):
        raise ValueError("decay weights must match the finite observation vector")
    if any(weight <= 0 for weight in selected_weights):
        raise ValueError("decay weights must be positive")
    return x, y, selected_weights


def _minimum_on_unit_interval(objective: Callable[[float], float]) -> float:
    grid = tuple(index / 2_048 for index in range(2_049))
    errors = tuple(objective(candidate) for candidate in grid)
    best = min(range(len(errors)), key=errors.__getitem__)
    left = grid[max(0, best - 1)]
    right = grid[min(len(grid) - 1, best + 1)]
    golden_ratio = (math.sqrt(5.0) - 1.0) / 2.0
    first = right - golden_ratio * (right - left)
    second = left + golden_ratio * (right - left)
    first_error = objective(first)
    second_error = objective(second)
    for _ in range(64):
        if first_error <= second_error:
            right = second
            second = first
            second_error = first_error
            first = right - golden_ratio * (right - left)
            first_error = objective(first)
        else:
            left = first
            first = second
            first_error = second_error
            second = left + golden_ratio * (right - left)
            second_error = objective(second)
    candidates = (0.0, 1.0, grid[best], (left + right) / 2.0)
    return min(candidates, key=objective)


def _affine_exponential_parameters(
    decay: float,
    x: tuple[int, ...],
    y: tuple[float, ...],
    weights: tuple[float, ...],
) -> tuple[float, float, float]:
    basis = tuple(decay**coordinate for coordinate in x)
    weight_sum = math.fsum(weights)
    weighted_basis = math.fsum(
        weight * value for weight, value in zip(weights, basis, strict=True)
    )
    weighted_basis_squared = math.fsum(
        weight * value * value for weight, value in zip(weights, basis, strict=True)
    )
    weighted_y = math.fsum(
        weight * value for weight, value in zip(weights, y, strict=True)
    )
    weighted_basis_y = math.fsum(
        weight * basis_value * observed
        for weight, basis_value, observed in zip(weights, basis, y, strict=True)
    )
    determinant = weighted_basis_squared * weight_sum - weighted_basis**2
    if abs(determinant) < 1.0e-15:
        amplitude = 0.0
        offset = weighted_y / weight_sum
    else:
        amplitude = (
            weighted_basis_y * weight_sum - weighted_y * weighted_basis
        ) / determinant
        offset = (
            weighted_basis_squared * weighted_y - weighted_basis * weighted_basis_y
        ) / determinant
    squared_error = math.fsum(
        weight * (observed - (amplitude * basis_value + offset)) ** 2
        for weight, observed, basis_value in zip(weights, y, basis, strict=True)
    )
    return squared_error, amplitude, offset


def fit_rb_decay(
    lengths: Sequence[int],
    survival_probabilities: Sequence[float],
    *,
    dimension: int = 2,
    weights: Sequence[float] | None = None,
) -> RbDecayFit:
    """Fit the conventional RB survival curve without a SciPy dependency."""

    if dimension < 2:
        raise ValueError("RB Hilbert dimension must be at least two")
    x, y, selected_weights = _observations(
        lengths,
        survival_probabilities,
        weights,
    )

    def objective(decay: float) -> float:
        return _affine_exponential_parameters(decay, x, y, selected_weights)[0]

    decay = _minimum_on_unit_interval(objective)
    squared_error, amplitude, offset = _affine_exponential_parameters(
        decay,
        x,
        y,
        selected_weights,
    )
    error_per_clifford = (dimension - 1) * (1.0 - decay) / dimension
    return RbDecayFit(
        amplitude=amplitude,
        decay=decay,
        offset=offset,
        dimension=dimension,
        error_per_clifford=error_per_clifford,
        rmse=math.sqrt(squared_error / math.fsum(selected_weights)),
        point_count=len(x),
    )


def fit_parallel_rb_decay(
    lengths: Sequence[int],
    survival_probabilities: object,
    entity_ids: Sequence[str],
    *,
    dimension: int = 2,
) -> tuple[EntityRbDecayFit, ...]:
    """Fit one RB decay along every column of a length-by-entity array."""

    values = cast(
        "np.ndarray[tuple[int, ...], np.dtype[np.float64]]",
        np.asarray(survival_probabilities, dtype=np.float64),
    )
    if values.shape != (len(lengths), len(entity_ids)):
        raise ValueError("parallel RB values must have shape length by entity")
    if len(set(entity_ids)) != len(entity_ids):
        raise ValueError("parallel RB entity ids must be unique")
    return tuple(
        EntityRbDecayFit(
            entity_id=entity_id,
            fit=fit_rb_decay(
                lengths,
                cast("list[float]", values[:, entity_index].tolist()),
                dimension=dimension,
            ),
        )
        for entity_index, entity_id in enumerate(entity_ids)
    )


def interleaved_rb_error(
    reference_decay: float,
    interleaved_decay: float,
    *,
    dimension: int = 2,
) -> float:
    """Estimate interleaved-gate error from reference and interleaved decays."""

    if dimension < 2:
        raise ValueError("RB Hilbert dimension must be at least two")
    if not 0.0 < reference_decay <= 1.0:
        raise ValueError("reference RB decay must be in (0, 1]")
    if not 0.0 <= interleaved_decay <= 1.0:
        raise ValueError("interleaved RB decay must be in [0, 1]")
    return (dimension - 1) * (1.0 - interleaved_decay / reference_decay) / dimension


def linear_xeb_from_samples(
    sampled_ideal_probabilities: Sequence[float],
    *,
    dimension: int,
) -> LinearXebEstimate:
    """Estimate linear XEB from ideal probabilities of the observed bitstrings."""

    values = tuple(float(value) for value in sampled_ideal_probabilities)
    if not values:
        raise ValueError("linear XEB requires a non-empty probability vector")
    if dimension < 2:
        raise ValueError("XEB Hilbert dimension must be at least two")
    if any(not math.isfinite(value) or not 0.0 <= value <= 1.0 for value in values):
        raise ValueError("sampled ideal probabilities must be finite values in [0, 1]")
    return LinearXebEstimate(
        fidelity=dimension * math.fsum(values) / len(values) - 1.0,
        dimension=dimension,
        sample_count=len(values),
    )


def linear_xeb_from_distribution(
    ideal_probabilities: Sequence[float],
    observed_probabilities: Sequence[float],
) -> LinearXebEstimate:
    """Evaluate linear XEB from complete ideal and observed distributions."""

    ideal = tuple(float(value) for value in ideal_probabilities)
    observed = tuple(float(value) for value in observed_probabilities)
    if len(ideal) < 2 or len(observed) != len(ideal):
        raise ValueError("XEB distributions must be paired one-dimensional vectors")
    if any(not math.isfinite(value) for value in (*ideal, *observed)):
        raise ValueError("XEB distributions must be finite")
    if any(value < 0.0 for value in (*ideal, *observed)):
        raise ValueError("XEB distributions must be non-negative")
    if not math.isclose(math.fsum(ideal), 1.0) or not math.isclose(
        math.fsum(observed),
        1.0,
    ):
        raise ValueError("XEB distributions must be normalized")
    dimension = len(ideal)
    return LinearXebEstimate(
        fidelity=(
            dimension
            * math.fsum(
                ideal_value * observed_value
                for ideal_value, observed_value in zip(ideal, observed, strict=True)
            )
            - 1.0
        ),
        dimension=dimension,
        sample_count=dimension,
    )


def _scaled_exponential_parameters(
    decay: float,
    x: tuple[int, ...],
    y: tuple[float, ...],
    weights: tuple[float, ...],
) -> tuple[float, float]:
    basis = tuple(decay**coordinate for coordinate in x)
    denominator = math.fsum(
        weight * value * value for weight, value in zip(weights, basis, strict=True)
    )
    amplitude = (
        0.0
        if denominator == 0.0
        else math.fsum(
            weight * basis_value * observed
            for weight, basis_value, observed in zip(weights, basis, y, strict=True)
        )
        / denominator
    )
    squared_error = math.fsum(
        weight * (observed - amplitude * basis_value) ** 2
        for weight, observed, basis_value in zip(weights, y, basis, strict=True)
    )
    return squared_error, amplitude


def fit_xeb_decay(
    cycles: Sequence[int],
    fidelities: Sequence[float],
    *,
    weights: Sequence[float] | None = None,
) -> XebDecayFit:
    """Fit a zero-offset exponential decay to XEB fidelity versus cycle count."""

    x, y, selected_weights = _observations(cycles, fidelities, weights)

    def objective(decay: float) -> float:
        return _scaled_exponential_parameters(decay, x, y, selected_weights)[0]

    decay = _minimum_on_unit_interval(objective)
    squared_error, amplitude = _scaled_exponential_parameters(
        decay,
        x,
        y,
        selected_weights,
    )
    return XebDecayFit(
        amplitude=amplitude,
        cycle_fidelity=decay,
        cycle_error=1.0 - decay,
        rmse=math.sqrt(squared_error / math.fsum(selected_weights)),
        point_count=len(x),
    )


__all__ = [
    "EntityRbDecayFit",
    "LinearXebEstimate",
    "RbDecayFit",
    "XebDecayFit",
    "fit_parallel_rb_decay",
    "fit_rb_decay",
    "fit_xeb_decay",
    "interleaved_rb_error",
    "linear_xeb_from_distribution",
    "linear_xeb_from_samples",
]
