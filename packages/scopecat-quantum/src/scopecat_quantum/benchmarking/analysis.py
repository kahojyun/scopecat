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


@dataclass(frozen=True, slots=True)
class SeedAggregate:
    """Seed-reduced observations with deterministic bootstrap intervals."""

    coordinates: tuple[int, ...]
    mean: np.ndarray
    standard_error: np.ndarray
    confidence_lower: np.ndarray
    confidence_upper: np.ndarray
    sample_counts: tuple[int, ...]
    confidence_level: float


@dataclass(frozen=True, slots=True)
class ParallelRbSeedAnalysis:
    """Seed aggregation and entity-addressed RB fits from the same values."""

    aggregate: SeedAggregate
    fits: tuple[EntityRbDecayFit, ...]


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


def aggregate_seed_observations(
    coordinates: Sequence[int],
    observations: object,
    *,
    confidence_level: float = 0.95,
    bootstrap_samples: int = 2_000,
    bootstrap_seed: int = 0,
) -> SeedAggregate:
    """Aggregate repeated seeds at each coordinate without positional assumptions."""

    coordinate_values = tuple(coordinates)
    values = np.asarray(observations, dtype=np.float64)
    if values.ndim < 1 or values.shape[0] != len(coordinate_values):
        raise ValueError("seed observations must have one leading point axis")
    if not coordinate_values:
        raise ValueError("seed aggregation requires at least one observation")
    if any(coordinate < 0 for coordinate in coordinate_values):
        raise ValueError("seed coordinates must be non-negative integers")
    if not np.isfinite(values).all():
        raise ValueError("seed observations must be finite")
    if not 0.0 < confidence_level < 1.0:
        raise ValueError("confidence level must be in (0, 1)")
    if bootstrap_samples <= 0:
        raise ValueError("bootstrap sample count must be positive")

    selected_coordinates = tuple(sorted(set(coordinate_values)))
    rng = np.random.default_rng(bootstrap_seed)
    means: list[np.ndarray] = []
    standard_errors: list[np.ndarray] = []
    lowers: list[np.ndarray] = []
    uppers: list[np.ndarray] = []
    sample_counts: list[int] = []
    tail = (1.0 - confidence_level) / 2.0
    for coordinate in selected_coordinates:
        indices = tuple(
            index
            for index, candidate in enumerate(coordinate_values)
            if candidate == coordinate
        )
        samples = values[np.asarray(indices, dtype=np.int64)]
        sample_count = len(indices)
        mean = np.mean(samples, axis=0)
        standard_error = (
            np.zeros_like(mean)
            if sample_count == 1
            else np.std(samples, axis=0, ddof=1) / math.sqrt(sample_count)
        )
        if sample_count == 1:
            lower = upper = mean
        else:
            resampled = samples[
                rng.integers(
                    0,
                    sample_count,
                    size=(bootstrap_samples, sample_count),
                )
            ]
            bootstrap_means = np.mean(resampled, axis=1)
            lower = np.quantile(bootstrap_means, tail, axis=0)
            upper = np.quantile(bootstrap_means, 1.0 - tail, axis=0)
        means.append(np.asarray(mean, dtype=np.float64))
        standard_errors.append(np.asarray(standard_error, dtype=np.float64))
        lowers.append(np.asarray(lower, dtype=np.float64))
        uppers.append(np.asarray(upper, dtype=np.float64))
        sample_counts.append(sample_count)
    return SeedAggregate(
        coordinates=selected_coordinates,
        mean=np.stack(means),
        standard_error=np.stack(standard_errors),
        confidence_lower=np.stack(lowers),
        confidence_upper=np.stack(uppers),
        sample_counts=tuple(sample_counts),
        confidence_level=confidence_level,
    )


def analyze_parallel_rb_seeds(
    lengths: Sequence[int],
    survival_probabilities: object,
    entity_ids: Sequence[str],
    *,
    dimension: int = 2,
    confidence_level: float = 0.95,
    bootstrap_samples: int = 2_000,
    bootstrap_seed: int = 0,
) -> ParallelRbSeedAnalysis:
    """Aggregate seed repetitions, then fit one decay per durable entity id."""

    aggregate = aggregate_seed_observations(
        lengths,
        survival_probabilities,
        confidence_level=confidence_level,
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
    )
    fits = fit_parallel_rb_decay(
        aggregate.coordinates,
        aggregate.mean,
        entity_ids,
        dimension=dimension,
    )
    return ParallelRbSeedAnalysis(aggregate=aggregate, fits=fits)


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
    "ParallelRbSeedAnalysis",
    "RbDecayFit",
    "SeedAggregate",
    "XebDecayFit",
    "aggregate_seed_observations",
    "analyze_parallel_rb_seeds",
    "fit_parallel_rb_decay",
    "fit_rb_decay",
    "fit_xeb_decay",
    "interleaved_rb_error",
    "linear_xeb_from_distribution",
    "linear_xeb_from_samples",
]
