# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Lazy facade for result contracts, schemas, and native projections."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.measurements.contracts import (
        validate_measurement_records_against_schema,
    )
    from scopecat.measurements.dataset import (
        Dataset,
        ExperimentResultPoint,
        ExperimentResultView,
        LabeledMeasurementArray,
        MeasurementArrayLayout,
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
    from scopecat.program.measurement_types import (
        MeasurementDType,
        MeasurementVariableRole,
    )
    from scopecat.program.record_refs import RecordRef
    from scopecat.records.measurement import (
        EntityAcquisitionEvidence,
        InstrumentAcquisitionEvidence,
        MeasurementAcquisitionEvidenceCatalog,
        MeasurementAcquisitionValue,
        MeasurementArray,
        MeasurementArrayAvailability,
        MeasurementArrayUnavailableGroup,
        MeasurementDataset,
        MeasurementDatasetSchema,
        MeasurementDimension,
        MeasurementEntityAcquisition,
        MeasurementEntityIndex,
        MeasurementEntityProductMetadataOverride,
        MeasurementEntityProductSource,
        MeasurementPartitionedArray,
        MeasurementPointCloudPointDomain,
        MeasurementPointDomain,
        MeasurementPointDomainAxis,
        MeasurementPointDomainColumn,
        MeasurementPointDomainLinearSource,
        MeasurementPointDomainRangeSource,
        MeasurementPointDomainValuesSource,
        MeasurementProductGridPointDomain,
        MeasurementRecord,
        MeasurementResultContract,
        MeasurementResultField,
        MeasurementScalar,
        MeasurementSegmentedArray,
        MeasurementUnavailable,
        MeasurementUnavailableReason,
        MeasurementValue,
        MeasurementVariable,
        MeasurementVariableGroup,
    )

_CONTRACT_EXPORTS = ("validate_measurement_records_against_schema",)
_DATASET_EXPORTS = (
    "Dataset",
    "ExperimentResultPoint",
    "ExperimentResultView",
    "LabeledMeasurementArray",
    "MeasurementArrayLayout",
    "NativeAvailableValue",
    "PointMask",
    "StoredExperimentResultPoint",
    "StoredExperimentResultView",
    "Variable",
)
_INTEROP_EXPORTS = (
    "MeasurementDataProjection",
    "PandasDTypeBackend",
    "ProjectionDiagnostics",
    "ProjectionField",
    "ProjectionLayout",
    "ProjectionSchema",
    "ProjectionSpec",
)
_MEASUREMENT_TYPE_EXPORTS = (
    "MeasurementDType",
    "MeasurementVariableRole",
)
_RECORD_EXPORTS = (
    "EntityAcquisitionEvidence",
    "InstrumentAcquisitionEvidence",
    "MeasurementAcquisitionEvidenceCatalog",
    "MeasurementAcquisitionValue",
    "MeasurementArray",
    "MeasurementArrayAvailability",
    "MeasurementArrayUnavailableGroup",
    "MeasurementPartitionedArray",
    "MeasurementDataset",
    "MeasurementDatasetSchema",
    "MeasurementDimension",
    "MeasurementEntityAcquisition",
    "MeasurementEntityIndex",
    "MeasurementEntityProductMetadataOverride",
    "MeasurementEntityProductSource",
    "MeasurementPointCloudPointDomain",
    "MeasurementPointDomain",
    "MeasurementPointDomainAxis",
    "MeasurementPointDomainColumn",
    "MeasurementPointDomainLinearSource",
    "MeasurementPointDomainRangeSource",
    "MeasurementPointDomainValuesSource",
    "MeasurementProductGridPointDomain",
    "MeasurementRecord",
    "MeasurementResultContract",
    "MeasurementResultField",
    "MeasurementScalar",
    "MeasurementSegmentedArray",
    "MeasurementUnavailable",
    "MeasurementUnavailableReason",
    "MeasurementValue",
    "MeasurementVariable",
    "MeasurementVariableGroup",
)
_EXPORTS = {
    **{name: ("scopecat.measurements.contracts", name) for name in _CONTRACT_EXPORTS},
    **{name: ("scopecat.measurements.dataset", name) for name in _DATASET_EXPORTS},
    **{name: ("scopecat.measurements.interop", name) for name in _INTEROP_EXPORTS},
    **{
        name: ("scopecat.program.measurement_types", name)
        for name in _MEASUREMENT_TYPE_EXPORTS
    },
    **{name: ("scopecat.records.measurement", name) for name in _RECORD_EXPORTS},
    "RecordRef": ("scopecat.program.record_refs", "RecordRef"),
    "Trace": ("scopecat.measurements.traces", "Trace"),
}


def __getattr__(name: str) -> object:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = cast("object", getattr(import_module(module_name), attribute_name))
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = [
    "Dataset",
    "EntityAcquisitionEvidence",
    "ExperimentResultPoint",
    "ExperimentResultView",
    "InstrumentAcquisitionEvidence",
    "LabeledMeasurementArray",
    "MeasurementAcquisitionEvidenceCatalog",
    "MeasurementAcquisitionValue",
    "MeasurementArray",
    "MeasurementArrayAvailability",
    "MeasurementArrayLayout",
    "MeasurementArrayUnavailableGroup",
    "MeasurementDType",
    "MeasurementDataProjection",
    "MeasurementDataset",
    "MeasurementDatasetSchema",
    "MeasurementDimension",
    "MeasurementEntityAcquisition",
    "MeasurementEntityIndex",
    "MeasurementEntityProductMetadataOverride",
    "MeasurementEntityProductSource",
    "MeasurementPartitionedArray",
    "MeasurementPointCloudPointDomain",
    "MeasurementPointDomain",
    "MeasurementPointDomainAxis",
    "MeasurementPointDomainColumn",
    "MeasurementPointDomainLinearSource",
    "MeasurementPointDomainRangeSource",
    "MeasurementPointDomainValuesSource",
    "MeasurementProductGridPointDomain",
    "MeasurementRecord",
    "MeasurementResultContract",
    "MeasurementResultField",
    "MeasurementScalar",
    "MeasurementSegmentedArray",
    "MeasurementUnavailable",
    "MeasurementUnavailableReason",
    "MeasurementValue",
    "MeasurementVariable",
    "MeasurementVariableGroup",
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
