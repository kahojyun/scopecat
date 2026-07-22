"""User-facing quantum wiring helpers for lab configuration."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Self

from scopecat.config.profiles import load_config_profile
from scopecat.records.config import (
    Channel,
    ConfigProfileSnapshot,
    Device,
    Link,
    RoutingEndpointBinding,
    RoutingGraph,
    SharedResourceGroup,
    SystemSpec,
    Topology,
    TopologyLine,
)
from scopecat.records.entity import EntityRef

from quantum_lab_demo.fixtures import EXPERIMENT_FIXTURE_DIR


@dataclass(frozen=True)
class QubitWiring:
    id: str
    drive: str
    readout: str
    flux: str | None = None


@dataclass(frozen=True)
class CouplerWiring:
    id: str
    qubits: tuple[str, str]
    flux: str


@dataclass(frozen=True)
class LineWiring:
    id: str
    kind: str
    instrument_id: str
    channel_id: str
    port: str | None = None
    lo_group: str | None = None


@dataclass(frozen=True)
class QuantumWiring:
    qubits: tuple[QubitWiring, ...]
    couplers: tuple[CouplerWiring, ...]
    lines: tuple[LineWiring, ...]


class QuantumWiringBuilder:
    """Lab-facing builder for qubit/coupler/line wiring.

    The builder is intentionally domain-local example code. It lets users edit
    a familiar lab view, then compiles that view into Scopecat's domain-neutral
    topology and canonical endpoint bindings.
    """

    def __init__(self) -> None:
        self._qubits: list[QubitWiring] = []
        self._couplers: list[CouplerWiring] = []
        self._lines: list[LineWiring] = []

    def qubit(
        self,
        qubit_id: str,
        *,
        drive: str,
        readout: str,
        flux: str | None = None,
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
        flux: str,
    ) -> Self:
        self._couplers.append(CouplerWiring(id=coupler_id, qubits=qubits, flux=flux))
        return self

    def drive_line(
        self,
        line_id: str,
        *,
        instrument: str,
        channel: str,
        port: str | None = None,
        shared_lo: str | None = None,
    ) -> Self:
        return self.line(
            line_id,
            kind="drive",
            instrument=instrument,
            channel=channel,
            port=port,
            shared_lo=shared_lo,
        )

    def readout_line(
        self,
        line_id: str,
        *,
        instrument: str,
        channel: str,
        port: str | None = None,
        shared_lo: str | None = None,
    ) -> Self:
        return self.line(
            line_id,
            kind="readout",
            instrument=instrument,
            channel=channel,
            port=port,
            shared_lo=shared_lo,
        )

    def qubit_flux_line(
        self,
        line_id: str,
        *,
        instrument: str,
        channel: str,
        port: str | None = None,
        shared_lo: str | None = None,
    ) -> Self:
        return self.line(
            line_id,
            kind="flux",
            instrument=instrument,
            channel=channel,
            port=port,
            shared_lo=shared_lo,
        )

    def coupler_flux_line(
        self,
        line_id: str,
        *,
        instrument: str,
        channel: str,
        port: str | None = None,
        shared_lo: str | None = None,
    ) -> Self:
        return self.line(
            line_id,
            kind="coupler",
            instrument=instrument,
            channel=channel,
            port=port,
            shared_lo=shared_lo,
        )

    def line(
        self,
        line_id: str,
        *,
        kind: str,
        instrument: str,
        channel: str,
        port: str | None = None,
        shared_lo: str | None = None,
    ) -> Self:
        self._lines.append(
            LineWiring(
                id=line_id,
                kind=kind,
                instrument_id=instrument,
                channel_id=channel,
                port=port,
                lo_group=shared_lo,
            )
        )
        return self

    def build(self) -> QuantumWiring:
        wiring = QuantumWiring(
            qubits=tuple(self._qubits),
            couplers=tuple(self._couplers),
            lines=tuple(self._lines),
        )
        _validate_wiring(wiring)
        return wiring


def quantum_wiring() -> QuantumWiringBuilder:
    return QuantumWiringBuilder()


def quantum_wiring_config_profile() -> ConfigProfileSnapshot:
    base = load_config_profile(EXPERIMENT_FIXTURE_DIR / "config-profile.json")
    return base.model_copy(
        update={
            "system": compile_quantum_wiring_system(
                base.system, default_quantum_wiring()
            )
        }
    )


def default_quantum_wiring() -> QuantumWiring:
    return (
        quantum_wiring()
        .drive_line(
            "q0.xy",
            instrument="drive-stack",
            channel="drive.awg0.ch1",
            port="awg0.ch1",
            shared_lo="lo.xy0",
        )
        .drive_line(
            "q1.xy",
            instrument="drive-stack",
            channel="drive.awg0.ch2",
            port="awg0.ch2",
            shared_lo="lo.xy0",
        )
        .drive_line(
            "q2.xy",
            instrument="drive-stack",
            channel="drive.awg1.ch1",
            port="awg1.ch1",
            shared_lo="lo.xy1",
        )
        .drive_line(
            "q3.xy",
            instrument="drive-stack",
            channel="drive.awg1.ch2",
            port="awg1.ch2",
            shared_lo="lo.xy1",
        )
        .readout_line(
            "ro.mux0",
            instrument="readout-stack",
            channel="readout.mux0",
            port="ro0",
            shared_lo="lo.ro0",
        )
        .coupler_flux_line(
            "c01.z",
            instrument="coupler-stack",
            channel="coupler.bias0",
            port="bias0",
        )
        .coupler_flux_line(
            "c23.z",
            instrument="coupler-stack",
            channel="coupler.bias1",
            port="bias1",
        )
        .qubit("q0", drive="q0.xy", readout="ro.mux0")
        .qubit("q1", drive="q1.xy", readout="ro.mux0")
        .qubit("q2", drive="q2.xy", readout="ro.mux0")
        .qubit("q3", drive="q3.xy", readout="ro.mux0")
        .coupler("coupler-q0-q1", qubits=("q0", "q1"), flux="c01.z")
        .coupler("coupler-q2-q3", qubits=("q2", "q3"), flux="c23.z")
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
    logical_devices = [
        Device(
            id=qubit.id,
            kind="logical_qubit",
            channels=_qubit_channel_ids(qubit=qubit, lines=wiring.lines),
        )
        for qubit in wiring.qubits
    ] + [
        Device(
            id=coupler.id,
            kind="logical_coupler",
            channels=_line_channel_ids((coupler.flux,), lines=wiring.lines),
        )
        for coupler in wiring.couplers
    ]
    instrument_devices = [
        Device(id=instrument_id, kind="logical_instrument")
        for instrument_id in _instrument_ids(wiring.lines)
    ]
    lines = [
        TopologyLine(
            id=line.id,
            kind=f"{line.kind}_line",
            signal=line.kind,
            endpoints=_line_endpoints(line=line, wiring=wiring),
        )
        for line in wiring.lines
    ]
    channels = [
        Channel(
            id=line.channel_id,
            kind=line.kind,
            device_id=line.instrument_id,
            direction=_line_direction(line.kind),
            signal=line.kind,
            port=line.port,
            line_id=line.id,
            group_ids=[line.lo_group] if line.lo_group is not None else [],
        )
        for line in wiring.lines
    ]
    groups = [
        SharedResourceGroup(
            id=group_id,
            kind="lo",
            members=[
                line.channel_id for line in wiring.lines if line.lo_group == group_id
            ],
        )
        for group_id in _lo_group_ids(wiring.lines)
    ]
    links = [
        Link(
            id=f"{coupler.qubits[0]}-{coupler.qubits[1]}-coupling",
            kind="coupling",
            endpoints=[*coupler.qubits, coupler.id],
        )
        for coupler in wiring.couplers
    ]
    return Topology(
        entities=entities,
        devices=[*logical_devices, *instrument_devices],
        links=links,
        lines=lines,
        channels=channels,
        groups=groups,
    )


def _routing_from_wiring(*, wiring: QuantumWiring) -> RoutingGraph:
    bindings: list[RoutingEndpointBinding] = []
    for instrument_id in _instrument_ids(wiring.lines):
        instrument_lines = [
            line for line in wiring.lines if line.instrument_id == instrument_id
        ]
        bindings.extend(_routing_bindings(instrument_lines, wiring=wiring))
    return RoutingGraph(bindings=bindings)


def _routing_bindings(
    lines: Sequence[LineWiring],
    *,
    wiring: QuantumWiring,
) -> list[RoutingEndpointBinding]:
    result: list[RoutingEndpointBinding] = []
    for line in lines:
        result.extend(
            RoutingEndpointBinding(
                instrument_id=line.instrument_id,
                capability=capability,
                entity_id=entity_id,
                channel_id=line.channel_id,
            )
            for entity_id in _line_entities(line=line, wiring=wiring)
            for capability in _line_capabilities(line.kind)
        )
    return result


def _line_entities(*, line: LineWiring, wiring: QuantumWiring) -> tuple[str, ...]:
    if line.kind == "drive":
        return tuple(qubit.id for qubit in wiring.qubits if qubit.drive == line.id)
    if line.kind == "readout":
        return tuple(qubit.id for qubit in wiring.qubits if qubit.readout == line.id)
    if line.kind == "flux":
        return tuple(
            qubit.id
            for qubit in wiring.qubits
            if qubit.flux is not None and qubit.flux == line.id
        )
    if line.kind == "coupler":
        return tuple(
            coupler.id for coupler in wiring.couplers if coupler.flux == line.id
        )
    return ()


def _line_capabilities(kind: str) -> list[str]:
    if kind == "drive":
        return ["play_pulse_program", "play_gate_sequence"]
    if kind == "readout":
        return ["readout_pulse", "acquire_iq"]
    if kind == "coupler":
        return ["play_coupler_pulse", "set_flux_bias"]
    if kind == "flux":
        return ["set_flux_bias"]
    return []


def _qubit_channel_ids(*, qubit: QubitWiring, lines: Sequence[LineWiring]) -> list[str]:
    line_ids = [qubit.drive, qubit.readout]
    if qubit.flux is not None:
        line_ids.append(qubit.flux)
    return _line_channel_ids(line_ids, lines=lines)


def _line_channel_ids(
    line_ids: Sequence[str],
    *,
    lines: Sequence[LineWiring],
) -> list[str]:
    by_id = {line.id: line.channel_id for line in lines}
    return [by_id[line_id] for line_id in line_ids if line_id in by_id]


def _line_endpoints(*, line: LineWiring, wiring: QuantumWiring) -> list[str]:
    return [*_line_entities(line=line, wiring=wiring), line.instrument_id]


def _instrument_ids(lines: Sequence[LineWiring]) -> list[str]:
    return list(dict.fromkeys(line.instrument_id for line in lines))


def _lo_group_ids(lines: Sequence[LineWiring]) -> list[str]:
    return list(
        dict.fromkeys(line.lo_group for line in lines if line.lo_group is not None)
    )


def _line_direction(kind: str) -> str:
    if kind == "readout":
        return "readout"
    return "control"


def _validate_wiring(wiring: QuantumWiring) -> None:
    _reject_duplicate_ids([qubit.id for qubit in wiring.qubits], "qubit")
    _reject_duplicate_ids([coupler.id for coupler in wiring.couplers], "coupler")
    _reject_duplicate_ids([line.id for line in wiring.lines], "line")
    _reject_duplicate_ids([line.channel_id for line in wiring.lines], "channel")

    line_ids = {line.id for line in wiring.lines}
    qubit_ids = {qubit.id for qubit in wiring.qubits}
    for qubit in wiring.qubits:
        _require_line(qubit.id, qubit.drive, line_ids=line_ids, role="drive")
        _require_line(qubit.id, qubit.readout, line_ids=line_ids, role="readout")
        if qubit.flux is not None:
            _require_line(qubit.id, qubit.flux, line_ids=line_ids, role="flux")

    for coupler in wiring.couplers:
        for qubit_id in coupler.qubits:
            if qubit_id not in qubit_ids:
                msg = f"coupler {coupler.id!r} references unknown qubit {qubit_id!r}"
                raise ValueError(msg)
        _require_line(coupler.id, coupler.flux, line_ids=line_ids, role="flux")


def _reject_duplicate_ids(values: Sequence[str], label: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            msg = f"duplicate {label} id: {value}"
            raise ValueError(msg)
        seen.add(value)


def _require_line(
    owner_id: str,
    line_id: str,
    *,
    line_ids: set[str],
    role: str,
) -> None:
    if line_id not in line_ids:
        msg = f"{owner_id!r} references unknown {role} line {line_id!r}"
        raise ValueError(msg)


__all__ = [
    "CouplerWiring",
    "LineWiring",
    "QuantumWiring",
    "QuantumWiringBuilder",
    "QubitWiring",
    "compile_quantum_wiring_system",
    "default_quantum_wiring",
    "quantum_wiring",
    "quantum_wiring_config_profile",
]
