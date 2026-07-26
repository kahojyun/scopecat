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
    flux: ChannelWiring | None = None


@dataclass(frozen=True)
class CouplerWiring:
    id: str
    qubits: tuple[str, str]
    flux: ChannelWiring


@dataclass(frozen=True)
class QuantumWiring:
    qubits: tuple[QubitWiring, ...]
    couplers: tuple[CouplerWiring, ...]


class QuantumWiringBuilder:
    """Lab-facing builder for qubit and coupler channel routing.

    The builder is intentionally domain-local example code. It lets users edit
    a familiar lab view, then compiles that view into Scopecat's domain-neutral
    topology and canonical endpoint bindings.
    """

    def __init__(self) -> None:
        self._qubits: list[QubitWiring] = []
        self._couplers: list[CouplerWiring] = []

    def qubit(
        self,
        qubit_id: str,
        *,
        drive: ChannelWiring,
        readout: ChannelWiring,
        flux: ChannelWiring | None = None,
    ) -> Self:
        self._qubits.append(
            QubitWiring(id=qubit_id, drive=drive, readout=readout, flux=flux)
        )
        return self

    def coupler(
        self,
        coupler_id: str,
        *,
        qubits: tuple[str, str],
        flux: ChannelWiring,
    ) -> Self:
        self._couplers.append(CouplerWiring(id=coupler_id, qubits=qubits, flux=flux))
        return self

    def build(self) -> QuantumWiring:
        wiring = QuantumWiring(
            qubits=tuple(self._qubits),
            couplers=tuple(self._couplers),
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
        .qubit(
            "q1",
            drive=ChannelWiring(
                instrument_id="drive-stack",
                channel_id="drive.awg0.ch2",
            ),
            readout=readout,
        )
        .qubit(
            "q2",
            drive=ChannelWiring(
                instrument_id="drive-stack",
                channel_id="drive.awg1.ch1",
            ),
            readout=readout,
        )
        .qubit(
            "q3",
            drive=ChannelWiring(
                instrument_id="drive-stack",
                channel_id="drive.awg1.ch2",
            ),
            readout=readout,
        )
        .coupler(
            "coupler-q0-q1",
            qubits=("q0", "q1"),
            flux=ChannelWiring(
                instrument_id="coupler-stack",
                channel_id="coupler.bias0",
            ),
        )
        .coupler(
            "coupler-q2-q3",
            qubits=("q2", "q3"),
            flux=ChannelWiring(
                instrument_id="coupler-stack",
                channel_id="coupler.bias1",
            ),
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
    entities = [
        EntityRef(id=qubit.id, kind="logical_qubit") for qubit in wiring.qubits
    ] + [
        EntityRef(id=coupler.id, kind="logical_coupler") for coupler in wiring.couplers
    ]
    return Topology(entities=entities)


def _routing_from_wiring(*, wiring: QuantumWiring) -> RoutingGraph:
    bindings: list[RoutingEndpointBinding] = []
    for qubit in wiring.qubits:
        bindings.extend(
            _endpoint_bindings(
                entity_id=qubit.id,
                endpoint=qubit.drive,
                capabilities=("play_pulse_program", "play_gate_sequence"),
            )
        )
        bindings.extend(
            _endpoint_bindings(
                entity_id=qubit.id,
                endpoint=qubit.readout,
                capabilities=("readout_pulse", "acquire_iq"),
            )
        )
        if qubit.flux is not None:
            bindings.extend(
                _endpoint_bindings(
                    entity_id=qubit.id,
                    endpoint=qubit.flux,
                    capabilities=("set_flux_bias",),
                )
            )
    for coupler in wiring.couplers:
        bindings.extend(
            _endpoint_bindings(
                entity_id=coupler.id,
                endpoint=coupler.flux,
                capabilities=("play_coupler_pulse", "set_flux_bias"),
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
    _reject_duplicate_ids([coupler.id for coupler in wiring.couplers], "coupler")

    qubit_ids = {qubit.id for qubit in wiring.qubits}
    for coupler in wiring.couplers:
        for qubit_id in coupler.qubits:
            if qubit_id not in qubit_ids:
                msg = f"coupler {coupler.id!r} references unknown qubit {qubit_id!r}"
                raise ValueError(msg)


def _reject_duplicate_ids(values: Sequence[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            msg = f"duplicate {label} id: {value}"
            raise ValueError(msg)
        seen.add(value)


__all__ = [
    "ChannelWiring",
    "CouplerWiring",
    "QuantumWiring",
    "QuantumWiringBuilder",
    "QubitWiring",
    "compile_quantum_wiring_system",
    "default_quantum_wiring",
    "quantum_wiring",
    "quantum_wiring_config_profile",
]
