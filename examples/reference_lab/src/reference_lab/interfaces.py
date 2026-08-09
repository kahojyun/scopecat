"""Reference-lab interfaces shared across physical device drivers."""

from __future__ import annotations

from scopecat.sdk.instruments import (
    InterfaceRef,
    InterfaceSpec,
    bool_property,
    enum_property,
    interface,
    quantity_property,
)

CLOCK_REFERENCE = InterfaceRef("reference_lab.clock_reference/v1")
CLOCK_REFERENCE_SOURCE = CLOCK_REFERENCE.property("source")
CLOCK_REFERENCE_FREQUENCY = CLOCK_REFERENCE.property("frequency")
CLOCK_REFERENCE_LOCKED = CLOCK_REFERENCE.property("locked")


def clock_reference_interface() -> InterfaceSpec:
    return interface(
        CLOCK_REFERENCE.interface_id,
        label="Clock reference",
        description="Instrument-wide reference clock configuration and lock state.",
        properties=(
            enum_property(
                CLOCK_REFERENCE_SOURCE.property_id,
                choices=("internal", "external"),
                label="Reference source",
            ),
            quantity_property(
                CLOCK_REFERENCE_FREQUENCY.property_id,
                unit="Hz",
                minimum=1.0,
                label="Reference frequency",
            ),
            bool_property(
                CLOCK_REFERENCE_LOCKED.property_id,
                label="Reference locked",
                access="read_only",
            ),
        ),
    )


__all__ = [
    "CLOCK_REFERENCE",
    "CLOCK_REFERENCE_FREQUENCY",
    "CLOCK_REFERENCE_LOCKED",
    "CLOCK_REFERENCE_SOURCE",
    "clock_reference_interface",
]
