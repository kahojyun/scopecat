"""Default laboratory configuration for the fake list-mode target."""

from __future__ import annotations

from scopecat.records.config import ConfigProfileSnapshot
from scopecat_quantum._ids import TargetId

from reference_lab.targets.configuration import (
    DRIVE_I_ROLE,
    DRIVE_Q_ROLE,
    LIST_MODE_TARGET_KIND,
    READOUT_I_ROLE,
    READOUT_Q_ROLE,
    ConfiguredQuantumRoute,
    configured_acquisition_signal,
    configured_output_signal,
    configured_quantum_routes,
)
from reference_lab.targets.fake_list_mode.model import (
    FakeAcquisitionBinding,
    FakeAwgChannelId,
    FakeDigitizerChannelId,
    FakeListTarget,
    FakeOutputBinding,
    FakeOutputSignal,
    signal_key,
)


def configured_fake_list_target(config: ConfigProfileSnapshot) -> FakeListTarget:
    """Build list-mode physical bindings from one accepted system snapshot."""

    target_id, routes = configured_quantum_routes(
        config,
        target_kind=LIST_MODE_TARGET_KIND,
    )
    output_bindings = _configured_output_bindings(routes)
    acquisition_bindings = tuple(
        FakeAcquisitionBinding(
            signal,
            FakeDigitizerChannelId(route.endpoint_id),
        )
        for route in routes
        if (signal := configured_acquisition_signal(route)) is not None
    )
    return _fake_list_target(
        target_id=target_id,
        output_bindings=output_bindings,
        acquisition_bindings=acquisition_bindings,
    )


def _configured_output_bindings(
    routes: tuple[ConfiguredQuantumRoute, ...],
) -> tuple[FakeOutputBinding, ...]:
    selected: dict[
        tuple[str, str, str],
        tuple[FakeOutputSignal, dict[str, FakeAwgChannelId]],
    ] = {}
    for route in routes:
        signal = configured_output_signal(route)
        if signal is None or route.role_id is None:
            continue
        key = signal_key(signal)
        bound_signal, channels = selected.setdefault(key, (signal, {}))
        channels[route.role_id] = FakeAwgChannelId(route.endpoint_id)
        selected[key] = (bound_signal, channels)

    bindings: list[FakeOutputBinding] = []
    for signal, channels in selected.values():
        i_role, q_role = (
            (DRIVE_I_ROLE, DRIVE_Q_ROLE)
            if signal_key(signal)[0] == "drive"
            else (READOUT_I_ROLE, READOUT_Q_ROLE)
        )
        bindings.append(
            FakeOutputBinding(
                signal=signal,
                i_channel_id=channels[i_role],
                q_channel_id=channels[q_role],
            )
        )
    return tuple(bindings)


def _fake_list_target(
    *,
    target_id: str,
    output_bindings: tuple[FakeOutputBinding, ...],
    acquisition_bindings: tuple[FakeAcquisitionBinding, ...],
) -> FakeListTarget:
    return FakeListTarget(
        id=TargetId(target_id),
        sample_rate_hz=1_000_000_000,
        max_list_entries=256,
        max_samples_per_entry=1_000_000,
        max_repetitions=100_000,
        max_abs_amplitude=1.0,
        output_bindings=output_bindings,
        acquisition_bindings=acquisition_bindings,
    )


__all__ = ["configured_fake_list_target"]
