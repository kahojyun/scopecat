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
    from scopecat.api._instruments import (
        InstrumentClientFactory,
        InstrumentRef,
        instrument,
    )
    from scopecat.api.analysis import (
        Analysis,
        AnalysisContext,
        AnalysisFigure,
        AnalysisFigureAxis,
        AnalysisFigureSeries,
        AnalysisTable,
        AnalysisTableCell,
        AnalysisTableColumn,
        AnalysisTableRow,
        analysis_step,
    )
    from scopecat.authoring import (
        Axis,
        BoolType,
        CoordinateRef,
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
        ProductRef,
        ProductValueSpec,
        QuantityType,
        RecordRef,
        ScalarType,
        StringType,
        Symbolic,
        TableColumn,
        TableType,
        ValueRef,
        ValueType,
        axis,
        coordinate,
        each,
        experiment,
        input_ref,
        module,
        one,
        parameter,
        parameter_catalog,
        parameter_field,
        parameter_lookup,
        parameter_schema,
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
    from scopecat.planning.system import ExperimentSystem
    from scopecat.project import open_project
    from scopecat.sdk.payloads import (
        PayloadCodec,
        PayloadCodecCatalog,
        PayloadCodecDescription,
        PayloadCodecRegistry,
    )

_EXPORTS: dict[str, tuple[str, str]] = {
    "Axis": ("scopecat.authoring", "Axis"),
    "BoolType": ("scopecat.authoring", "BoolType"),
    "CoordinateRef": ("scopecat.authoring", "CoordinateRef"),
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
    "ProductValueSpec": ("scopecat.authoring", "ProductValueSpec"),
    "QuantityType": ("scopecat.authoring", "QuantityType"),
    "RecordRef": ("scopecat.authoring", "RecordRef"),
    "ScalarType": ("scopecat.authoring", "ScalarType"),
    "StringType": ("scopecat.authoring", "StringType"),
    "Symbolic": ("scopecat.authoring", "Symbolic"),
    "TableColumn": ("scopecat.authoring", "TableColumn"),
    "TableType": ("scopecat.authoring", "TableType"),
    "ValueRef": ("scopecat.authoring", "ValueRef"),
    "ValueType": ("scopecat.authoring", "ValueType"),
    "coordinate": ("scopecat.authoring", "coordinate"),
    "each": ("scopecat.authoring", "each"),
    "experiment": ("scopecat.authoring", "experiment"),
    "input_ref": ("scopecat.authoring", "input_ref"),
    "module": ("scopecat.authoring", "module"),
    "one": ("scopecat.authoring", "one"),
    "parameter": ("scopecat.authoring", "parameter"),
    "parameter_catalog": ("scopecat.authoring", "parameter_catalog"),
    "parameter_field": ("scopecat.authoring", "parameter_field"),
    "parameter_lookup": ("scopecat.authoring", "parameter_lookup"),
    "parameter_schema": ("scopecat.authoring", "parameter_schema"),
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
    "AnalysisContext": ("scopecat.api.analysis", "AnalysisContext"),
    "AnalysisFigure": ("scopecat.api.analysis", "AnalysisFigure"),
    "AnalysisFigureAxis": ("scopecat.api.analysis", "AnalysisFigureAxis"),
    "AnalysisFigureSeries": ("scopecat.api.analysis", "AnalysisFigureSeries"),
    "AnalysisTable": ("scopecat.api.analysis", "AnalysisTable"),
    "AnalysisTableCell": ("scopecat.api.analysis", "AnalysisTableCell"),
    "AnalysisTableColumn": ("scopecat.api.analysis", "AnalysisTableColumn"),
    "AnalysisTableRow": ("scopecat.api.analysis", "AnalysisTableRow"),
    "InstrumentClientFactory": (
        "scopecat.api._instruments",
        "InstrumentClientFactory",
    ),
    "InstrumentRef": ("scopecat.api._instruments", "InstrumentRef"),
    "Quantity": ("scopecat.kernel.quantity", "Quantity"),
    "open_project": ("scopecat.project", "open_project"),
    "analysis_step": ("scopecat.api.analysis", "analysis_step"),
    "instrument": ("scopecat.api._instruments", "instrument"),
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
