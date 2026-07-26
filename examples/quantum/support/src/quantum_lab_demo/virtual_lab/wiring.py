"""User-facing quantum wiring helpers for lab configuration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

from scopecat.kernel.entity import EntityRef
from scopecat.records.config import (
    ConfigProfileSnapshot,
    RoutingEndpointBinding,
    RoutingGraph,
    SystemSpec,
    Topology,
)

from quantum_lab_demo.configuration import quantum_lab_bootstrap_config


@dataclass(frozen=True)
class ChannelWiring:
    instrument_id: str
    channel_id: str


@dataclass(frozen=True)
class QubitWiring:
    id: str
    drive: ChannelWiring
    readout: ChannelWiring


@dataclass(frozen=True)
class QuantumWiring:
    qubits: tuple[QubitWiring, ...]


class QuantumWiringBuilder:
    """Lab-facing builder for qubit channel routing.

    The builder is intentionally domain-local example code. It lets users edit
    a familiar lab view, then compiles that view into Scopecat's domain-neutral
    topology and canonical endpoint bindings.
    """

    def __init__(self) -> None:
        self._qubits: list[QubitWiring] = []

    def qubit(
        self,
        qubit_id: str,
        *,
        drive: ChannelWiring,
        readout: ChannelWiring,
    ) -> Self:
        self._qubits.append(QubitWiring(id=qubit_id, drive=drive, readout=readout))
        return self

    def build(self) -> QuantumWiring:
        wiring = QuantumWiring(
            qubits=tuple(self._qubits),
        )
        _validate_wiring(wiring)
        return wiring


def quantum_wiring() -> QuantumWiringBuilder:
    return QuantumWiringBuilder()


def quantum_wiring_config_profile() -> ConfigProfileSnapshot:
    """Build the accepted list-mode wiring snapshot."""

    base = quantum_lab_bootstrap_config()
    return base.model_copy(
        update={
            "system": compile_quantum_wiring_system(
                base.system,
                default_quantum_wiring(),
            )
        }
    )


def default_quantum_wiring() -> QuantumWiring:
    readout = ChannelWiring(
        instrument_id="readout-stack",
        channel_id="readout.mux0",
    )
    return (
        quantum_wiring()
        .qubit(
            "q0",
            drive=ChannelWiring(
                instrument_id="drive-stack",
                channel_id="drive.awg0.ch1",
            ),
            readout=readout,
        )
        .build()
    )


def compile_quantum_wiring_system(
    base: SystemSpec,
    wiring: QuantumWiring,
) -> SystemSpec:
    _validate_wiring(wiring)
    topology = _topology_from_wiring(wiring=wiring)
    routing = _routing_from_wiring(wiring=wiring)
    return base.model_copy(update={"topology": topology, "routing": routing})


def _topology_from_wiring(*, wiring: QuantumWiring) -> Topology:
    return Topology(
        entities=[
            EntityRef(id=qubit.id, kind="logical_qubit") for qubit in wiring.qubits
        ]
    )


def _routing_from_wiring(*, wiring: QuantumWiring) -> RoutingGraph:
    bindings: list[RoutingEndpointBinding] = []
    for qubit in wiring.qubits:
        bindings.extend(
            _endpoint_bindings(
                entity_id=qubit.id,
                endpoint=qubit.drive,
                capabilities=("play_pulse_program",),
            )
        )
        bindings.extend(
            _endpoint_bindings(
                entity_id=qubit.id,
                endpoint=qubit.readout,
                capabilities=("readout_pulse", "acquire_iq"),
            )
        )
    return RoutingGraph(bindings=bindings)


def _endpoint_bindings(
    *,
    entity_id: str,
    endpoint: ChannelWiring,
    capabilities: Sequence[str],
) -> list[RoutingEndpointBinding]:
    return [
        RoutingEndpointBinding(
            instrument_id=endpoint.instrument_id,
            capability=capability,
            entity_id=entity_id,
            channel_id=endpoint.channel_id,
        )
        for capability in capabilities
    ]


def _validate_wiring(wiring: QuantumWiring) -> None:
    _reject_duplicate_ids([qubit.id for qubit in wiring.qubits], "qubit")


def _reject_duplicate_ids(values: Sequence[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            msg = f"duplicate {label} id: {value}"
            raise ValueError(msg)
        seen.add(value)


__all__ = [
    "ChannelWiring",
    "QuantumWiring",
    "QuantumWiringBuilder",
    "QubitWiring",
    "compile_quantum_wiring_system",
    "default_quantum_wiring",
    "quantum_wiring",
    "quantum_wiring_config_profile",
]
