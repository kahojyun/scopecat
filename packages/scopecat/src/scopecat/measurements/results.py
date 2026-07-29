"""Result contracts, measurement schemas, and recording APIs."""

from __future__ import annotations

from scopecat.measurements.contracts import (
    validate_measurement_records_against_schema,
)
from scopecat.measurements.traces import (
    Trace,
    TraceCoordinate,
    TraceSample,
    measurement_traces,
)
from scopecat.records.measurement import (
    ComplexComponents,
    InstrumentAcquisitionEvidence,
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementDType,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
    MeasurementValue,
    MeasurementVariable,
    MeasurementVariableRole,
)

__all__ = [
    "ComplexComponents",
    "InstrumentAcquisitionEvidence",
    "MeasurementArray",
    "MeasurementDType",
    "MeasurementDataset",
    "MeasurementDatasetSchema",
    "MeasurementDimension",
    "MeasurementRecord",
    "MeasurementScalar",
    "MeasurementUnavailable",
    "MeasurementUnavailableReason",
    "MeasurementValue",
    "MeasurementVariable",
    "MeasurementVariableRole",
    "Trace",
    "TraceCoordinate",
    "TraceSample",
    "measurement_traces",
    "validate_measurement_records_against_schema",
]
