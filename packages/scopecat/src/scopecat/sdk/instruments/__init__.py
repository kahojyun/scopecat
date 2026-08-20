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
        InstrumentReadback,
        InstrumentStateObservation,
        InstrumentStateReadback,
        InstrumentStateSetting,
        InstrumentStateSnapshot,
        state_observation,
        state_setting,
    )
    from scopecat.sdk.instruments.authoring import (
        DriverAcquisition,
        DriverAcquisitionDimension,
        DriverArgument,
        DriverOperation,
        DriverOutcome,
        DriverPayload,
        DriverReadback,
        DriverRejected,
        DriverScalar,
        DriverStateAssignment,
        DriverStateObservation,
        DriverStatePatch,
        DriverStateReadback,
        DriverStateReadRequest,
        DriverSuccess,
        DriverUnknown,
        state_readback,
    )
    from scopecat.sdk.instruments.backend import InstrumentBackend
    from scopecat.sdk.instruments.catalog import (
        DriverCatalog,
        DriverConnectionSpec,
        DriverSpec,
        InstrumentConnectionKind,
    )
    from scopecat.sdk.instruments.commands import (
        ApplyReceipt,
        CollectReceipt,
        InstrumentConfiguredDefaultsApplyReceipt,
        InvokeReceipt,
    )
    from scopecat.sdk.instruments.contracts import (
        AcquisitionAxisSize,
        AcquisitionAxisSpec,
        AcquisitionPreconditionSpec,
        AcquisitionResultSpec,
        AcquisitionSpec,
        ComponentSpec,
        DeviceStateMemberSpec,
        DeviceStateSpec,
        InstrumentComponentSpec,
        InstrumentDescription,
        InterfaceMountSpec,
        InterfaceSpec,
        OperationArgumentSpec,
        OperationSpec,
        PropertySpec,
        StatePropertyRef,
        acquisition,
        acquisition_axis,
        acquisition_precondition,
        acquisition_result,
        bool_property,
        capture_state_members,
        component,
        enum_property,
        float_property,
        instrument_component,
        int_property,
        interface,
        interface_mount,
        operation,
        operation_argument,
        quantity_property,
        state_capture_request,
        string_property,
    )
    from scopecat.sdk.instruments.declarations import (
        DeviceMember,
        Member,
        device_member,
    )
    from scopecat.sdk.instruments.errors import InstrumentCollectFailure
    from scopecat.sdk.instruments.members import (
        AcquisitionRef,
        AcquisitionResultRef,
        ComponentRef,
        DevicePropertyRef,
        InterfaceRef,
        OperationArgumentRef,
        OperationRef,
        PropertyRef,
        StateMemberRef,
    )
    from scopecat.sdk.instruments.mounted_driver import (
        MountedInstrumentDriver,
        MountedInstrumentRouter,
        MountPath,
    )
    from scopecat.sdk.instruments.object_driver import (
        Change,
        InstrumentDriverMetadata,
        ObjectInstrumentDriver,
        instrument_driver,
        query,
        read,
        update,
        write,
    )
    from scopecat.sdk.instruments.provider import (
        DriverFault,
        InstrumentConnectionContext,
        InstrumentDriver,
        InstrumentProvider,
        InstrumentProviderContext,
        InstrumentProviderDescription,
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
    "Change": ("scopecat.sdk.instruments.object_driver", "Change"),
    "AcquisitionAxisSize": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionAxisSize",
    ),
    "AcquisitionAxisSpec": (
        "scopecat.sdk.instruments.contracts",
        "AcquisitionAxisSpec",
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
    "ApplyReceipt": ("scopecat.sdk.instruments.commands", "ApplyReceipt"),
    "CollectReceipt": ("scopecat.sdk.instruments.commands", "CollectReceipt"),
    "CommandChannelBinding": (
        "scopecat.records.instrument",
        "CommandChannelBinding",
    ),
    "ComponentRef": ("scopecat.sdk.instruments.members", "ComponentRef"),
    "ComponentSpec": ("scopecat.sdk.instruments.contracts", "ComponentSpec"),
    "DeviceStateMemberSpec": (
        "scopecat.sdk.instruments.contracts",
        "DeviceStateMemberSpec",
    ),
    "DeviceStateSpec": (
        "scopecat.sdk.instruments.contracts",
        "DeviceStateSpec",
    ),
    "DeviceMember": ("scopecat.sdk.instruments.declarations", "DeviceMember"),
    "DriverAcquisition": (
        "scopecat.sdk.instruments.authoring",
        "DriverAcquisition",
    ),
    "DriverAcquisitionDimension": (
        "scopecat.sdk.instruments.authoring",
        "DriverAcquisitionDimension",
    ),
    "DriverCatalog": ("scopecat.sdk.instruments.catalog", "DriverCatalog"),
    "DriverConnectionSpec": (
        "scopecat.sdk.instruments.catalog",
        "DriverConnectionSpec",
    ),
    "DriverArgument": ("scopecat.sdk.instruments.authoring", "DriverArgument"),
    "DriverFault": ("scopecat.sdk.instruments.provider", "DriverFault"),
    "DriverOperation": ("scopecat.sdk.instruments.authoring", "DriverOperation"),
    "DriverOutcome": ("scopecat.sdk.instruments.authoring", "DriverOutcome"),
    "DriverPayload": ("scopecat.sdk.instruments.authoring", "DriverPayload"),
    "DriverReadback": ("scopecat.sdk.instruments.authoring", "DriverReadback"),
    "DriverRejected": ("scopecat.sdk.instruments.authoring", "DriverRejected"),
    "DriverScalar": ("scopecat.sdk.instruments.authoring", "DriverScalar"),
    "DriverStateAssignment": (
        "scopecat.sdk.instruments.authoring",
        "DriverStateAssignment",
    ),
    "DriverStateObservation": (
        "scopecat.sdk.instruments.authoring",
        "DriverStateObservation",
    ),
    "DriverStatePatch": (
        "scopecat.sdk.instruments.authoring",
        "DriverStatePatch",
    ),
    "DriverStateReadRequest": (
        "scopecat.sdk.instruments.authoring",
        "DriverStateReadRequest",
    ),
    "DriverStateReadback": (
        "scopecat.sdk.instruments.authoring",
        "DriverStateReadback",
    ),
    "DriverSpec": ("scopecat.sdk.instruments.catalog", "DriverSpec"),
    "DriverSuccess": ("scopecat.sdk.instruments.authoring", "DriverSuccess"),
    "DriverUnknown": ("scopecat.sdk.instruments.authoring", "DriverUnknown"),
    "InstrumentBackend": ("scopecat.sdk.instruments.backend", "InstrumentBackend"),
    "InstrumentDriverMetadata": (
        "scopecat.sdk.instruments.object_driver",
        "InstrumentDriverMetadata",
    ),
    "InstrumentBindingSpec": (
        "scopecat.records.config",
        "InstrumentBindingSpec",
    ),
    "InstrumentConnection": ("scopecat.records.config", "InstrumentConnection"),
    "InstrumentConnectionContext": (
        "scopecat.sdk.instruments.provider",
        "InstrumentConnectionContext",
    ),
    "InstrumentConnectionKind": (
        "scopecat.sdk.instruments.catalog",
        "InstrumentConnectionKind",
    ),
    "InstrumentComponentSpec": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentComponentSpec",
    ),
    "InstrumentCollectFailure": (
        "scopecat.sdk.instruments.errors",
        "InstrumentCollectFailure",
    ),
    "InstrumentConfiguredDefaultsApplyReceipt": (
        "scopecat.sdk.instruments.commands",
        "InstrumentConfiguredDefaultsApplyReceipt",
    ),
    "InstrumentDescription": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentDescription",
    ),
    "InstrumentDriver": ("scopecat.sdk.instruments.provider", "InstrumentDriver"),
    "ObjectInstrumentDriver": (
        "scopecat.sdk.instruments.object_driver",
        "ObjectInstrumentDriver",
    ),
    "InstrumentStateObservation": (
        "scopecat.records.instrument",
        "InstrumentStateObservation",
    ),
    "InstrumentStateReadback": (
        "scopecat.records.instrument",
        "InstrumentStateReadback",
    ),
    "InstrumentStateSetting": (
        "scopecat.records.instrument",
        "InstrumentStateSetting",
    ),
    "InstrumentProvider": ("scopecat.sdk.instruments.provider", "InstrumentProvider"),
    "InstrumentProviderContext": (
        "scopecat.sdk.instruments.provider",
        "InstrumentProviderContext",
    ),
    "InstrumentProviderDescription": (
        "scopecat.sdk.instruments.provider",
        "InstrumentProviderDescription",
    ),
    "InstrumentReadback": ("scopecat.records.instrument", "InstrumentReadback"),
    "InstrumentStateSnapshot": (
        "scopecat.records.instrument",
        "InstrumentStateSnapshot",
    ),
    "state_observation": (
        "scopecat.records.instrument",
        "state_observation",
    ),
    "state_setting": (
        "scopecat.records.instrument",
        "state_setting",
    ),
    "InterfaceRef": ("scopecat.sdk.instruments.members", "InterfaceRef"),
    "Member": ("scopecat.sdk.instruments.declarations", "Member"),
    "MountPath": ("scopecat.sdk.instruments.mounted_driver", "MountPath"),
    "MountedInstrumentDriver": (
        "scopecat.sdk.instruments.mounted_driver",
        "MountedInstrumentDriver",
    ),
    "MountedInstrumentRouter": (
        "scopecat.sdk.instruments.mounted_driver",
        "MountedInstrumentRouter",
    ),
    "DevicePropertyRef": (
        "scopecat.sdk.instruments.members",
        "DevicePropertyRef",
    ),
    "InterfaceMountSpec": (
        "scopecat.sdk.instruments.contracts",
        "InterfaceMountSpec",
    ),
    "InterfaceSpec": ("scopecat.sdk.instruments.contracts", "InterfaceSpec"),
    "InvokeReceipt": ("scopecat.sdk.instruments.commands", "InvokeReceipt"),
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
    "StateMemberRef": ("scopecat.sdk.instruments.members", "StateMemberRef"),
    "PropertySpec": ("scopecat.sdk.instruments.contracts", "PropertySpec"),
    "ScpiIdentity": ("scopecat.sdk.instruments.scpi", "ScpiIdentity"),
    "ScpiProtocolError": ("scopecat.sdk.instruments.scpi", "ScpiProtocolError"),
    "ScpiTransport": ("scopecat.sdk.instruments.scpi", "ScpiTransport"),
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
    "acquisition_precondition": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_precondition",
    ),
    "acquisition_result": (
        "scopecat.sdk.instruments.contracts",
        "acquisition_result",
    ),
    "bool_property": ("scopecat.sdk.instruments.contracts", "bool_property"),
    "capture_state_members": (
        "scopecat.sdk.instruments.contracts",
        "capture_state_members",
    ),
    "component": ("scopecat.sdk.instruments.contracts", "component"),
    "device_member": (
        "scopecat.sdk.instruments.declarations",
        "device_member",
    ),
    "enum_property": ("scopecat.sdk.instruments.contracts", "enum_property"),
    "float_property": ("scopecat.sdk.instruments.contracts", "float_property"),
    "format_number": ("scopecat.sdk.instruments.scpi", "format_number"),
    "int_property": ("scopecat.sdk.instruments.contracts", "int_property"),
    "interface": ("scopecat.sdk.instruments.contracts", "interface"),
    "interface_mount": (
        "scopecat.sdk.instruments.contracts",
        "interface_mount",
    ),
    "instrument_component": (
        "scopecat.sdk.instruments.contracts",
        "instrument_component",
    ),
    "instrument_driver": (
        "scopecat.sdk.instruments.object_driver",
        "instrument_driver",
    ),
    "query": ("scopecat.sdk.instruments.object_driver", "query"),
    "read": ("scopecat.sdk.instruments.object_driver", "read"),
    "update": ("scopecat.sdk.instruments.object_driver", "update"),
    "write": ("scopecat.sdk.instruments.object_driver", "write"),
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
    "string_property": ("scopecat.sdk.instruments.contracts", "string_property"),
    "state_readback": (
        "scopecat.sdk.instruments.authoring",
        "state_readback",
    ),
    "state_capture_request": (
        "scopecat.sdk.instruments.contracts",
        "state_capture_request",
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
