"""Post-run analysis implementation with lazy native-library exports."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.analysis.datasets import (
        DERIVED_DATASET_CODEC,
        DERIVED_DATASET_MEDIA_TYPE,
        DerivedDataset,
        DerivedDatasetField,
        DerivedDatasetSchema,
        PandasDTypeBackend,
        derived_dataset,
    )

_DATASET_EXPORTS = frozenset(
    {
        "DERIVED_DATASET_CODEC",
        "DERIVED_DATASET_MEDIA_TYPE",
        "DerivedDataset",
        "DerivedDatasetField",
        "DerivedDatasetSchema",
        "PandasDTypeBackend",
        "derived_dataset",
    }
)


def __getattr__(name: str) -> object:
    if name not in _DATASET_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = cast("object", getattr(import_module("scopecat.analysis.datasets"), name))
    globals()[name] = value
    return value


__all__ = [
    "DERIVED_DATASET_CODEC",
    "DERIVED_DATASET_MEDIA_TYPE",
    "DerivedDataset",
    "DerivedDatasetField",
    "DerivedDatasetSchema",
    "PandasDTypeBackend",
    "derived_dataset",
]
