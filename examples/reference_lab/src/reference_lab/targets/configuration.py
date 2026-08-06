"""Project accepted system routing into demo quantum target endpoints."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.records.config import ConfigProfileSnapshot
from scopecat_quantum._ids import QubitId
from scopecat_quantum.pulses import (
    AcquireSignal,
    DriveSignal,
    ReadoutSignal,
)

from reference_lab.interfaces import ACQUIRE_IQ, PLAY_PULSE_PROGRAM, READOUT_PULSE

FAKE_LIST_TARGET_KIND = "reference_lab.fake-list-mode"


@dataclass(frozen=True, slots=True)
class ConfiguredQuantumRoute:
    """One complete logical-signal route owned by the selected target."""

    instrument_id: str
    interface_id: str
    entity_id: str
    entity_kind: str
    channel_id: str

    @property
    def endpoint_id(self) -> str:
        # Target schedulers need one lane per logical route even when several
        # entities share a multiplexed physical channel.
        return f"{self.instrument_id}:{self.channel_id}:{self.entity_id}"


def configured_quantum_routes(
    config: ConfigProfileSnapshot,
    *,
    target_kind: str,
) -> tuple[str, tuple[ConfiguredQuantumRoute, ...]]:
    """Select one target and normalize its static routing from configuration."""

    target = config.domain_target
    if target is None:
        raise ValueError("quantum configuration requires a domain target")
    if target.kind != target_kind:
        raise ValueError(
            f"configured target kind {target.kind!r} is not {target_kind!r}"
        )
    instrument_ids = set(target.instrument_ids)
    routes: list[ConfiguredQuantumRoute] = []
    for binding in config.routing.bindings:
        if binding.instrument_id not in instrument_ids:
            continue
        if binding.entity_id is None or binding.channel_id is None:
            continue
        entity = config.topology.entity(binding.entity_id)
        if entity is None or entity.kind is None:
            raise ValueError(
                f"quantum route requires a typed entity {binding.entity_id!r}"
            )
        routes.append(
            ConfiguredQuantumRoute(
                instrument_id=binding.instrument_id,
                interface_id=binding.interface_id,
                entity_id=binding.entity_id,
                entity_kind=entity.kind,
                channel_id=binding.channel_id,
            )
        )
    if not routes:
        raise ValueError("configured quantum target has no routed endpoints")
    return target.id, tuple(routes)


def configured_output_signal(
    route: ConfiguredQuantumRoute,
) -> DriveSignal | ReadoutSignal | None:
    """Project one configured route into a logical pulse-output signal."""

    if route.entity_kind == "logical_qubit":
        qubit = QubitId(route.entity_id)
        if route.interface_id == PLAY_PULSE_PROGRAM.interface_id:
            return DriveSignal(qubit)
        if route.interface_id == READOUT_PULSE.interface_id:
            return ReadoutSignal(qubit)
    return None


def configured_acquisition_signal(
    route: ConfiguredQuantumRoute,
) -> AcquireSignal | None:
    """Project one configured route into a logical acquisition signal."""

    if (
        route.interface_id == ACQUIRE_IQ.interface_id
        and route.entity_kind == "logical_qubit"
    ):
        return AcquireSignal(QubitId(route.entity_id))
    return None


__all__ = [
    "FAKE_LIST_TARGET_KIND",
    "ConfiguredQuantumRoute",
    "configured_acquisition_signal",
    "configured_output_signal",
    "configured_quantum_routes",
]
