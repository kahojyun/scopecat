"""Default laboratory configuration for the fake list-mode target."""

from __future__ import annotations

from scopecat.records.config import ConfigProfileSnapshot
from scopecat_quantum._ids import TargetId

from quantum_lab_demo.targets.configuration import (
    FAKE_LIST_TARGET_KIND,
    configured_acquisition_signal,
    configured_output_signal,
    configured_quantum_routes,
)
from quantum_lab_demo.targets.fake_list_mode.model import (
    FakeAcquisitionBinding,
    FakeAwgChannelId,
    FakeDigitizerChannelId,
    FakeListTarget,
    FakeOutputBinding,
)


def configured_fake_list_target(config: ConfigProfileSnapshot) -> FakeListTarget:
    """Build list-mode physical bindings from one accepted system snapshot."""

    target_id, routes = configured_quantum_routes(
        config,
        target_kind=FAKE_LIST_TARGET_KIND,
    )
    output_bindings = tuple(
        FakeOutputBinding(signal, FakeAwgChannelId(route.endpoint_id))
        for route in routes
        if (signal := configured_output_signal(route)) is not None
    )
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
