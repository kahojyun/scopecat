# ruff: noqa: F401
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Instrument driver contracts."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.kernel.state import PayloadRef, StateValue
    from scopecat.records.instrument import (
        CommandChannelBinding,
        InstrumentPropertyState,
        InstrumentReadback,
        InstrumentStateSnapshot,
    )
    from scopecat.sdk.instruments.contracts import (
        AcquisitionAxisSpec,
        AcquisitionResultSpec,
        AcquisitionSpec,
        ApplyReceipt,
        CollectAxisRequest,
        CollectCommand,
        CollectReceipt,
        CollectResultRequest,
        ComponentSpec,
        DiscriminatedStateSpec,
        DriverFault,
        InstrumentDescription,
        InstrumentDriver,
        InstrumentOperationArgument,
        InstrumentProvider,
        InstrumentProviderContext,
        InstrumentProviderDescription,
        InstrumentProviderResult,
        InstrumentStateAssignment,
        InstrumentStateCommand,
        InterfaceSpec,
        InvokeCommand,
        InvokeReceipt,
        OperationArgumentSpec,
        OperationSpec,
        PropertySpec,
        StateCaseSpec,
        acquisition,
        acquisition_axis,
        acquisition_result,
        apply_state_command_to_snapshot,
        bool_property,
        component,
        discriminated_state,
        enum_property,
        float_property,
        int_property,
        interface,
        operation,
        operation_argument,
        quantity_property,
        state_case,
        string_property,
        validate_collect_command,
        validate_collect_receipt,
        validate_invoke_command,
        validate_state_assignments,
        validate_state_command,
        validate_state_snapshot,
    )


_EXPORTS: dict[str, tuple[str, str]] = {
    "AcquisitionAxisSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionAxisSpec",
    ),
    "AcquisitionResultSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionResultSpec",
    ),
    "AcquisitionSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionSpec",
    ),
    "ApplyReceipt": ("scopecat.sdk.instruments.contracts", "ApplyReceipt"),
    "CollectAxisRequest": ("scopecat.sdk.instruments.contracts", "CollectAxisRequest"),
    "CollectCommand": ("scopecat.sdk.instruments.contracts", "CollectCommand"),
    "CollectResultRequest": (
        "scopecat.sdk.instruments.contracts",
        "CollectResultRequest",
    ),
    "CollectReceipt": ("scopecat.sdk.instruments.contracts", "CollectReceipt"),
    "CommandChannelBinding": (
        "scopecat.records.instrument",
        "CommandChannelBinding",
    ),
    "ComponentSpec": ("scopecat.sdk.instruments.contracts", "ComponentSpec"),
    "DiscriminatedStateSpec": (
        "scopecat.sdk.instruments.contracts",
        "DiscriminatedStateSpec",
    ),
    "DriverFault": ("scopecat.sdk.instruments.contracts", "DriverFault"),
    "InterfaceSpec": ("scopecat.sdk.instruments.contracts", "InterfaceSpec"),
    "InstrumentDescription": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentDescription",
    ),
    "InstrumentDriver": ("scopecat.sdk.instruments.contracts", "InstrumentDriver"),
    "InstrumentOperationArgument": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentOperationArgument",
    ),
    "InstrumentProvider": ("scopecat.sdk.instruments.contracts", "InstrumentProvider"),
    "InstrumentProviderContext": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentProviderContext",
    ),
    "InstrumentProviderDescription": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentProviderDescription",
    ),
    "InstrumentProviderResult": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentProviderResult",
    ),
    "InstrumentReadback": ("scopecat.records.instrument", "InstrumentReadback"),
    "InstrumentStateCommand": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentStateCommand",
    ),
    "InstrumentStateAssignment": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentStateAssignment",
    ),
    "InstrumentPropertyState": (
        "scopecat.records.instrument",
        "InstrumentPropertyState",
    ),
    "InstrumentStateSnapshot": (
        "scopecat.records.instrument",
        "InstrumentStateSnapshot",
    ),
    "InvokeCommand": ("scopecat.sdk.instruments.contracts", "InvokeCommand"),
    "InvokeReceipt": ("scopecat.sdk.instruments.contracts", "InvokeReceipt"),
    "OperationArgumentSpec": (
        "scopecat.sdk.instruments.contracts",
        "OperationArgumentSpec",
    ),
    "OperationSpec": ("scopecat.sdk.instruments.contracts", "OperationSpec"),
    "PropertySpec": ("scopecat.sdk.instruments.contracts", "PropertySpec"),
    "StateCaseSpec": ("scopecat.sdk.instruments.contracts", "StateCaseSpec"),
    "acquisition": ("scopecat.sdk.instruments.contracts", "acquisition"),
    "acquisition_axis": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_axis",
    ),
    "acquisition_result": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_result",
    ),
    "apply_state_command_to_snapshot": (
        "scopecat.sdk.instruments.contracts",
        "apply_state_command_to_snapshot",
    ),
    "bool_property": ("scopecat.sdk.instruments.contracts", "bool_property"),
    "component": ("scopecat.sdk.instruments.contracts", "component"),
    "discriminated_state": (
        "scopecat.sdk.instruments.contracts",
        "discriminated_state",
    ),
    "enum_property": ("scopecat.sdk.instruments.contracts", "enum_property"),
    "float_property": ("scopecat.sdk.instruments.contracts", "float_property"),
    "int_property": ("scopecat.sdk.instruments.contracts", "int_property"),
    "interface": ("scopecat.sdk.instruments.contracts", "interface"),
    "operation": ("scopecat.sdk.instruments.contracts", "operation"),
    "operation_argument": (
        "scopecat.sdk.instruments.contracts",
        "operation_argument",
    ),
    "quantity_property": (
        "scopecat.sdk.instruments.contracts",
        "quantity_property",
    ),
    "state_case": ("scopecat.sdk.instruments.contracts", "state_case"),
    "string_property": ("scopecat.sdk.instruments.contracts", "string_property"),
    "validate_state_command": (
        "scopecat.sdk.instruments.contracts",
        "validate_state_command",
    ),
    "validate_state_assignments": (
        "scopecat.sdk.instruments.contracts",
        "validate_state_assignments",
    ),
    "validate_state_snapshot": (
        "scopecat.sdk.instruments.contracts",
        "validate_state_snapshot",
    ),
    "validate_collect_command": (
        "scopecat.sdk.instruments.contracts",
        "validate_collect_command",
    ),
    "validate_collect_receipt": (
        "scopecat.sdk.instruments.contracts",
        "validate_collect_receipt",
    ),
    "validate_invoke_command": (
        "scopecat.sdk.instruments.contracts",
        "validate_invoke_command",
    ),
    "PayloadRef": ("scopecat.kernel.state", "PayloadRef"),
    "StateValue": ("scopecat.kernel.state", "StateValue"),
}


def __getattr__(name: str) -> object:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = cast("object", getattr(import_module(module_name), attribute_name))
    globals()[name] = value
    return value


__all__ = sorted(_EXPORTS)
