# ruff: noqa: F401
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Notebook-first public workflow facade.

The facade is intentionally lazy: importing an internal Scopecat module does
not construct the authoring, compiler, session, and storage dependency graph.
"""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.api.analysis import (
        Analysis,
        AnalysisContext,
        analysis_step,
    )
    from scopecat.api.lab import LabClient
    from scopecat.api.run import RunHandle
    from scopecat.authoring import (
        BoolType,
        Compute,
        ComputeInput,
        DomainProgramDef,
        EntityType,
        ExperimentBody,
        ExperimentInvocation,
        ExperimentModule,
        ExperimentTemplate,
        FloatType,
        Input,
        IntType,
        MeasurementTransform,
        ModuleBuilder,
        ModuleInvocation,
        ModuleOutputs,
        ParameterKeyInput,
        PayloadType,
        ProductOutputs,
        ProductRef,
        QuantityType,
        RecordField,
        RecordType,
        RuntimeInput,
        ScalarType,
        ScratchDefinition,
        SeriesType,
        StringType,
        TableColumn,
        TableType,
        ValueRef,
        ValueType,
        compute,
        coordinate,
        domain_execution,
        domain_program,
        entity_axis,
        experiment,
        input_ref,
        measurement_transform,
        module,
        module_body,
        parameter,
        parameter_lookup,
        product_axis,
        record_alias,
        record_product,
        scratch,
        template,
    )
    from scopecat.authoring import (
        input as input,
    )
    from scopecat.authoring.scans import (
        Scan,
        axis,
        cartesian,
        param_axis,
    )
    from scopecat.config.candidates import CandidateConfig
    from scopecat.config.drafts import ConfigDraft
    from scopecat.config.parameters import (
        delete_parameter_rows,
        insert_parameter_rows,
        replace_scalar_parameter,
        replace_series_parameter,
        replace_table_parameter,
        update_parameter_rows,
    )
    from scopecat.kernel.entity import (
        EntityRef,
        entity_ref,
    )
    from scopecat.kernel.quantity import Quantity
    from scopecat.planning.preview_models import ExperimentPreview
    from scopecat.planning.system import ExperimentSystem
    from scopecat.project import Project, open_project

_EXPORTS: dict[str, tuple[str, str]] = {
    "BoolType": ("scopecat.authoring", "BoolType"),
    "Compute": ("scopecat.authoring", "Compute"),
    "ComputeInput": ("scopecat.authoring", "ComputeInput"),
    "ConfigDraft": ("scopecat.config.drafts", "ConfigDraft"),
    "DomainProgramDef": ("scopecat.authoring", "DomainProgramDef"),
    "EntityType": ("scopecat.authoring", "EntityType"),
    "ExperimentBody": ("scopecat.authoring", "ExperimentBody"),
    "ExperimentInvocation": ("scopecat.authoring", "ExperimentInvocation"),
    "ExperimentModule": ("scopecat.authoring", "ExperimentModule"),
    "ExperimentTemplate": ("scopecat.authoring", "ExperimentTemplate"),
    "FloatType": ("scopecat.authoring", "FloatType"),
    "Input": ("scopecat.authoring", "Input"),
    "IntType": ("scopecat.authoring", "IntType"),
    "LabClient": ("scopecat.api.lab", "LabClient"),
    "MeasurementTransform": ("scopecat.authoring", "MeasurementTransform"),
    "ModuleBuilder": ("scopecat.authoring", "ModuleBuilder"),
    "ModuleInvocation": ("scopecat.authoring", "ModuleInvocation"),
    "ModuleOutputs": ("scopecat.authoring", "ModuleOutputs"),
    "ParameterKeyInput": ("scopecat.authoring", "ParameterKeyInput"),
    "PayloadType": ("scopecat.authoring", "PayloadType"),
    "ProductOutputs": ("scopecat.authoring", "ProductOutputs"),
    "ProductRef": ("scopecat.authoring", "ProductRef"),
    "QuantityType": ("scopecat.authoring", "QuantityType"),
    "RecordField": ("scopecat.authoring", "RecordField"),
    "RecordType": ("scopecat.authoring", "RecordType"),
    "RuntimeInput": ("scopecat.authoring", "RuntimeInput"),
    "ScratchDefinition": ("scopecat.authoring", "ScratchDefinition"),
    "ScalarType": ("scopecat.authoring", "ScalarType"),
    "SeriesType": ("scopecat.authoring", "SeriesType"),
    "StringType": ("scopecat.authoring", "StringType"),
    "TableColumn": ("scopecat.authoring", "TableColumn"),
    "TableType": ("scopecat.authoring", "TableType"),
    "ValueRef": ("scopecat.authoring", "ValueRef"),
    "ValueType": ("scopecat.authoring", "ValueType"),
    "compute": ("scopecat.authoring", "compute"),
    "coordinate": ("scopecat.authoring", "coordinate"),
    "domain_execution": ("scopecat.authoring", "domain_execution"),
    "domain_program": ("scopecat.authoring", "domain_program"),
    "entity_axis": ("scopecat.authoring", "entity_axis"),
    "experiment": ("scopecat.authoring", "experiment"),
    "input": ("scopecat.authoring", "input"),
    "input_ref": ("scopecat.authoring", "input_ref"),
    "measurement_transform": ("scopecat.authoring", "measurement_transform"),
    "module": ("scopecat.authoring", "module"),
    "module_body": ("scopecat.authoring", "module_body"),
    "parameter": ("scopecat.authoring", "parameter"),
    "parameter_lookup": ("scopecat.authoring", "parameter_lookup"),
    "record_alias": ("scopecat.authoring", "record_alias"),
    "product_axis": ("scopecat.authoring", "product_axis"),
    "record_product": ("scopecat.authoring", "record_product"),
    "scratch": ("scopecat.authoring", "scratch"),
    "template": ("scopecat.authoring", "template"),
    "Scan": ("scopecat.authoring.scans", "Scan"),
    "axis": ("scopecat.authoring.scans", "axis"),
    "cartesian": ("scopecat.authoring.scans", "cartesian"),
    "param_axis": ("scopecat.authoring.scans", "param_axis"),
    "ExperimentSystem": ("scopecat.planning.system", "ExperimentSystem"),
    "Project": ("scopecat.project", "Project"),
    "EntityRef": ("scopecat.kernel.entity", "EntityRef"),
    "entity_ref": ("scopecat.kernel.entity", "entity_ref"),
    "delete_parameter_rows": ("scopecat.config.parameters", "delete_parameter_rows"),
    "insert_parameter_rows": ("scopecat.config.parameters", "insert_parameter_rows"),
    "replace_scalar_parameter": (
        "scopecat.config.parameters",
        "replace_scalar_parameter",
    ),
    "replace_series_parameter": (
        "scopecat.config.parameters",
        "replace_series_parameter",
    ),
    "replace_table_parameter": (
        "scopecat.config.parameters",
        "replace_table_parameter",
    ),
    "update_parameter_rows": ("scopecat.config.parameters", "update_parameter_rows"),
    "ExperimentPreview": ("scopecat.planning.preview_models", "ExperimentPreview"),
    "Analysis": ("scopecat.api.analysis", "Analysis"),
    "AnalysisContext": ("scopecat.api.analysis", "AnalysisContext"),
    "CandidateConfig": ("scopecat.config.candidates", "CandidateConfig"),
    "Quantity": ("scopecat.kernel.quantity", "Quantity"),
    "RunHandle": ("scopecat.api.run", "RunHandle"),
    "open_project": ("scopecat.project", "open_project"),
    "analysis_step": ("scopecat.api.analysis", "analysis_step"),
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
