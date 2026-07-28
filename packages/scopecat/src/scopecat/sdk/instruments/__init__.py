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
        InstrumentReadback,
        InstrumentStateField,
        InstrumentStateSnapshot,
    )
    from scopecat.sdk.instruments.contracts import (
        ApplyReceipt,
        CapabilityDescription,
        CapabilityField,
        CollectAxisRequest,
        CollectCommand,
        CollectProductRequest,
        CollectReceipt,
        DriverFault,
        InstrumentDescription,
        InstrumentDriver,
        InstrumentProvider,
        InstrumentProviderContext,
        InstrumentProviderDescription,
        InstrumentProviderResult,
        InstrumentStateCommand,
        InstrumentStateCommandField,
        ProductAxisDescription,
        ProductDescription,
        apply_state_command_to_snapshot,
        bool_field,
        capability,
        enum_field,
        float_field,
        int_field,
        payload_field,
        product,
        product_axis,
        quantity_field,
        string_field,
        validate_collect_command,
        validate_collect_receipt,
        validate_state_command,
        validate_state_fields,
    )


_EXPORTS: dict[str, tuple[str, str]] = {
    "ApplyReceipt": ("scopecat.sdk.instruments.contracts", "ApplyReceipt"),
    "CapabilityDescription": (
        "scopecat.sdk.instruments.contracts",
        "CapabilityDescription",
    ),
    "CapabilityField": ("scopecat.sdk.instruments.contracts", "CapabilityField"),
    "CollectAxisRequest": ("scopecat.sdk.instruments.contracts", "CollectAxisRequest"),
    "CollectCommand": ("scopecat.sdk.instruments.contracts", "CollectCommand"),
    "CollectProductRequest": (
        "scopecat.sdk.instruments.contracts",
        "CollectProductRequest",
    ),
    "CollectReceipt": ("scopecat.sdk.instruments.contracts", "CollectReceipt"),
    "CommandChannelBinding": (
        "scopecat.records.instrument",
        "CommandChannelBinding",
    ),
    "DriverFault": ("scopecat.sdk.instruments.contracts", "DriverFault"),
    "InstrumentDescription": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentDescription",
    ),
    "InstrumentDriver": ("scopecat.sdk.instruments.contracts", "InstrumentDriver"),
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
    "InstrumentStateCommandField": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentStateCommandField",
    ),
    "InstrumentStateField": (
        "scopecat.records.instrument",
        "InstrumentStateField",
    ),
    "InstrumentStateSnapshot": (
        "scopecat.records.instrument",
        "InstrumentStateSnapshot",
    ),
    "ProductAxisDescription": (
        "scopecat.sdk.instruments.contracts",
        "ProductAxisDescription",
    ),
    "ProductDescription": ("scopecat.sdk.instruments.contracts", "ProductDescription"),
    "apply_state_command_to_snapshot": (
        "scopecat.sdk.instruments.contracts",
        "apply_state_command_to_snapshot",
    ),
    "bool_field": ("scopecat.sdk.instruments.contracts", "bool_field"),
    "capability": ("scopecat.sdk.instruments.contracts", "capability"),
    "enum_field": ("scopecat.sdk.instruments.contracts", "enum_field"),
    "float_field": ("scopecat.sdk.instruments.contracts", "float_field"),
    "int_field": ("scopecat.sdk.instruments.contracts", "int_field"),
    "payload_field": ("scopecat.sdk.instruments.contracts", "payload_field"),
    "product": ("scopecat.sdk.instruments.contracts", "product"),
    "product_axis": ("scopecat.sdk.instruments.contracts", "product_axis"),
    "quantity_field": ("scopecat.sdk.instruments.contracts", "quantity_field"),
    "string_field": ("scopecat.sdk.instruments.contracts", "string_field"),
    "validate_state_command": (
        "scopecat.sdk.instruments.contracts",
        "validate_state_command",
    ),
    "validate_state_fields": (
        "scopecat.sdk.instruments.contracts",
        "validate_state_fields",
    ),
    "validate_collect_command": (
        "scopecat.sdk.instruments.contracts",
        "validate_collect_command",
    ),
    "validate_collect_receipt": (
        "scopecat.sdk.instruments.contracts",
        "validate_collect_receipt",
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
