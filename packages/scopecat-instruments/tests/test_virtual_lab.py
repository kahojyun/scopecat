from __future__ import annotations

from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments import (
    DriverApplyRequest,
    DriverCollectRequest,
    DriverCollectResult,
    DriverPropertyWrite,
)

from scopecat_instruments._support import (
    LinearSweepSettings,
    state_properties_by_target,
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
)
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


def test_virtual_state_survives_driver_disconnect() -> None:
    world = VirtualLabWorld(seed=11)
    first = VirtualDcSource("flux", world)
    first.set_voltage_level(0.125)
    first.set_output(True)
    first.disconnect()

    second = VirtualDcSource("flux", world)

    assert second.output_enabled() is True
    assert world.flux_bias() == 0.5
    level = state_properties_by_target(second.read_state())[
        DC_SOURCE_VOLTAGE_LEVEL
    ].value.root
    assert isinstance(level, Quantity)
    assert level.value == 0.125


def test_virtual_dc_current_case_drives_physics_and_snapshot_shape() -> None:
    world = VirtualLabWorld(seed=13)
    driver = VirtualDcSource("flux", world)

    receipt = driver.apply_state(
        DriverApplyRequest(
            assignments=(
                DriverPropertyWrite(
                    interface_id=DC_SOURCE_MODE.interface_id,
                    component_path=DC_SOURCE_MODE.component_path,
                    property_id=DC_SOURCE_MODE.property_id,
                    value=StateValue("current"),
                ),
                DriverPropertyWrite(
                    interface_id=DC_SOURCE_CURRENT_RANGE.interface_id,
                    component_path=DC_SOURCE_CURRENT_RANGE.component_path,
                    property_id=DC_SOURCE_CURRENT_RANGE.property_id,
                    value=StateValue(Quantity(0.01, "A")),
                ),
                DriverPropertyWrite(
                    interface_id=DC_SOURCE_CURRENT_LEVEL.interface_id,
                    component_path=DC_SOURCE_CURRENT_LEVEL.component_path,
                    property_id=DC_SOURCE_CURRENT_LEVEL.property_id,
                    value=StateValue(Quantity(0.001, "A")),
                ),
                DriverPropertyWrite(
                    interface_id=DC_SOURCE_OUTPUT_ENABLED.interface_id,
                    component_path=DC_SOURCE_OUTPUT_ENABLED.component_path,
                    property_id=DC_SOURCE_OUTPUT_ENABLED.property_id,
                    value=StateValue(True),
                ),
            ),
        )
    )

    assert receipt.status == "applied"
    assert receipt.state is not None
    property_targets = state_properties_by_target(receipt.state)
    assert {
        DC_SOURCE_CURRENT_RANGE,
        DC_SOURCE_CURRENT_LEVEL,
    } <= property_targets.keys()
    assert {
        DC_SOURCE_VOLTAGE_RANGE,
        DC_SOURCE_VOLTAGE_LEVEL,
    }.isdisjoint(property_targets)
    assert world.flux_bias() == 0.5


def test_virtual_dc_case_local_setters_do_not_switch_mode() -> None:
    driver = VirtualDcSource("flux", VirtualLabWorld(seed=13))

    driver.set_current_range(0.01)
    driver.set_current_level(0.001)

    assert driver.source_mode() == "voltage"


def test_virtual_dc_monitor_configuration_round_trips_through_state() -> None:
    driver = VirtualDcSource("flux", VirtualLabWorld(seed=13))

    receipt = driver.apply_state(
        DriverApplyRequest(
            assignments=(
                DriverPropertyWrite(
                    interface_id=DC_MONITOR_MEASUREMENT_ENABLED.interface_id,
                    component_path=DC_MONITOR_MEASUREMENT_ENABLED.component_path,
                    property_id=DC_MONITOR_MEASUREMENT_ENABLED.property_id,
                    value=StateValue(False),
                ),
                DriverPropertyWrite(
                    interface_id=DC_MONITOR_INTEGRATION_CYCLES.interface_id,
                    component_path=DC_MONITOR_INTEGRATION_CYCLES.component_path,
                    property_id=DC_MONITOR_INTEGRATION_CYCLES.property_id,
                    value=StateValue(5),
                ),
                DriverPropertyWrite(
                    interface_id=DC_MONITOR_MEASUREMENT_DELAY.interface_id,
                    component_path=DC_MONITOR_MEASUREMENT_DELAY.component_path,
                    property_id=DC_MONITOR_MEASUREMENT_DELAY.property_id,
                    value=StateValue(Quantity(0.25, "s")),
                ),
            )
        )
    )

    assert receipt.status == "applied"
    assert receipt.state is not None
    properties = state_properties_by_target(receipt.state)
    assert properties[DC_MONITOR_MEASUREMENT_ENABLED].value.root is False
    assert properties[DC_MONITOR_INTEGRATION_CYCLES].value.root == 5
    delay = properties[DC_MONITOR_MEASUREMENT_DELAY].value.root
    assert isinstance(delay, Quantity)
    assert delay == Quantity(0.25, "s")


def test_virtual_dc_monitor_requires_source_output_and_measurement_enabled() -> None:
    driver = VirtualDcSource("flux", VirtualLabWorld(seed=13))
    request = DriverCollectRequest(
        interface_id=DC_MONITOR_ACQUISITION.interface_id,
        component_path=DC_MONITOR_ACQUISITION.component_path,
        acquisition_id=DC_MONITOR_ACQUISITION.acquisition_id,
        results=(
            DriverCollectResult(
                request_id="current",
                result_id=DC_MONITOR_CURRENT_RESULT.result_id,
            ),
        ),
    )

    driver.set_output(True)
    assert driver.collect(request).status == "collected"

    driver.set_output(False)
    receipt = driver.collect(request)

    assert receipt.status == "not_collected"
    assert receipt.problems[0].code == "virtual_dc_monitor_output_disabled"

    driver.set_output(True)
    driver.set_measurement_enabled(False)
    receipt = driver.collect(request)

    assert receipt.status == "not_collected"
    assert receipt.problems[0].code == "virtual_dc_monitor_disabled"


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
