"""Result contracts, measurement schemas, and recording APIs."""

from __future__ import annotations

from scopecat.measurements.contracts import (
    validate_measurement_records_against_schema,
)
from scopecat.measurements.dataset import Dataset, PointMask, Variable
from scopecat.measurements.traces import Trace
from scopecat.records.measurement import (
    ComplexComponents,
    InstrumentAcquisitionEvidence,
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
    MeasurementDType,
    MeasurementPointCloudPointDomain,
    MeasurementPointDomain,
    MeasurementPointDomainAxis,
    MeasurementPointDomainColumn,
    MeasurementProductGridPointDomain,
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
    "Dataset",
    "InstrumentAcquisitionEvidence",
    "MeasurementArray",
    "MeasurementDType",
    "MeasurementDataset",
    "MeasurementDatasetSchema",
    "MeasurementDimension",
    "MeasurementPointCloudPointDomain",
    "MeasurementPointDomain",
    "MeasurementPointDomainAxis",
    "MeasurementPointDomainColumn",
    "MeasurementProductGridPointDomain",
    "MeasurementRecord",
    "MeasurementScalar",
    "MeasurementUnavailable",
    "MeasurementUnavailableReason",
    "MeasurementValue",
    "MeasurementVariable",
    "MeasurementVariableRole",
    "PointMask",
    "Trace",
    "Variable",
    "validate_measurement_records_against_schema",
]
