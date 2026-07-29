# ruff: noqa: F401
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false
"""Instrument driver contracts."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from scopecat.kernel.state import StateValue
    from scopecat.records.config import (
        InstrumentBindingSpec,
        InstrumentConnection,
        TcpipSocketInstrumentConnection,
        VirtualInstrumentConnection,
    )
    from scopecat.records.instrument import (
        CommandChannelBinding,
        InstrumentPropertyState,
        InstrumentReadback,
        InstrumentStateSnapshot,
    )
    from scopecat.sdk.instruments.backend import InstrumentBackend
    from scopecat.sdk.instruments.contracts import (
        AcquisitionAxisSize,
        AcquisitionAxisSpec,
        AcquisitionCaseSpec,
        AcquisitionPreconditionSpec,
        AcquisitionReadiness,
        AcquisitionReadinessIssue,
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
        FixedAcquisitionSpec,
        InstrumentConnectionContext,
        InstrumentDescription,
        InstrumentDriver,
        InstrumentOperationArgument,
        InstrumentProvider,
        InstrumentProviderContext,
        InstrumentProviderDescription,
        InstrumentStateAssignment,
        InstrumentStateCommand,
        InteractiveCollectIntent,
        InteractiveCollectResolution,
        InterfaceSpec,
        InvokeCommand,
        InvokeReceipt,
        OperationArgumentSpec,
        OperationSpec,
        PropertySpec,
        RejectedInteractiveCollect,
        ResolvedInteractiveCollect,
        StateCaseSpec,
        StateComparisonOperator,
        StateDiscriminatedAcquisitionSpec,
        StatePropertyRef,
        acquisition,
        acquisition_axis,
        acquisition_case,
        acquisition_precondition,
        acquisition_result,
        acquisition_results,
        bool_property,
        component,
        discriminated_state,
        enum_property,
        evaluate_acquisition_readiness,
        float_property,
        int_property,
        interface,
        operation,
        operation_argument,
        quantity_property,
        resolve_acquisition_dimensions,
        resolve_interactive_collect,
        state_case,
        state_discriminated_acquisition,
        string_property,
        validate_collect_command,
        validate_collect_plan,
        validate_collect_receipt,
        validate_invoke_command,
        validate_state_assignments,
        validate_state_command,
        validate_state_snapshot,
    )
    from scopecat.sdk.instruments.driver import (
        DriverApplyRequest,
        DriverCollectRequest,
        DriverCollectResult,
        DriverInvokeArgument,
        DriverInvokeRequest,
        DriverOperationArgument,
        DriverPayloadArgument,
        DriverPropertyWrite,
        DriverScalarValue,
    )
    from scopecat.sdk.instruments.members import (
        AcquisitionRef,
        AcquisitionResultRef,
        ComponentRef,
        InterfaceRef,
        OperationArgumentRef,
        OperationRef,
        PropertyRef,
    )


_EXPORTS: dict[str, tuple[str, str]] = {
    "AcquisitionPreconditionSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionPreconditionSpec",
    ),
    "AcquisitionReadiness": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionReadiness",
    ),
    "AcquisitionReadinessIssue": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionReadinessIssue",
    ),
    "AcquisitionRef": (
        "scopecat.sdk.instruments.members",
        "AcquisitionRef",
    ),
    "AcquisitionResultRef": (
        "scopecat.sdk.instruments.members",
        "AcquisitionResultRef",
    ),
    "AcquisitionCaseSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionCaseSpec",
    ),
    "AcquisitionAxisSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionAxisSpec",
    ),
    "AcquisitionAxisSize": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionAxisSize",
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
    "ComponentRef": (
        "scopecat.sdk.instruments.members",
        "ComponentRef",
    ),
    "ComponentSpec": ("scopecat.sdk.instruments.contracts", "ComponentSpec"),
    "DiscriminatedStateSpec": (
        "scopecat.sdk.instruments.contracts",
        "DiscriminatedStateSpec",
    ),
    "DriverFault": ("scopecat.sdk.instruments.contracts", "DriverFault"),
    "FixedAcquisitionSpec": (
        "scopecat.sdk.instruments.contracts",
        "FixedAcquisitionSpec",
    ),
    "DriverApplyRequest": (
        "scopecat.sdk.instruments.driver",
        "DriverApplyRequest",
    ),
    "DriverCollectRequest": (
        "scopecat.sdk.instruments.driver",
        "DriverCollectRequest",
    ),
    "DriverCollectResult": (
        "scopecat.sdk.instruments.driver",
        "DriverCollectResult",
    ),
    "DriverInvokeArgument": (
        "scopecat.sdk.instruments.driver",
        "DriverInvokeArgument",
    ),
    "DriverInvokeRequest": (
        "scopecat.sdk.instruments.driver",
        "DriverInvokeRequest",
    ),
    "DriverOperationArgument": (
        "scopecat.sdk.instruments.driver",
        "DriverOperationArgument",
    ),
    "DriverPayloadArgument": (
        "scopecat.sdk.instruments.driver",
        "DriverPayloadArgument",
    ),
    "DriverPropertyWrite": (
        "scopecat.sdk.instruments.driver",
        "DriverPropertyWrite",
    ),
    "DriverScalarValue": (
        "scopecat.sdk.instruments.driver",
        "DriverScalarValue",
    ),
    "InstrumentConnectionContext": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentConnectionContext",
    ),
    "InstrumentBindingSpec": (
        "scopecat.records.config",
        "InstrumentBindingSpec",
    ),
    "InstrumentConnection": (
        "scopecat.records.config",
        "InstrumentConnection",
    ),
    "InterfaceRef": (
        "scopecat.sdk.instruments.members",
        "InterfaceRef",
    ),
    "InstrumentBackend": (
        "scopecat.sdk.instruments.backend",
        "InstrumentBackend",
    ),
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
    "InstrumentReadback": ("scopecat.records.instrument", "InstrumentReadback"),
    "InstrumentStateCommand": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentStateCommand",
    ),
    "InstrumentStateAssignment": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentStateAssignment",
    ),
    "InteractiveCollectIntent": (
        "scopecat.sdk.instruments.contracts",
        "InteractiveCollectIntent",
    ),
    "InteractiveCollectResolution": (
        "scopecat.sdk.instruments.contracts",
        "InteractiveCollectResolution",
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
    "OperationArgumentRef": (
        "scopecat.sdk.instruments.members",
        "OperationArgumentRef",
    ),
    "OperationRef": (
        "scopecat.sdk.instruments.members",
        "OperationRef",
    ),
    "OperationSpec": ("scopecat.sdk.instruments.contracts", "OperationSpec"),
    "PropertyRef": (
        "scopecat.sdk.instruments.members",
        "PropertyRef",
    ),
    "PropertySpec": ("scopecat.sdk.instruments.contracts", "PropertySpec"),
    "RejectedInteractiveCollect": (
        "scopecat.sdk.instruments.contracts",
        "RejectedInteractiveCollect",
    ),
    "ResolvedInteractiveCollect": (
        "scopecat.sdk.instruments.contracts",
        "ResolvedInteractiveCollect",
    ),
    "StateCaseSpec": ("scopecat.sdk.instruments.contracts", "StateCaseSpec"),
    "StateComparisonOperator": (
        "scopecat.sdk.instruments.contracts",
        "StateComparisonOperator",
    ),
    "StateDiscriminatedAcquisitionSpec": (
        "scopecat.sdk.instruments.contracts",
        "StateDiscriminatedAcquisitionSpec",
    ),
    "StatePropertyRef": (
        "scopecat.sdk.instruments.contracts",
        "StatePropertyRef",
    ),
    "acquisition": ("scopecat.sdk.instruments.contracts", "acquisition"),
    "acquisition_case": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_case",
    ),
    "acquisition_precondition": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_precondition",
    ),
    "acquisition_axis": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_axis",
    ),
    "acquisition_result": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_result",
    ),
    "acquisition_results": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_results",
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
    "resolve_acquisition_dimensions": (
        "scopecat.sdk.instruments.contracts",
        "resolve_acquisition_dimensions",
    ),
    "resolve_interactive_collect": (
        "scopecat.sdk.instruments.contracts",
        "resolve_interactive_collect",
    ),
    "state_case": ("scopecat.sdk.instruments.contracts", "state_case"),
    "state_discriminated_acquisition": (
        "scopecat.sdk.instruments.contracts",
        "state_discriminated_acquisition",
    ),
    "evaluate_acquisition_readiness": (
        "scopecat.sdk.instruments.contracts",
        "evaluate_acquisition_readiness",
    ),
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
    "validate_collect_plan": (
        "scopecat.sdk.instruments.contracts",
        "validate_collect_plan",
    ),
    "validate_collect_receipt": (
        "scopecat.sdk.instruments.contracts",
        "validate_collect_receipt",
    ),
    "validate_invoke_command": (
        "scopecat.sdk.instruments.contracts",
        "validate_invoke_command",
    ),
    "StateValue": ("scopecat.kernel.state", "StateValue"),
    "TcpipSocketInstrumentConnection": (
        "scopecat.records.config",
        "TcpipSocketInstrumentConnection",
    ),
    "VirtualInstrumentConnection": (
        "scopecat.records.config",
        "VirtualInstrumentConnection",
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


__all__ = sorted(_EXPORTS)
