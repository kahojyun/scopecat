# ruff: noqa: F401
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""High-level experiment authoring facade with one notebook entry point.

The root exports authoring tools and ``open_project``. Returned workflow
handles stay in their owner modules so the root does not become a second API
for every subsystem. Program IR and generated-client implementation types are
imported from their owner modules by extensions instead of being re-exported
here. Imports are lazy to keep the dependency graph cold.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.analysis.datasets import (
        DerivedDataset,
        DerivedDatasetField,
        DerivedDatasetSchema,
        derived_dataset,
    )
    from scopecat.analysis.facts import AnalysisFactSchema
    from scopecat.api.analysis import (
        Analysis,
        AnalysisContext,
        AnalysisField,
        analysis_step,
    )
    from scopecat.api.instruments import (
        InstrumentClientFactory,
        InstrumentRef,
        TemporaryInstrumentRef,
        instrument,
        temporary_instrument,
    )
    from scopecat.api.published_analysis import (
        PublishedAnalysis,
        PublishedAnalysisArtifact,
    )
    from scopecat.authoring import (
        ANY_RESOURCE_ROLE,
        DEFAULT_RESOURCE_ROLE,
        ArrayDimension,
        ArrayType,
        Axis,
        BoolType,
        CapabilityResource,
        CoordinateRef,
        DataRef,
        EachEntity,
        EntityType,
        Experiment,
        ExperimentContext,
        ExperimentInvocation,
        ExperimentModule,
        FloatType,
        Input,
        IntType,
        ModuleContext,
        ModuleInvocation,
        OneEntity,
        ParameterAssignment,
        ParameterCell,
        ParameterField,
        ParameterRow,
        ParameterRowKey,
        ParameterScalar,
        ParameterSchema,
        PayloadType,
        PerEntity,
        ProductBundle,
        ProductRef,
        ProductValueSpec,
        QuantityType,
        RecordedProducts,
        RecordRef,
        ResourceRoleSelector,
        Result,
        ScalarType,
        StringType,
        Symbolic,
        TableColumn,
        TableType,
        ValueRef,
        ValueType,
        axis,
        capability_resource,
        constant,
        coordinate,
        each,
        ensure_state_targets,
        experiment,
        input_ref,
        module,
        one,
        parameter,
        parameter_catalog,
        parameter_field,
        parameter_lookup,
        parameter_schema,
        resource_role,
    )
    from scopecat.config.parameters import (
        delete_parameter_rows,
        insert_parameter_rows,
        replace_scalar_parameter,
        replace_table_parameter,
        update_parameter_rows,
    )
    from scopecat.kernel.entity import (
        EntityRef,
        entity_ref,
    )
    from scopecat.kernel.quantity import Quantity
    from scopecat.measurements.points import PointCandidate
    from scopecat.optimization import (
        AdaptivePointPlan,
        CompletedPointObservation,
        OptimizationComplete,
        PointOptimizer,
        PointOptimizerContext,
        PointProposalDecision,
        PointProposalLedger,
    )
    from scopecat.planning.system import ExperimentSystem
    from scopecat.project import open_project
    from scopecat.sdk.payloads import (
        PayloadCodec,
        PayloadCodecCatalog,
        PayloadCodecDescription,
        PayloadCodecRegistry,
    )

_EXPORTS: dict[str, tuple[str, str]] = {
    "ANY_RESOURCE_ROLE": ("scopecat.authoring", "ANY_RESOURCE_ROLE"),
    "ArrayDimension": ("scopecat.authoring", "ArrayDimension"),
    "ArrayType": ("scopecat.authoring", "ArrayType"),
    "Axis": ("scopecat.authoring", "Axis"),
    "BoolType": ("scopecat.authoring", "BoolType"),
    "CapabilityResource": ("scopecat.authoring", "CapabilityResource"),
    "CoordinateRef": ("scopecat.authoring", "CoordinateRef"),
    "DataRef": ("scopecat.authoring", "DataRef"),
    "DEFAULT_RESOURCE_ROLE": ("scopecat.authoring", "DEFAULT_RESOURCE_ROLE"),
    "DerivedDataset": ("scopecat.analysis.datasets", "DerivedDataset"),
    "DerivedDatasetField": (
        "scopecat.analysis.datasets",
        "DerivedDatasetField",
    ),
    "DerivedDatasetSchema": (
        "scopecat.analysis.datasets",
        "DerivedDatasetSchema",
    ),
    "EachEntity": ("scopecat.authoring", "EachEntity"),
    "EntityType": ("scopecat.authoring", "EntityType"),
    "Experiment": ("scopecat.authoring", "Experiment"),
    "ExperimentContext": ("scopecat.authoring", "ExperimentContext"),
    "ExperimentInvocation": ("scopecat.authoring", "ExperimentInvocation"),
    "ExperimentModule": ("scopecat.authoring", "ExperimentModule"),
    "FloatType": ("scopecat.authoring", "FloatType"),
    "Input": ("scopecat.authoring", "Input"),
    "IntType": ("scopecat.authoring", "IntType"),
    "ModuleContext": ("scopecat.authoring", "ModuleContext"),
    "ModuleInvocation": ("scopecat.authoring", "ModuleInvocation"),
    "OneEntity": ("scopecat.authoring", "OneEntity"),
    "ParameterAssignment": ("scopecat.authoring", "ParameterAssignment"),
    "ParameterCell": ("scopecat.authoring", "ParameterCell"),
    "ParameterField": ("scopecat.authoring", "ParameterField"),
    "ParameterRow": ("scopecat.authoring", "ParameterRow"),
    "ParameterRowKey": ("scopecat.authoring", "ParameterRowKey"),
    "ParameterScalar": ("scopecat.authoring", "ParameterScalar"),
    "ParameterSchema": ("scopecat.authoring", "ParameterSchema"),
    "PayloadType": ("scopecat.authoring", "PayloadType"),
    "PerEntity": ("scopecat.authoring", "PerEntity"),
    "ProductRef": ("scopecat.authoring", "ProductRef"),
    "ProductBundle": ("scopecat.authoring", "ProductBundle"),
    "ProductValueSpec": ("scopecat.authoring", "ProductValueSpec"),
    "QuantityType": ("scopecat.authoring", "QuantityType"),
    "RecordRef": ("scopecat.authoring", "RecordRef"),
    "RecordedProducts": ("scopecat.authoring", "RecordedProducts"),
    "Result": ("scopecat.authoring", "Result"),
    "ResourceRoleSelector": ("scopecat.authoring", "ResourceRoleSelector"),
    "ScalarType": ("scopecat.authoring", "ScalarType"),
    "StringType": ("scopecat.authoring", "StringType"),
    "Symbolic": ("scopecat.authoring", "Symbolic"),
    "TableColumn": ("scopecat.authoring", "TableColumn"),
    "TableType": ("scopecat.authoring", "TableType"),
    "ValueRef": ("scopecat.authoring", "ValueRef"),
    "ValueType": ("scopecat.authoring", "ValueType"),
    "coordinate": ("scopecat.authoring", "coordinate"),
    "capability_resource": ("scopecat.authoring", "capability_resource"),
    "constant": ("scopecat.authoring", "constant"),
    "each": ("scopecat.authoring", "each"),
    "ensure_state_targets": ("scopecat.authoring", "ensure_state_targets"),
    "experiment": ("scopecat.authoring", "experiment"),
    "input_ref": ("scopecat.authoring", "input_ref"),
    "module": ("scopecat.authoring", "module"),
    "one": ("scopecat.authoring", "one"),
    "parameter": ("scopecat.authoring", "parameter"),
    "parameter_catalog": ("scopecat.authoring", "parameter_catalog"),
    "parameter_field": ("scopecat.authoring", "parameter_field"),
    "parameter_lookup": ("scopecat.authoring", "parameter_lookup"),
    "parameter_schema": ("scopecat.authoring", "parameter_schema"),
    "resource_role": ("scopecat.authoring", "resource_role"),
    "axis": ("scopecat.authoring", "axis"),
    "ExperimentSystem": ("scopecat.planning.system", "ExperimentSystem"),
    "PayloadCodec": ("scopecat.sdk.payloads", "PayloadCodec"),
    "PayloadCodecCatalog": ("scopecat.sdk.payloads", "PayloadCodecCatalog"),
    "PayloadCodecDescription": (
        "scopecat.sdk.payloads",
        "PayloadCodecDescription",
    ),
    "PayloadCodecRegistry": ("scopecat.sdk.payloads", "PayloadCodecRegistry"),
    "EntityRef": ("scopecat.kernel.entity", "EntityRef"),
    "entity_ref": ("scopecat.kernel.entity", "entity_ref"),
    "delete_parameter_rows": ("scopecat.config.parameters", "delete_parameter_rows"),
    "derived_dataset": ("scopecat.analysis.datasets", "derived_dataset"),
    "insert_parameter_rows": ("scopecat.config.parameters", "insert_parameter_rows"),
    "replace_scalar_parameter": (
        "scopecat.config.parameters",
        "replace_scalar_parameter",
    ),
    "replace_table_parameter": (
        "scopecat.config.parameters",
        "replace_table_parameter",
    ),
    "update_parameter_rows": ("scopecat.config.parameters", "update_parameter_rows"),
    "Analysis": ("scopecat.api.analysis", "Analysis"),
    "AnalysisFactSchema": ("scopecat.analysis.facts", "AnalysisFactSchema"),
    "AnalysisContext": ("scopecat.api.analysis", "AnalysisContext"),
    "AnalysisField": ("scopecat.api.analysis", "AnalysisField"),
    "PublishedAnalysis": (
        "scopecat.api.published_analysis",
        "PublishedAnalysis",
    ),
    "PublishedAnalysisArtifact": (
        "scopecat.api.published_analysis",
        "PublishedAnalysisArtifact",
    ),
    "InstrumentClientFactory": (
        "scopecat.api.instruments",
        "InstrumentClientFactory",
    ),
    "InstrumentRef": ("scopecat.api.instruments", "InstrumentRef"),
    "TemporaryInstrumentRef": (
        "scopecat.api.instruments",
        "TemporaryInstrumentRef",
    ),
    "Quantity": ("scopecat.kernel.quantity", "Quantity"),
    "PointCandidate": ("scopecat.measurements.points", "PointCandidate"),
    "AdaptivePointPlan": ("scopecat.optimization", "AdaptivePointPlan"),
    "CompletedPointObservation": (
        "scopecat.optimization",
        "CompletedPointObservation",
    ),
    "OptimizationComplete": ("scopecat.optimization", "OptimizationComplete"),
    "PointOptimizer": ("scopecat.optimization", "PointOptimizer"),
    "PointOptimizerContext": (
        "scopecat.optimization",
        "PointOptimizerContext",
    ),
    "PointProposalDecision": (
        "scopecat.optimization",
        "PointProposalDecision",
    ),
    "PointProposalLedger": ("scopecat.optimization", "PointProposalLedger"),
    "open_project": ("scopecat.project", "open_project"),
    "analysis_step": ("scopecat.api.analysis", "analysis_step"),
    "instrument": ("scopecat.api.instruments", "instrument"),
    "temporary_instrument": (
        "scopecat.api.instruments",
        "temporary_instrument",
    ),
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


__all__ = sorted(_EXPORTS)
