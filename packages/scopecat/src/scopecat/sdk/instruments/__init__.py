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
        AcquisitionResultSpec,
        AcquisitionSpec,
        ApplyReceipt,
        CollectReceipt,
        ComponentSpec,
        DiscriminatedState,
        DriverFault,
        FixedAcquisitionSpec,
        InstrumentConnectionContext,
        InstrumentDescription,
        InstrumentDriver,
        InstrumentProvider,
        InstrumentProviderContext,
        InstrumentProviderDescription,
        InterfaceSpec,
        InvokeReceipt,
        OperationArgumentSpec,
        OperationSpec,
        PropertySpec,
        StateCase,
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
        float_property,
        int_property,
        interface,
        operation,
        operation_argument,
        quantity_property,
        state_case,
        state_discriminated_acquisition,
        string_property,
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
    from scopecat.sdk.instruments.scpi import (
        ScpiIdentity,
        ScpiProtocolError,
        ScpiTransport,
        TransportError,
        format_number,
        parse_bool,
        parse_float,
        parse_identity,
        parse_int,
        query_bool,
        query_csv_floats,
        query_float,
        query_identity,
        query_int,
        query_string,
        query_text,
    )


_EXPORTS: dict[str, tuple[str, str]] = {
    "AcquisitionAxisSize": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionAxisSize",
    ),
    "AcquisitionAxisSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionAxisSpec",
    ),
    "AcquisitionCaseSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionCaseSpec",
    ),
    "AcquisitionPreconditionSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionPreconditionSpec",
    ),
    "AcquisitionRef": ("scopecat.sdk.instruments.members", "AcquisitionRef"),
    "AcquisitionResultRef": (
        "scopecat.sdk.instruments.members",
        "AcquisitionResultRef",
    ),
    "AcquisitionResultSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionResultSpec",
    ),
    "AcquisitionSpec": ("scopecat.sdk.instruments.contracts", "AcquisitionSpec"),
    "ApplyReceipt": ("scopecat.sdk.instruments.contracts", "ApplyReceipt"),
    "CollectReceipt": ("scopecat.sdk.instruments.contracts", "CollectReceipt"),
    "CommandChannelBinding": (
        "scopecat.records.instrument",
        "CommandChannelBinding",
    ),
    "ComponentRef": ("scopecat.sdk.instruments.members", "ComponentRef"),
    "ComponentSpec": ("scopecat.sdk.instruments.contracts", "ComponentSpec"),
    "DiscriminatedState": (
        "scopecat.sdk.instruments.contracts",
        "DiscriminatedState",
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
    "DriverFault": ("scopecat.sdk.instruments.contracts", "DriverFault"),
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
    "FixedAcquisitionSpec": (
        "scopecat.sdk.instruments.contracts",
        "FixedAcquisitionSpec",
    ),
    "InstrumentBackend": ("scopecat.sdk.instruments.backend", "InstrumentBackend"),
    "InstrumentBindingSpec": (
        "scopecat.records.config",
        "InstrumentBindingSpec",
    ),
    "InstrumentConnection": ("scopecat.records.config", "InstrumentConnection"),
    "InstrumentConnectionContext": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentConnectionContext",
    ),
    "InstrumentDescription": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentDescription",
    ),
    "InstrumentDriver": ("scopecat.sdk.instruments.contracts", "InstrumentDriver"),
    "InstrumentPropertyState": (
        "scopecat.records.instrument",
        "InstrumentPropertyState",
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
    "InstrumentStateSnapshot": (
        "scopecat.records.instrument",
        "InstrumentStateSnapshot",
    ),
    "InterfaceRef": ("scopecat.sdk.instruments.members", "InterfaceRef"),
    "InterfaceSpec": ("scopecat.sdk.instruments.contracts", "InterfaceSpec"),
    "InvokeReceipt": ("scopecat.sdk.instruments.contracts", "InvokeReceipt"),
    "OperationArgumentRef": (
        "scopecat.sdk.instruments.members",
        "OperationArgumentRef",
    ),
    "OperationArgumentSpec": (
        "scopecat.sdk.instruments.contracts",
        "OperationArgumentSpec",
    ),
    "OperationRef": ("scopecat.sdk.instruments.members", "OperationRef"),
    "OperationSpec": ("scopecat.sdk.instruments.contracts", "OperationSpec"),
    "PropertyRef": ("scopecat.sdk.instruments.members", "PropertyRef"),
    "PropertySpec": ("scopecat.sdk.instruments.contracts", "PropertySpec"),
    "ScpiIdentity": ("scopecat.sdk.instruments.scpi", "ScpiIdentity"),
    "ScpiProtocolError": ("scopecat.sdk.instruments.scpi", "ScpiProtocolError"),
    "ScpiTransport": ("scopecat.sdk.instruments.scpi", "ScpiTransport"),
    "StateCase": ("scopecat.sdk.instruments.contracts", "StateCase"),
    "StateDiscriminatedAcquisitionSpec": (
        "scopecat.sdk.instruments.contracts",
        "StateDiscriminatedAcquisitionSpec",
    ),
    "StatePropertyRef": (
        "scopecat.sdk.instruments.contracts",
        "StatePropertyRef",
    ),
    "StateValue": ("scopecat.kernel.state", "StateValue"),
    "TcpipSocketInstrumentConnection": (
        "scopecat.records.config",
        "TcpipSocketInstrumentConnection",
    ),
    "TransportError": ("scopecat.sdk.instruments.scpi", "TransportError"),
    "VirtualInstrumentConnection": (
        "scopecat.records.config",
        "VirtualInstrumentConnection",
    ),
    "acquisition": ("scopecat.sdk.instruments.contracts", "acquisition"),
    "acquisition_axis": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_axis",
    ),
    "acquisition_case": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_case",
    ),
    "acquisition_precondition": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_precondition",
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
    "format_number": ("scopecat.sdk.instruments.scpi", "format_number"),
    "int_property": ("scopecat.sdk.instruments.contracts", "int_property"),
    "interface": ("scopecat.sdk.instruments.contracts", "interface"),
    "operation": ("scopecat.sdk.instruments.contracts", "operation"),
    "operation_argument": (
        "scopecat.sdk.instruments.contracts",
        "operation_argument",
    ),
    "parse_bool": ("scopecat.sdk.instruments.scpi", "parse_bool"),
    "parse_float": ("scopecat.sdk.instruments.scpi", "parse_float"),
    "parse_identity": ("scopecat.sdk.instruments.scpi", "parse_identity"),
    "parse_int": ("scopecat.sdk.instruments.scpi", "parse_int"),
    "quantity_property": (
        "scopecat.sdk.instruments.contracts",
        "quantity_property",
    ),
    "query_bool": ("scopecat.sdk.instruments.scpi", "query_bool"),
    "query_csv_floats": (
        "scopecat.sdk.instruments.scpi",
        "query_csv_floats",
    ),
    "query_float": ("scopecat.sdk.instruments.scpi", "query_float"),
    "query_identity": ("scopecat.sdk.instruments.scpi", "query_identity"),
    "query_int": ("scopecat.sdk.instruments.scpi", "query_int"),
    "query_string": ("scopecat.sdk.instruments.scpi", "query_string"),
    "query_text": ("scopecat.sdk.instruments.scpi", "query_text"),
    "state_case": ("scopecat.sdk.instruments.contracts", "state_case"),
    "state_discriminated_acquisition": (
        "scopecat.sdk.instruments.contracts",
        "state_discriminated_acquisition",
    ),
    "string_property": ("scopecat.sdk.instruments.contracts", "string_property"),
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
