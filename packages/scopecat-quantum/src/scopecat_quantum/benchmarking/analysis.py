"""Numerical reference analysis for RB decay and linear XEB fidelity."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
from scipy.optimize import curve_fit  # pyright: ignore[reportUnknownVariableType]

type _FloatVector = np.ndarray[tuple[int], np.dtype[np.float64]]


def _rb_decay_model(
    coordinates: _FloatVector,
    amplitude: float,
    decay: float,
    offset: float,
) -> _FloatVector:
    return cast(
        "_FloatVector",
        amplitude * np.power(decay, coordinates) + offset,
    )


def _xeb_decay_model(
    coordinates: _FloatVector,
    amplitude: float,
    decay: float,
) -> _FloatVector:
    return cast("_FloatVector", amplitude * np.power(decay, coordinates))


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


def fit_rb_decay(
    lengths: Sequence[int],
    survival_probabilities: Sequence[float],
    *,
    dimension: int = 2,
    weights: Sequence[float] | None = None,
) -> RbDecayFit:
    """Fit the conventional RB survival curve with bounded SciPy optimization."""

    if dimension < 2:
        raise ValueError("RB Hilbert dimension must be at least two")
    x, y, selected_weights = _observations(
        lengths,
        survival_probabilities,
        weights,
    )
    if max(y) == min(y):
        raise ValueError("RB decay is not identifiable from constant observations")
    coordinates = np.asarray(x, dtype=np.float64)
    observations = np.asarray(y, dtype=np.float64)
    short_index = min(range(len(x)), key=x.__getitem__)
    long_index = max(range(len(x)), key=x.__getitem__)
    initial_offset = y[long_index]
    initial_amplitude = y[short_index] - initial_offset
    if initial_amplitude == 0.0:
        initial_amplitude = max(y) - min(y)
    parameters = cast(
        "_FloatVector",
        curve_fit(
            _rb_decay_model,
            coordinates,
            observations,
            p0=(initial_amplitude, 0.95, initial_offset),
            bounds=((-np.inf, 0.0, -np.inf), (np.inf, 1.0, np.inf)),
            sigma=1.0 / np.sqrt(np.asarray(selected_weights, dtype=np.float64)),
            ftol=1.0e-14,
            gtol=1.0e-14,
            xtol=1.0e-14,
            max_nfev=10_000,
        )[0],
    )
    amplitude, decay, offset = (float(value) for value in parameters)
    squared_error = math.fsum(
        weight * (observed - (amplitude * decay**length + offset)) ** 2
        for length, observed, weight in zip(x, y, selected_weights, strict=True)
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


def fit_xeb_decay(
    cycles: Sequence[int],
    fidelities: Sequence[float],
    *,
    weights: Sequence[float] | None = None,
) -> XebDecayFit:
    """Fit a zero-offset exponential decay to XEB fidelity versus cycle count."""

    x, y, selected_weights = _observations(cycles, fidelities, weights)
    if not any(y):
        raise ValueError("XEB decay is not identifiable from zero observations")
    coordinates = np.asarray(x, dtype=np.float64)
    observations = np.asarray(y, dtype=np.float64)
    short_index = min(range(len(x)), key=x.__getitem__)
    initial_decay = 0.95
    initial_amplitude = y[short_index] / initial_decay ** x[short_index]
    parameters = cast(
        "_FloatVector",
        curve_fit(
            _xeb_decay_model,
            coordinates,
            observations,
            p0=(initial_amplitude, initial_decay),
            bounds=((-np.inf, 0.0), (np.inf, 1.0)),
            sigma=1.0 / np.sqrt(np.asarray(selected_weights, dtype=np.float64)),
            ftol=1.0e-14,
            gtol=1.0e-14,
            xtol=1.0e-14,
            max_nfev=10_000,
        )[0],
    )
    amplitude, decay = (float(value) for value in parameters)
    squared_error = math.fsum(
        weight * (observed - amplitude * decay**cycle) ** 2
        for cycle, observed, weight in zip(x, y, selected_weights, strict=True)
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
