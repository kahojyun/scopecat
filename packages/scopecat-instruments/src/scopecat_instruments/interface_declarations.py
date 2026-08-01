"""Typed Python declarations for first-party instrument capabilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal, Protocol

from scopecat.kernel.quantity import Quantity
from scopecat.program.value_refs import ValueRef
from scopecat.sdk.instruments.declarations import (
    CompiledInterface,
    acquisition,
    axis,
    compile_interface,
    instrument_interface,
    instrument_result,
    instrument_state,
    member,
    result,
)

type Desired[T] = T | ValueRef
type ReferenceSource = Literal["internal", "external"]
type SParameter = Literal["S11", "S21", "S12", "S22"]


@instrument_state
@dataclass(frozen=True, slots=True)
class NetworkSweepState:
    """Sparse network-sweep state shared by live and symbolic clients."""

    start_frequency: Annotated[
        Desired[Quantity] | None,
        member(
            unit="Hz",
            label="Start frequency",
            description="First stimulus frequency in the linear sweep.",
        ),
    ] = None
    stop_frequency: Annotated[
        Desired[Quantity] | None,
        member(
            unit="Hz",
            label="Stop frequency",
            description="Last stimulus frequency in the linear sweep.",
        ),
    ] = None
    points: Annotated[
        Desired[int] | None,
        member(
            minimum=2,
            label="Sweep points",
            description="Number of equally spaced frequency points.",
        ),
    ] = None
    if_bandwidth: Annotated[
        Desired[Quantity] | None,
        member(
            unit="Hz",
            label="IF bandwidth",
            description="Receiver intermediate-frequency bandwidth.",
        ),
    ] = None
    source_power: Annotated[
        Desired[Quantity] | None,
        member(
            unit="dBm",
            label="Source power",
            description="Stimulus power for the selected analyzer channel.",
        ),
    ] = None
    s_parameter: Annotated[
        Desired[SParameter] | None,
        member(
            label="S-parameter",
            description="Two-port S-parameter measured by the selected trace.",
        ),
    ] = None


@instrument_result
@dataclass(frozen=True, slots=True)
class _NetworkSweepResults:
    frequency: Annotated[
        list[float],
        result(
            dtype="float64",
            unit="Hz",
            axes=("frequency",),
            label="Frequency",
            description="Stimulus frequency values for the acquired trace.",
        ),
    ]
    s_parameter: Annotated[
        list[complex],
        result(
            dtype="complex128",
            unit="ratio",
            axes=("frequency",),
            label="Complex S-parameter",
            description=("Complex response values for the configured S-parameter."),
        ),
    ]


@instrument_interface(
    "scopecat.network_sweep/v1",
    state=NetworkSweepState,
    label="Network sweep",
    description="Linear, single-trigger complex S-parameter sweep.",
)
class NetworkSweepInterface(Protocol):
    @acquisition(
        label="Acquire sweep",
        description="Trigger and read the configured network sweep.",
        axes={
            "frequency": axis(
                size="points",
                kind="frequency",
                unit="Hz",
                label="Frequency",
                description="Linear VNA stimulus frequency.",
            )
        },
    )
    def sweep(self) -> _NetworkSweepResults: ...


NETWORK_SWEEP_DECLARATION: CompiledInterface[NetworkSweepInterface] = compile_interface(
    NetworkSweepInterface
)


__all__ = [
    "NETWORK_SWEEP_DECLARATION",
    "Desired",
    "NetworkSweepInterface",
    "NetworkSweepState",
    "ReferenceSource",
    "SParameter",
]
