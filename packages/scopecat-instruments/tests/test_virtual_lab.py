from __future__ import annotations

from scopecat.kernel.quantity import Quantity

from scopecat_instruments import (
    LinearSweepSettings,
    VirtualDcSource,
    VirtualLabWorld,
    VirtualNetworkAnalyzer,
)


def _notch_frequency(
    trace_frequencies: tuple[float, ...],
    values: tuple[complex, ...],
) -> float:
    index = min(range(len(values)), key=lambda selected: abs(values[selected]))
    return trace_frequencies[index]


def test_virtual_state_survives_driver_session_close() -> None:
    world = VirtualLabWorld(seed=11)
    first = VirtualDcSource("flux", world)
    first.set_voltage_level(0.125)
    first.set_output(True)
    first.close()

    second = VirtualDcSource("flux", world)

    assert second.output_enabled() is True
    assert world.flux_bias() == 0.5
    level = {
        field.field_path: field.value.root for field in second.read_state().fields
    }["voltage_level"]
    assert isinstance(level, Quantity)
    assert level.value == 0.125


def test_virtual_network_noise_is_deterministic_for_seed() -> None:
    settings = LinearSweepSettings(
        start_frequency_hz=4.9e9,
        stop_frequency_hz=5.1e9,
        points=101,
        if_bandwidth_hz=1.0e3,
        source_power_dbm=-30.0,
        s_parameter="S21",
    )
    first = VirtualNetworkAnalyzer("vna", VirtualLabWorld(seed=23))
    second = VirtualNetworkAnalyzer("vna", VirtualLabWorld(seed=23))
    first.configure_linear_sweep(settings)
    second.configure_linear_sweep(settings)

    assert first.acquire_trace() == second.acquire_trace()


def test_flux_moves_notch_and_temperature_broadens_response() -> None:
    world = VirtualLabWorld(seed=7)
    vna = VirtualNetworkAnalyzer("vna", world)
    vna.configure_linear_sweep(
        LinearSweepSettings(
            start_frequency_hz=4.9e9,
            stop_frequency_hz=5.1e9,
            points=401,
            if_bandwidth_hz=1.0,
            source_power_dbm=-30.0,
            s_parameter="S21",
        )
    )
    baseline = vna.acquire_trace()

    dc = VirtualDcSource("flux", world)
    dc.set_voltage_level(0.125)
    dc.set_output(True)
    flux_shifted = vna.acquire_trace()

    baseline_notch = _notch_frequency(
        baseline.frequencies_hz,
        baseline.values,
    )
    shifted_notch = _notch_frequency(
        flux_shifted.frequencies_hz,
        flux_shifted.values,
    )
    assert abs(shifted_notch - baseline_notch) > 20.0e6

    cold_count = sum(abs(value) < 0.9 for value in flux_shifted.values)
    world.set_base_temperature(0.2)
    hot = vna.acquire_trace()
    hot_count = sum(abs(value) < 0.9 for value in hot.values)
    assert hot_count > cold_count
