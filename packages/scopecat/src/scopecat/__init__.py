# ruff: noqa: F401
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Experiment authoring facade with one notebook workflow entry point.

The root exports authoring tools and ``open_project``. Returned workflow
handles stay in their owner modules so the root does not become a second API
for every subsystem. Imports are lazy to keep the dependency graph cold.
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
        analysis_step,
    )
    from scopecat.authoring import (
        BoolType,
        ComputeInput,
        ConcreteEntityInput,
        DefinitionResource,
        DesiredState,
        EachEntity,
        EntityInput,
        EntityKey,
        EntitySelection,
        EntityType,
        ExperimentContext,
        ExperimentInvocation,
        ExperimentModule,
        ExperimentTemplate,
        FloatType,
        Input,
        IntType,
        MeasurementPostprocessor,
        ModuleContext,
        ModuleInvocation,
        ModuleOutputs,
        ModuleResource,
        ModuleResources,
        OneEntity,
        ParameterColumn,
        ParameterKeyInput,
        ParameterRow,
        ParameterTable,
        PayloadType,
        PerEntity,
        ProductOutputs,
        ProductRef,
        QuantityType,
        RuntimeInput,
        ScalarType,
        ScratchDefinition,
        StateBinding,
        StringType,
        TableColumn,
        TableType,
        ValueRef,
        ValueType,
        coordinate,
        each,
        entity_axis,
        entity_key,
        input_ref,
        measurement_postprocessor,
        module,
        one,
        parameter,
        parameter_column,
        parameter_lookup,
        product_axis,
        record_alias,
        record_coordinate,
        record_product,
        scratch,
        template,
    )
    from scopecat.authoring.scans import (
        Scan,
        axis,
        param_axis,
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
    "BoolType": ("scopecat.authoring", "BoolType"),
    "ComputeInput": ("scopecat.authoring", "ComputeInput"),
    "ConcreteEntityInput": ("scopecat.authoring", "ConcreteEntityInput"),
    "DefinitionResource": ("scopecat.authoring", "DefinitionResource"),
    "DesiredState": ("scopecat.authoring", "DesiredState"),
    "EachEntity": ("scopecat.authoring", "EachEntity"),
    "EntityInput": ("scopecat.authoring", "EntityInput"),
    "EntityKey": ("scopecat.authoring", "EntityKey"),
    "EntitySelection": ("scopecat.authoring", "EntitySelection"),
    "EntityType": ("scopecat.authoring", "EntityType"),
    "ExperimentContext": ("scopecat.authoring", "ExperimentContext"),
    "ExperimentInvocation": ("scopecat.authoring", "ExperimentInvocation"),
    "ExperimentModule": ("scopecat.authoring", "ExperimentModule"),
    "ExperimentTemplate": ("scopecat.authoring", "ExperimentTemplate"),
    "FloatType": ("scopecat.authoring", "FloatType"),
    "Input": ("scopecat.authoring", "Input"),
    "IntType": ("scopecat.authoring", "IntType"),
    "MeasurementPostprocessor": ("scopecat.authoring", "MeasurementPostprocessor"),
    "ModuleContext": ("scopecat.authoring", "ModuleContext"),
    "ModuleInvocation": ("scopecat.authoring", "ModuleInvocation"),
    "ModuleOutputs": ("scopecat.authoring", "ModuleOutputs"),
    "ModuleResource": ("scopecat.authoring", "ModuleResource"),
    "ModuleResources": ("scopecat.authoring", "ModuleResources"),
    "OneEntity": ("scopecat.authoring", "OneEntity"),
    "ParameterColumn": ("scopecat.authoring", "ParameterColumn"),
    "ParameterKeyInput": ("scopecat.authoring", "ParameterKeyInput"),
    "ParameterRow": ("scopecat.authoring", "ParameterRow"),
    "ParameterTable": ("scopecat.authoring", "ParameterTable"),
    "PayloadType": ("scopecat.authoring", "PayloadType"),
    "PerEntity": ("scopecat.authoring", "PerEntity"),
    "ProductOutputs": ("scopecat.authoring", "ProductOutputs"),
    "ProductRef": ("scopecat.authoring", "ProductRef"),
    "QuantityType": ("scopecat.authoring", "QuantityType"),
    "RuntimeInput": ("scopecat.authoring", "RuntimeInput"),
    "ScratchDefinition": ("scopecat.authoring", "ScratchDefinition"),
    "ScalarType": ("scopecat.authoring", "ScalarType"),
    "StringType": ("scopecat.authoring", "StringType"),
    "StateBinding": ("scopecat.authoring", "StateBinding"),
    "TableColumn": ("scopecat.authoring", "TableColumn"),
    "TableType": ("scopecat.authoring", "TableType"),
    "ValueRef": ("scopecat.authoring", "ValueRef"),
    "ValueType": ("scopecat.authoring", "ValueType"),
    "coordinate": ("scopecat.authoring", "coordinate"),
    "each": ("scopecat.authoring", "each"),
    "entity_axis": ("scopecat.authoring", "entity_axis"),
    "entity_key": ("scopecat.authoring", "entity_key"),
    "input_ref": ("scopecat.authoring", "input_ref"),
    "measurement_postprocessor": ("scopecat.authoring", "measurement_postprocessor"),
    "module": ("scopecat.authoring", "module"),
    "one": ("scopecat.authoring", "one"),
    "parameter": ("scopecat.authoring", "parameter"),
    "parameter_column": ("scopecat.authoring", "parameter_column"),
    "parameter_lookup": ("scopecat.authoring", "parameter_lookup"),
    "record_alias": ("scopecat.authoring", "record_alias"),
    "record_coordinate": ("scopecat.authoring", "record_coordinate"),
    "product_axis": ("scopecat.authoring", "product_axis"),
    "record_product": ("scopecat.authoring", "record_product"),
    "scratch": ("scopecat.authoring", "scratch"),
    "template": ("scopecat.authoring", "template"),
    "Scan": ("scopecat.authoring.scans", "Scan"),
    "axis": ("scopecat.authoring.scans", "axis"),
    "param_axis": ("scopecat.authoring.scans", "param_axis"),
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
