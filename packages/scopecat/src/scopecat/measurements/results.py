"""Result contracts, measurement schemas, and recording APIs."""

from __future__ import annotations

from scopecat.measurements.contracts import (
    validate_measurement_records_against_schema,
)
from scopecat.measurements.dataset import (
    Dataset,
    ExperimentResultPoint,
    ExperimentResultView,
    NativeAvailableValue,
    PointMask,
    StoredExperimentResultPoint,
    StoredExperimentResultView,
    Variable,
)
from scopecat.measurements.interop import (
    MeasurementDataProjection,
    PandasDTypeBackend,
    ProjectionDiagnostics,
    ProjectionField,
    ProjectionLayout,
    ProjectionSchema,
    ProjectionSpec,
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
    MeasurementResultContract,
    MeasurementResultField,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
    MeasurementValue,
    MeasurementVariable,
)

__all__ = [
    "Dataset",
    "ExperimentResultPoint",
    "ExperimentResultView",
    "InstrumentAcquisitionEvidence",
    "MeasurementArray",
    "MeasurementDType",
    "MeasurementDataProjection",
    "MeasurementDataset",
    "MeasurementDatasetSchema",
    "MeasurementDimension",
    "MeasurementPointCloudPointDomain",
    "MeasurementPointDomain",
    "MeasurementPointDomainAxis",
    "MeasurementPointDomainColumn",
    "MeasurementProductGridPointDomain",
    "MeasurementRecord",
    "MeasurementResultContract",
    "MeasurementResultField",
    "MeasurementScalar",
    "MeasurementUnavailable",
    "MeasurementUnavailableReason",
    "MeasurementValue",
    "MeasurementVariable",
    "MeasurementVariableRole",
    "NativeAvailableValue",
    "PandasDTypeBackend",
    "PointMask",
    "ProjectionDiagnostics",
    "ProjectionField",
    "ProjectionLayout",
    "ProjectionSchema",
    "ProjectionSpec",
    "RecordRef",
    "StoredExperimentResultPoint",
    "StoredExperimentResultView",
    "Trace",
    "Variable",
    "validate_measurement_records_against_schema",
]
