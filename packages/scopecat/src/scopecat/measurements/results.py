"""Result contracts, measurement schemas, and recording APIs."""

from __future__ import annotations

from scopecat.measurements.contracts import (
    validate_measurement_records_against_schema,
)
from scopecat.records.measurement import (
    ComplexComponents,
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementDType,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementValue,
    MeasurementVariable,
    MeasurementVariableRole,
)

__all__ = [
    "ComplexComponents",
    "MeasurementArray",
    "MeasurementDType",
    "MeasurementDataset",
    "MeasurementDatasetSchema",
    "MeasurementDimension",
    "MeasurementRecord",
    "MeasurementScalar",
    "MeasurementValue",
    "MeasurementVariable",
    "MeasurementVariableRole",
    "validate_measurement_records_against_schema",
]
