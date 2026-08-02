from __future__ import annotations

from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments import (
    DriverAcquisition,
    DriverRejected,
    DriverStatePatch,
    DriverSuccess,
)

from scopecat_instruments._support import LinearSweepSettings
from scopecat_instruments.driver_handlers import (
    DCSourceMonitorDriverAdapter,
    NetworkSweepDriverAdapter,
    RFOutputDriverAdapter,
    TemperatureReadoutDriverAdapter,
)
from scopecat_instruments.members import (
    DC_MONITOR_ACQUISITION,
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_INTEGRATION_CYCLES,
    DC_MONITOR_MEASUREMENT_DELAY,
    DC_MONITOR_MEASUREMENT_ENABLED,
    DC_SOURCE_CURRENT_LEVEL,
    DC_SOURCE_CURRENT_RANGE,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP_POINTS,
    NETWORK_SWEEP_S_PARAMETER,
    RF_OUTPUT_ENABLED,
    RF_OUTPUT_FREQUENCY,
    TEMPERATURE_READOUT_RESISTANCE_RESULT,
    TEMPERATURE_READOUT_SAMPLE,
    TEMPERATURE_READOUT_TEMPERATURE_RESULT,
)
from scopecat_instruments.virtual import (
    VirtualDcSource,
    VirtualLabWorld,
    VirtualNetworkAnalyzer,
    VirtualRfSource,
    VirtualTemperatureMonitor,
)


def _notch_frequency(
    trace_frequencies: tuple[float, ...],
    values: tuple[complex, ...],
) -> float:
    index = min(range(len(values)), key=lambda selected: abs(values[selected]))
    return trace_frequencies[index]


def test_virtual_drivers_use_generated_adapters() -> None:
    assert issubclass(VirtualRfSource, RFOutputDriverAdapter)
    assert issubclass(VirtualDcSource, DCSourceMonitorDriverAdapter)
    assert issubclass(VirtualTemperatureMonitor, TemperatureReadoutDriverAdapter)
    assert issubclass(VirtualNetworkAnalyzer, NetworkSweepDriverAdapter)


def test_virtual_state_survives_driver_disconnect() -> None:
    world = VirtualLabWorld(seed=11)
    first = VirtualDcSource("flux", world)
    first.set_voltage_level(0.125)
    first.set_output(True)
    first.disconnect()

    second = VirtualDcSource("flux", world)

    assert second.output_enabled() is True
    assert world.flux_bias() == 0.5
    level = second.read_state().values[DC_SOURCE_VOLTAGE_LEVEL]
    assert isinstance(level, Quantity)
    assert level.value == 0.125


def test_virtual_rf_driver_applies_typed_sparse_patch() -> None:
    driver = VirtualRfSource("readout-lo", VirtualLabWorld(seed=12))
    driver.set_output(True)

    receipt = driver.apply_state(
        DriverStatePatch(
            values={
                RF_OUTPUT_FREQUENCY: Quantity(6.0e9, "Hz"),
                RF_OUTPUT_ENABLED: False,
            }
        )
    )

    assert isinstance(receipt, DriverSuccess)
    assert receipt.value is None
    state = driver.read_state()
    assert state.values[RF_OUTPUT_FREQUENCY] == Quantity(6.0e9, "Hz")
    assert state.values[RF_OUTPUT_ENABLED] is False


def test_virtual_dc_current_case_drives_physics_and_snapshot_shape() -> None:
    world = VirtualLabWorld(seed=13)
    driver = VirtualDcSource("flux", world)
    driver.set_output(True)

    receipt = driver.apply_state(
        DriverStatePatch(
            values={
                DC_SOURCE_MODE: "current",
                DC_SOURCE_CURRENT_RANGE: Quantity(0.01, "A"),
                DC_SOURCE_CURRENT_LEVEL: Quantity(0.001, "A"),
                DC_MONITOR_INTEGRATION_CYCLES: 5,
                RF_OUTPUT_FREQUENCY: Quantity(6.0e9, "Hz"),
            },
        )
    )

    assert isinstance(receipt, DriverSuccess)
    assert receipt.value is None
    property_targets = driver.read_state().values
    assert {
        DC_SOURCE_CURRENT_RANGE,
        DC_SOURCE_CURRENT_LEVEL,
    } <= property_targets.keys()
    assert {
        DC_SOURCE_VOLTAGE_RANGE,
        DC_SOURCE_VOLTAGE_LEVEL,
    }.isdisjoint(property_targets)
    assert property_targets[DC_SOURCE_OUTPUT_ENABLED] is True
    assert property_targets[DC_MONITOR_INTEGRATION_CYCLES] == 5
    assert RF_OUTPUT_FREQUENCY not in property_targets
    assert world.flux_bias() == 0.5


def test_virtual_dc_case_local_setters_do_not_switch_mode() -> None:
    driver = VirtualDcSource("flux", VirtualLabWorld(seed=13))

    driver.set_current_range(0.01)
    driver.set_current_level(0.001)

    assert driver.source_mode() == "voltage"


def test_virtual_dc_monitor_configuration_round_trips_through_state() -> None:
    driver = VirtualDcSource("flux", VirtualLabWorld(seed=13))

    receipt = driver.apply_state(
        DriverStatePatch(
            values={
                DC_MONITOR_MEASUREMENT_ENABLED: False,
                DC_MONITOR_INTEGRATION_CYCLES: 5,
                DC_MONITOR_MEASUREMENT_DELAY: Quantity(0.25, "s"),
            }
        )
    )

    assert isinstance(receipt, DriverSuccess)
    assert receipt.value is None
    properties = driver.read_state().values
    assert properties[DC_MONITOR_MEASUREMENT_ENABLED] is False
    assert properties[DC_MONITOR_INTEGRATION_CYCLES] == 5
    delay = properties[DC_MONITOR_MEASUREMENT_DELAY]
    assert isinstance(delay, Quantity)
    assert delay == Quantity(0.25, "s")


def test_virtual_dc_monitor_requires_source_output_and_measurement_enabled() -> None:
    driver = VirtualDcSource("flux", VirtualLabWorld(seed=13))
    request = DriverAcquisition(
        target=DC_MONITOR_ACQUISITION,
        results=frozenset({DC_MONITOR_CURRENT_RESULT}),
    )

    driver.set_output(True)
    assert isinstance(driver.collect(request), DriverSuccess)

    driver.set_output(False)
    receipt = driver.collect(request)

    assert isinstance(receipt, DriverRejected)
    assert receipt.problems[0].code == "virtual_dc_monitor_output_disabled"

    driver.set_output(True)
    driver.set_measurement_enabled(False)
    receipt = driver.collect(request)

    assert isinstance(receipt, DriverRejected)
    assert receipt.problems[0].code == "virtual_dc_monitor_disabled"


def test_virtual_temperature_adapter_preserves_readback_metadata() -> None:
    driver = VirtualTemperatureMonitor("mixing-chamber", VirtualLabWorld(seed=19))

    receipt = driver.collect(
        DriverAcquisition(
            target=TEMPERATURE_READOUT_SAMPLE,
            results=frozenset(
                {
                    TEMPERATURE_READOUT_TEMPERATURE_RESULT,
                    TEMPERATURE_READOUT_RESISTANCE_RESULT,
                }
            ),
        )
    )

    assert isinstance(receipt, DriverSuccess)
    assert set(receipt.value.values) == {
        TEMPERATURE_READOUT_TEMPERATURE_RESULT,
        TEMPERATURE_READOUT_RESISTANCE_RESULT,
    }
    assert receipt.value.metadata == {
        "mode": "virtual",
        "world_seed": 19,
        "scan_channel": 1,
        "autoscan_enabled": False,
        "reading_status": 0,
    }
    assert driver.read_state().metadata == {"mode": "virtual", "world_seed": 19}


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


def test_virtual_network_analyzer_applies_typed_sparse_patch() -> None:
    driver = VirtualNetworkAnalyzer("vna", VirtualLabWorld(seed=23))

    receipt = driver.apply_state(
        DriverStatePatch(
            values={
                NETWORK_SWEEP_S_PARAMETER: "S11",
                NETWORK_SWEEP_POINTS: 17,
                RF_OUTPUT_FREQUENCY: Quantity(6.0e9, "Hz"),
            }
        )
    )

    assert isinstance(receipt, DriverSuccess)
    assert receipt.value is None
    state = driver.read_state()
    assert state.values[NETWORK_SWEEP_S_PARAMETER] == "S11"
    assert state.values[NETWORK_SWEEP_POINTS] == 17
    assert RF_OUTPUT_FREQUENCY not in state.values


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
