"""Adapters from recorded Scopecat/Xarray datasets to benchmark analysis."""

from __future__ import annotations

from collections.abc import Sequence
from typing import cast

import numpy as np
import xarray as xr
from scopecat.kernel.entity import EntityRef
from scopecat.measurements.dataset import Dataset

from .analysis import ParallelRbSeedAnalysis, analyze_parallel_rb_seeds


def analyze_parallel_rb_dataset(
    dataset: Dataset | xr.Dataset,
    *,
    length_variable: str = "length",
    survival_variable: str = "probability_0",
    entity_dimension: str = "entity",
    entity_ids: Sequence[str] | None = None,
    dimension: int = 2,
    confidence_level: float = 0.95,
    bootstrap_samples: int = 2_000,
    bootstrap_seed: int = 0,
) -> ParallelRbSeedAnalysis:
    """Analyze repeated-seed parallel RB directly from a recorded dataset."""

    source = dataset if isinstance(dataset, xr.Dataset) else dataset.to_xarray()
    if length_variable not in source:
        raise KeyError(f"RB dataset has no length variable {length_variable!r}")
    if survival_variable not in source:
        raise KeyError(f"RB dataset has no survival variable {survival_variable!r}")
    lengths = source[length_variable]
    survival = source[survival_variable]
    if lengths.dims != ("point",):
        raise ValueError("RB length variable must have exactly the point dimension")
    if survival.dims != ("point", entity_dimension):
        raise ValueError(
            "parallel RB survival variable must have point and entity dimensions"
        )
    selected_entity_ids = (
        tuple(entity_ids)
        if entity_ids is not None
        else _entity_coordinate_ids(survival, entity_dimension)
    )
    length_values = cast("list[object]", np.asarray(lengths.values).tolist())
    return analyze_parallel_rb_seeds(
        tuple(int(cast("int", value)) for value in length_values),
        survival.values,
        selected_entity_ids,
        dimension=dimension,
        confidence_level=confidence_level,
        bootstrap_samples=bootstrap_samples,
        bootstrap_seed=bootstrap_seed,
    )


def _entity_coordinate_ids(variable: xr.DataArray, dimension: str) -> tuple[str, ...]:
    if dimension not in variable.coords:  # pyright: ignore[reportUnknownMemberType]
        raise ValueError(
            "parallel RB dataset requires entity ids or an entity coordinate"
        )
    coordinate = cast(
        "xr.DataArray",
        variable.coords[dimension],
    )
    values = cast("list[object]", np.asarray(coordinate.values, dtype=object).tolist())
    return tuple(
        value.id if isinstance(value, EntityRef) else str(value) for value in values
    )


__all__ = ["analyze_parallel_rb_dataset"]
