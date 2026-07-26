"""Result contracts, measurement schemas, and recording APIs."""

from __future__ import annotations

from scopecat.records.measurement import (
    ComplexQuantity,
    CoordinateValue,
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetRole,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementDType,
    MeasurementRecord,
    MeasurementValue,
    MeasurementVariable,
    MeasurementVariableRole,
    validate_measurement_records_against_schema,
)

__all__ = [
    "ComplexQuantity",
    "CoordinateValue",
    "MeasurementArray",
    "MeasurementDType",
    "MeasurementDataset",
    "MeasurementDatasetRole",
    "MeasurementDatasetSchema",
    "MeasurementDimension",
    "MeasurementRecord",
    "MeasurementValue",
    "MeasurementVariable",
    "MeasurementVariableRole",
    "validate_measurement_records_against_schema",
]
