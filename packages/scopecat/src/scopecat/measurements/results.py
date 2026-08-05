"""Result contracts, measurement schemas, and recording APIs."""

from __future__ import annotations

from scopecat.measurements.contracts import (
    validate_measurement_records_against_schema,
)
from scopecat.measurements.dataset import (
    Dataset,
    NativeAvailableValue,
    PointMask,
    Variable,
)
from scopecat.measurements.traces import Trace
from scopecat.program.measurement_types import MeasurementDType, MeasurementVariableRole
from scopecat.program.record_refs import RecordRef
from scopecat.records.measurement import (
    InstrumentAcquisitionEvidence,
    MeasurementArray,
    MeasurementDataset,
    MeasurementDatasetSchema,
    MeasurementDimension,
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
)

__all__ = [
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
    "NativeAvailableValue",
    "PointMask",
    "RecordRef",
    "Trace",
    "Variable",
    "validate_measurement_records_against_schema",
]
