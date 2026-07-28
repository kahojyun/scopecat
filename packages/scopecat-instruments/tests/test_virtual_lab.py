from __future__ import annotations

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments import (
    InstrumentStateAssignment,
    InstrumentStateCommand,
)

from scopecat_instruments._support import LinearSweepSettings
from scopecat_instruments.interfaces import DC_SOURCE
from scopecat_instruments.virtual import (
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
        property_state.property_id: property_state.value.root
        for property_state in second.read_state().properties
    }["voltage_level"]
    assert isinstance(level, Quantity)
    assert level.value == 0.125


def test_virtual_dc_current_case_drives_physics_and_snapshot_shape() -> None:
    world = VirtualLabWorld(seed=13)
    driver = VirtualDcSource("flux", world)

    receipt = driver.apply_state(
        InstrumentStateCommand(
            instrument_id="flux",
            assignments=[
                InstrumentStateAssignment(
                    resource_id="flux",
                    interface_id=DC_SOURCE,
                    property_id="source_mode",
                    value=StateValue("current"),
                ),
                InstrumentStateAssignment(
                    resource_id="flux",
                    interface_id=DC_SOURCE,
                    property_id="current_range",
                    value=StateValue(Quantity(0.01, "A")),
                ),
                InstrumentStateAssignment(
                    resource_id="flux",
                    interface_id=DC_SOURCE,
                    property_id="current_level",
                    value=StateValue(Quantity(0.001, "A")),
                ),
                InstrumentStateAssignment(
                    resource_id="flux",
                    interface_id=DC_SOURCE,
                    property_id="output_enabled",
                    value=StateValue(True),
                ),
            ],
        )
    )

    assert receipt.status == "applied"
    assert receipt.state is not None
    property_ids = {
        property_state.property_id for property_state in receipt.state.properties
    }
    assert {"current_range", "current_level"} <= property_ids
    assert {"voltage_range", "voltage_level"}.isdisjoint(property_ids)
    assert world.flux_bias() == 0.5


def test_virtual_dc_case_local_setters_do_not_switch_mode() -> None:
    driver = VirtualDcSource("flux", VirtualLabWorld(seed=13))

    driver.set_current_range(0.01)
    driver.set_current_level(0.001)

    assert driver.source_mode() == "voltage"


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
