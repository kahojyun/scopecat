"""Instrument adapter contracts and simple reference implementation."""

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
        ActionReceipt,
        ApplyReceipt,
        CapabilityDescription,
        CapabilityField,
        CollectAxisRequest,
        CollectCommand,
        CollectProductRequest,
        CollectReceipt,
        DriverFault,
        InstrumentActionCommand,
        InstrumentActionCommandField,
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
        validate_action_command,
        validate_state_command,
    )
    from scopecat.sdk.instruments.simple import (
        SimpleCapability,
        SimpleInstrumentDriver,
        SimpleLifecycleCallback,
        SimpleProduct,
        SimpleProductReader,
        SimpleStateField,
        SimpleStateReader,
        SimpleStateWriter,
        simple_capability,
    )


_EXPORTS: dict[str, tuple[str, str]] = {
    "ActionReceipt": ("scopecat.sdk.instruments.contracts", "ActionReceipt"),
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
    "InstrumentActionCommand": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentActionCommand",
    ),
    "InstrumentActionCommandField": (
        "scopecat.sdk.instruments.contracts",
        "InstrumentActionCommandField",
    ),
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
    "validate_action_command": (
        "scopecat.sdk.instruments.contracts",
        "validate_action_command",
    ),
    "validate_state_command": (
        "scopecat.sdk.instruments.contracts",
        "validate_state_command",
    ),
    "SimpleCapability": ("scopecat.sdk.instruments.simple", "SimpleCapability"),
    "SimpleInstrumentDriver": (
        "scopecat.sdk.instruments.simple",
        "SimpleInstrumentDriver",
    ),
    "SimpleLifecycleCallback": (
        "scopecat.sdk.instruments.simple",
        "SimpleLifecycleCallback",
    ),
    "SimpleProduct": ("scopecat.sdk.instruments.simple", "SimpleProduct"),
    "SimpleProductReader": ("scopecat.sdk.instruments.simple", "SimpleProductReader"),
    "SimpleStateField": ("scopecat.sdk.instruments.simple", "SimpleStateField"),
    "SimpleStateReader": ("scopecat.sdk.instruments.simple", "SimpleStateReader"),
    "SimpleStateWriter": ("scopecat.sdk.instruments.simple", "SimpleStateWriter"),
    "simple_capability": ("scopecat.sdk.instruments.simple", "simple_capability"),
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


__all__ = [
    "ActionReceipt",
    "ApplyReceipt",
    "CapabilityDescription",
    "CapabilityField",
    "CollectAxisRequest",
    "CollectCommand",
    "CollectProductRequest",
    "CollectReceipt",
    "CommandChannelBinding",
    "DriverFault",
    "InstrumentActionCommand",
    "InstrumentActionCommandField",
    "InstrumentDescription",
    "InstrumentDriver",
    "InstrumentProvider",
    "InstrumentProviderContext",
    "InstrumentProviderDescription",
    "InstrumentProviderResult",
    "InstrumentReadback",
    "InstrumentStateCommand",
    "InstrumentStateCommandField",
    "InstrumentStateField",
    "InstrumentStateSnapshot",
    "PayloadRef",
    "ProductAxisDescription",
    "ProductDescription",
    "SimpleCapability",
    "SimpleInstrumentDriver",
    "SimpleLifecycleCallback",
    "SimpleProduct",
    "SimpleProductReader",
    "SimpleStateField",
    "SimpleStateReader",
    "SimpleStateWriter",
    "StateValue",
    "apply_state_command_to_snapshot",
    "bool_field",
    "capability",
    "enum_field",
    "float_field",
    "int_field",
    "payload_field",
    "product",
    "product_axis",
    "quantity_field",
    "simple_capability",
    "string_field",
    "validate_action_command",
    "validate_state_command",
]
