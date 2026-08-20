"""Reference-lab interfaces shared across physical device drivers."""

from __future__ import annotations

from scopecat.sdk.instruments import (
    InterfaceRef,
    InterfaceSpec,
    bool_property,
    interface,
    quantity_property,
)

CLOCK_TIMING = InterfaceRef("reference_lab.clock_timing/v1")
CLOCK_TIMING_FREQUENCY = CLOCK_TIMING.property("frequency")
CLOCK_TIMING_LOCKED = CLOCK_TIMING.property("locked")


def clock_timing_interface() -> InterfaceSpec:
    return interface(
        CLOCK_TIMING.interface_id,
        label="Clock timing",
        description="Lab AWG reference-frequency configuration and lock state.",
        properties=(
            quantity_property(
                CLOCK_TIMING_FREQUENCY.property_id,
                unit="Hz",
                minimum=1.0,
                label="Reference frequency",
            ),
            bool_property(
                CLOCK_TIMING_LOCKED.property_id,
                label="Reference locked",
                access="read_only",
            ),
        ),
    )


__all__ = [
    "CLOCK_TIMING",
    "CLOCK_TIMING_FREQUENCY",
    "CLOCK_TIMING_LOCKED",
    "clock_timing_interface",
]
