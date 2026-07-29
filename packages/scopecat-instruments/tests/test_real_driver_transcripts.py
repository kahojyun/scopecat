from __future__ import annotations

import pytest
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.records.measurement import MeasurementScalar
from scopecat.sdk.instruments import (
    AcquisitionRef,
    AcquisitionResultRef,
    DriverApplyRequest,
    DriverCollectRequest,
    DriverCollectResult,
    DriverPropertyWrite,
    PropertyRef,
)

from scopecat_instruments._support import (
    LinearSweepSettings,
    state_properties_by_target,
)
from scopecat_instruments.drivers import (
    KeysightE5080B,
    LakeShore372,
    RohdeSchwarzSGS100A,
    YokogawaGS200,
)
from scopecat_instruments.members import (
    DC_MONITOR_ACQUISITION,
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_VOLTAGE_RESULT,
    DC_SOURCE_CURRENT_LEVEL,
    DC_SOURCE_CURRENT_PROTECTION,
    DC_SOURCE_CURRENT_RANGE,
    DC_SOURCE_MODE,
    DC_SOURCE_OUTPUT_ENABLED,
    DC_SOURCE_VOLTAGE_LEVEL,
    DC_SOURCE_VOLTAGE_RANGE,
    NETWORK_SWEEP_ACQUISITION,
    NETWORK_SWEEP_S_PARAMETER_RESULT,
    RF_OUTPUT_ENABLED,
    RF_OUTPUT_FREQUENCY,
    RF_OUTPUT_POWER,
    RF_OUTPUT_REFERENCE_SOURCE,
    TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    TEMPERATURE_READOUT_RESISTANCE_RESULT,
    TEMPERATURE_READOUT_SAMPLE,
    TEMPERATURE_READOUT_SCAN_CHANNEL,
    TEMPERATURE_READOUT_TEMPERATURE_RESULT,
)
from scopecat_instruments.testing import ScriptedExchange, ScriptedTransport


def _apply_request(
    properties: list[tuple[PropertyRef, bool | str | Quantity]],
) -> DriverApplyRequest:
    return DriverApplyRequest(
        assignments=tuple(
            DriverPropertyWrite(
                interface_id=target.interface_id,
                component_path=target.component_path,
                property_id=target.property_id,
                value=StateValue(value),
            )
            for target, value in properties
        ),
    )


def _collect_request(
    acquisition: AcquisitionRef,
    *results: AcquisitionResultRef,
) -> DriverCollectRequest:
    return DriverCollectRequest(
        interface_id=acquisition.interface_id,
        component_path=acquisition.component_path,
        acquisition_id=acquisition.acquisition_id,
        results=tuple(
            DriverCollectResult(
                request_id=result.result_id,
                result_id=result.result_id,
            )
            for result in results
        ),
    )


def _gs200_state_readback(
    *,
    mode: str,
    source_range: str,
    source_level: str,
    output_enabled: bool,
    voltage_protection: str = "10",
    current_protection: str = "0.01",
) -> list[ScriptedExchange]:
    return [
        ScriptedExchange.query(":SOUR:FUNC?", mode),
        ScriptedExchange.query(":SOUR:RANG?", source_range),
        ScriptedExchange.query(":SOUR:LEV?", source_level),
        ScriptedExchange.query(":SOUR:PROT:VOLT?", voltage_protection),
        ScriptedExchange.query(":SOUR:PROT:CURR?", current_protection),
        ScriptedExchange.query(":OUTP?", "1" if output_enabled else "0"),
    ]


def _sgs100a_state_readback(
    *,
    frequency_with_offset: str = "5.020000000000E+09",
    frequency_offset: str = "2.000000000000E+07",
    power: str = "-2.750000000000E+01",
    output_enabled: bool,
    reference_source: str = "EXT",
) -> list[ScriptedExchange]:
    return [
        ScriptedExchange.query(":SOUR:OPM?", "NORM"),
        ScriptedExchange.query(":SOUR:IQ:STAT?", "OFF"),
        ScriptedExchange.query(":SOUR:PULM:STAT?", "OFF"),
        ScriptedExchange.query(":SOUR:FREQ?", frequency_with_offset),
        ScriptedExchange.query(":SOUR:FREQ:OFFS?", frequency_offset),
        ScriptedExchange.query(":SOUR:POW:POW?", power),
        ScriptedExchange.query(":OUTP?", "ON" if output_enabled else "OFF"),
        ScriptedExchange.query(":SOUR:ROSC:SOUR?", reference_source),
    ]


def test_gs200_source_and_monitor_transcript() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(
                "*IDN?",
                "YOKOGAWA,GS210,91X000001,2.03",
            ),
            ScriptedExchange.write(":SOUR:FUNC VOLT"),
            ScriptedExchange.write(":SOUR:RANG 1"),
            ScriptedExchange.write(":SOUR:LEV 0.125"),
            ScriptedExchange.write(":SOUR:PROT:VOLT 12"),
            ScriptedExchange.write(":SOUR:PROT:CURR 0.01"),
            ScriptedExchange.write(":OUTP ON"),
            ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
            ScriptedExchange.query(":SOUR:RANG?", "+1.000000E+00"),
            ScriptedExchange.query(":SOUR:LEV?", "+1.250000E-01"),
            ScriptedExchange.query(":SOUR:PROT:VOLT?", "+1.200000E+01"),
            ScriptedExchange.query(":SOUR:PROT:CURR?", "+1.000000E-02"),
            ScriptedExchange.query(":OUTP?", "1"),
            ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
            ScriptedExchange.query(":MEAS?", "+1.250000E-04"),
        ]
    )
    driver = YokogawaGS200("bias", transport, monitor_option=True)

    identity = driver.identify()
    driver.set_source_mode("voltage")
    driver.set_source_range(1.0)
    driver.set_source_level(0.125)
    driver.set_voltage_protection(12.0)
    driver.set_current_protection(0.01)
    driver.set_output(True)
    state = driver.read_state()
    receipt = driver.collect(
        _collect_request(
            DC_MONITOR_ACQUISITION,
            DC_MONITOR_CURRENT_RESULT,
        )
    )

    assert identity.model == "GS210"
    assert state.metadata["identity"] == identity.raw
    assert receipt.status == "collected"
    assert receipt.readback is not None
    measured = receipt.readback.values[DC_MONITOR_CURRENT_RESULT.result_id]
    assert isinstance(measured, MeasurementScalar)
    assert measured.value == pytest.approx(1.25e-4)
    transport.assert_complete()


@pytest.mark.parametrize(
    "target_output",
    [False, True],
    ids=["leave-disabled", "restore-enabled"],
)
def test_gs200_apply_disables_live_output_while_switching_state(
    target_output: bool,
) -> None:
    writes = [
        ScriptedExchange.write(":OUTP OFF"),
        ScriptedExchange.write(":SOUR:FUNC VOLT"),
        ScriptedExchange.write(":SOUR:RANG 1"),
        ScriptedExchange.write(":SOUR:LEV 0.125"),
    ]
    if target_output:
        writes.append(ScriptedExchange.write(":OUTP ON"))
    transport = ScriptedTransport(
        [
            *_gs200_state_readback(
                mode="CURR",
                source_range="0.01",
                source_level="0.001",
                output_enabled=True,
            ),
            *writes,
            *_gs200_state_readback(
                mode="VOLT",
                source_range="1",
                source_level="0.125",
                output_enabled=target_output,
            ),
        ]
    )
    driver = YokogawaGS200("bias", transport)

    receipt = driver.apply_state(
        _apply_request(
            [
                (DC_SOURCE_MODE, "voltage"),
                (DC_SOURCE_VOLTAGE_RANGE, Quantity(1.0, "V")),
                (DC_SOURCE_VOLTAGE_LEVEL, Quantity(0.125, "V")),
                (DC_SOURCE_OUTPUT_ENABLED, target_output),
            ],
        )
    )

    assert receipt.status == "applied"
    transport.assert_complete()


def test_gs200_applies_and_monitors_current_source_case() -> None:
    transport = ScriptedTransport(
        [
            *_gs200_state_readback(
                mode="VOLT",
                source_range="1",
                source_level="0",
                output_enabled=False,
            ),
            ScriptedExchange.write(":SOUR:FUNC CURR"),
            ScriptedExchange.write(":SOUR:RANG 0.01"),
            ScriptedExchange.write(":SOUR:LEV 0.001"),
            ScriptedExchange.write(":OUTP ON"),
            *_gs200_state_readback(
                mode="CURR",
                source_range="0.01",
                source_level="0.001",
                output_enabled=True,
            ),
            ScriptedExchange.query(":SOUR:FUNC?", "CURR"),
            ScriptedExchange.query(":MEAS?", "1"),
        ]
    )
    driver = YokogawaGS200("bias", transport, monitor_option=True)

    applied = driver.apply_state(
        _apply_request(
            [
                (DC_SOURCE_MODE, "current"),
                (DC_SOURCE_CURRENT_RANGE, Quantity(0.01, "A")),
                (DC_SOURCE_CURRENT_LEVEL, Quantity(0.001, "A")),
                (DC_SOURCE_OUTPUT_ENABLED, True),
            ],
        )
    )
    monitored = driver.collect(
        _collect_request(
            DC_MONITOR_ACQUISITION,
            DC_MONITOR_VOLTAGE_RESULT,
        )
    )

    assert applied.status == "applied"
    assert monitored.status == "collected"
    assert monitored.readback is not None
    assert monitored.readback.values[
        DC_MONITOR_VOLTAGE_RESULT.result_id
    ] == MeasurementScalar.create(
        dtype="float64",
        value=1.0,
        unit="V",
    )
    transport.assert_complete()


def test_gs200_adjusts_compliance_without_interrupting_live_output() -> None:
    transport = ScriptedTransport(
        [
            *_gs200_state_readback(
                mode="VOLT",
                source_range="1",
                source_level="0.125",
                output_enabled=True,
            ),
            ScriptedExchange.write(":SOUR:PROT:CURR 0.005"),
            *_gs200_state_readback(
                mode="VOLT",
                source_range="1",
                source_level="0.125",
                output_enabled=True,
                current_protection="0.005",
            ),
        ]
    )
    driver = YokogawaGS200("bias", transport)

    receipt = driver.apply_state(
        _apply_request(
            [(DC_SOURCE_CURRENT_PROTECTION, Quantity(0.005, "A"))],
        )
    )

    assert receipt.status == "applied"
    transport.assert_complete()


def test_sgs100a_cw_source_transcript() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(
                "*IDN?",
                "Rohde&Schwarz,SGS100A,1419.5505k02/100001,5.00",
            ),
            ScriptedExchange.write(":SOUR:FREQ 5000000000"),
            ScriptedExchange.write(":SOUR:POW:POW -27.5"),
            ScriptedExchange.write(":SOUR:ROSC:SOUR EXT"),
            ScriptedExchange.write(":OUTP ON"),
            *_sgs100a_state_readback(output_enabled=True),
        ]
    )
    driver = RohdeSchwarzSGS100A("readout-lo", transport)

    driver.identify()
    driver.set_frequency(5.0e9)
    driver.set_power(-27.5)
    driver.set_reference_source("external")
    driver.set_output(True)
    state = driver.read_state()

    properties = state_properties_by_target(state)
    assert properties[RF_OUTPUT_FREQUENCY].value.root == Quantity(5.0e9, "Hz")
    assert properties[RF_OUTPUT_POWER].value.root == Quantity(-27.5, "dBm")
    assert properties[RF_OUTPUT_REFERENCE_SOURCE].value.root == "external"
    assert properties[RF_OUTPUT_ENABLED].value.root is True
    transport.assert_complete()


@pytest.mark.parametrize("enabled", [False, True], ids=["disable-first", "enable-last"])
def test_sgs100a_apply_orders_output_around_frequency_and_power(
    enabled: bool,
) -> None:
    initially_enabled = not enabled
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(
                ":OUTP?",
                "ON" if initially_enabled else "OFF",
            ),
            *([ScriptedExchange.write(":OUTP OFF")] if initially_enabled else []),
            ScriptedExchange.write(":SOUR:OPM NORM"),
            ScriptedExchange.write(":SOUR:IQ:STAT OFF"),
            ScriptedExchange.write(":SOUR:PULM:STAT OFF"),
            ScriptedExchange.write(":SOUR:FREQ 5000000000"),
            ScriptedExchange.write(":SOUR:POW:POW -27.5"),
            *([ScriptedExchange.write(":OUTP ON")] if enabled else []),
            *_sgs100a_state_readback(
                output_enabled=enabled,
                reference_source="INT",
            ),
        ]
    )
    driver = RohdeSchwarzSGS100A("readout-lo", transport)

    receipt = driver.apply_state(
        _apply_request(
            [
                (RF_OUTPUT_FREQUENCY, Quantity(5.0e9, "Hz")),
                (RF_OUTPUT_POWER, Quantity(-27.5, "dBm")),
                (RF_OUTPUT_ENABLED, enabled),
            ],
        )
    )

    assert receipt.status == "applied"
    transport.assert_complete()


@pytest.mark.parametrize(
    ("operation_mode", "iq_modulation", "pulse_modulation", "diagnostic"),
    [
        ("BBBY", "OFF", "OFF", "mode=BBBY"),
        ("NORM", "ON", "OFF", "iq_modulation=ON"),
        ("NORM", "OFF", "ON", "pulse_modulation=ON"),
    ],
)
def test_sgs100a_read_state_rejects_non_cw_hardware_without_writing(
    operation_mode: str,
    iq_modulation: str,
    pulse_modulation: str,
    diagnostic: str,
) -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(":SOUR:OPM?", operation_mode),
            ScriptedExchange.query(":SOUR:IQ:STAT?", iq_modulation),
            ScriptedExchange.query(":SOUR:PULM:STAT?", pulse_modulation),
        ]
    )
    driver = RohdeSchwarzSGS100A("readout-lo", transport)

    with pytest.raises(ValueError, match=diagnostic):
        driver.read_state()

    transport.assert_complete()


def test_lakeshore_372_state_contains_only_persistent_scanner_state() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(
                "*IDN?",
                "LSCI,MODEL372,LSA1234,1.4",
            ),
            ScriptedExchange.query("SCAN?", "5,1"),
        ]
    )
    driver = LakeShore372("fridge", transport)

    driver.identify()
    state = driver.read_state()

    properties = state_properties_by_target(state)
    assert set(properties) == {
        TEMPERATURE_READOUT_SCAN_CHANNEL,
        TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    }
    assert properties[TEMPERATURE_READOUT_SCAN_CHANNEL].value.root == 5
    assert properties[TEMPERATURE_READOUT_AUTOSCAN_ENABLED].value.root is True
    transport.assert_complete()


def test_lakeshore_372_collect_waits_for_one_coherent_valid_sample() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "5,1"),
            ScriptedExchange.query("RDGSTL?", "2,1"),
            ScriptedExchange.query("RDGSTL?", "2,0"),
            ScriptedExchange.query("SCAN?", "5,1"),
            ScriptedExchange.query("INCRV? 5", "21"),
            ScriptedExchange.query("KRDG? 5", "+2.050000E-02"),
            ScriptedExchange.query("SRDG? 5", "+6.720000E+03"),
            ScriptedExchange.query("RDGST? 5", "0"),
            ScriptedExchange.query("RDGSTL?", "2,0"),
            ScriptedExchange.query("SCAN?", "5,1"),
        ]
    )
    driver = LakeShore372("fridge", transport)

    receipt = driver.collect(
        _collect_request(
            TEMPERATURE_READOUT_SAMPLE,
            TEMPERATURE_READOUT_TEMPERATURE_RESULT,
            TEMPERATURE_READOUT_RESISTANCE_RESULT,
        )
    )

    assert receipt.status == "collected"
    assert receipt.readback is not None
    temperature = receipt.readback.values[
        TEMPERATURE_READOUT_TEMPERATURE_RESULT.result_id
    ]
    resistance = receipt.readback.values[
        TEMPERATURE_READOUT_RESISTANCE_RESULT.result_id
    ]
    assert isinstance(temperature, MeasurementScalar)
    assert isinstance(resistance, MeasurementScalar)
    assert temperature.value == pytest.approx(0.0205)
    assert resistance.value == pytest.approx(6720.0)
    assert receipt.readback.metadata["curve_number"] == 21
    transport.assert_complete()


def test_lakeshore_372_resistance_does_not_require_a_temperature_curve() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("SRDG? 5", "+6.720000E+03"),
            ScriptedExchange.query("RDGST? 5", "0"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,0"),
        ]
    )
    driver = LakeShore372("fridge", transport)

    receipt = driver.collect(
        _collect_request(
            TEMPERATURE_READOUT_SAMPLE,
            TEMPERATURE_READOUT_RESISTANCE_RESULT,
        )
    )

    assert receipt.status == "collected"
    assert receipt.readback is not None
    assert "curve_number" not in receipt.readback.metadata
    transport.assert_complete()


def test_lakeshore_372_retries_when_autoscan_changes_channel() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "4,1"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,1"),
            ScriptedExchange.query("SCAN?", "5,1"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,1"),
            ScriptedExchange.query("SRDG? 5", "+6.720000E+03"),
            ScriptedExchange.query("RDGST? 5", "0"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,1"),
        ]
    )
    driver = LakeShore372("fridge", transport)

    receipt = driver.collect(
        _collect_request(
            TEMPERATURE_READOUT_SAMPLE,
            TEMPERATURE_READOUT_RESISTANCE_RESULT,
        )
    )

    assert receipt.status == "collected"
    assert receipt.readback is not None
    assert receipt.readback.metadata["scan_channel"] == 5
    transport.assert_complete()


def test_lakeshore_372_temperature_without_curve_is_not_collected() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("INCRV? 5", "0"),
            ScriptedExchange.query("SCAN?", "5,0"),
        ]
    )
    driver = LakeShore372("fridge", transport)

    receipt = driver.collect(
        _collect_request(
            TEMPERATURE_READOUT_SAMPLE,
            TEMPERATURE_READOUT_TEMPERATURE_RESULT,
        )
    )

    assert receipt.status == "not_collected"
    assert receipt.problems[0].code == "lakeshore_temperature_curve_required"
    transport.assert_complete()


def test_lakeshore_372_invalid_reading_is_not_collected() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("SRDG? 5", "+1.000000E+08"),
            ScriptedExchange.query("RDGST? 5", "64"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,0"),
        ]
    )
    driver = LakeShore372("fridge", transport)

    receipt = driver.collect(
        _collect_request(
            TEMPERATURE_READOUT_SAMPLE,
            TEMPERATURE_READOUT_RESISTANCE_RESULT,
        )
    )

    assert receipt.status == "not_collected"
    assert receipt.problems[0].code == "lakeshore_reading_invalid"
    assert receipt.problems[0].details["reading_status"] == "64"
    transport.assert_complete()


def test_e5080b_linear_sweep_and_ascii_trace_transcript() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(
                "*IDN?",
                "Keysight Technologies,E5080B,MY12345678,A.20.10",
            ),
            ScriptedExchange.write("SENS1:SWE:TYPE LIN"),
            ScriptedExchange.write("SENS1:FREQ:STAR 4800000000"),
            ScriptedExchange.write("SENS1:FREQ:STOP 5200000000"),
            ScriptedExchange.write("SENS1:SWE:POIN 3"),
            ScriptedExchange.write("SENS1:BWID 1000"),
            ScriptedExchange.write("SOUR1:POW -30"),
            ScriptedExchange.write('CALC1:MEAS1:PAR "S21"'),
            ScriptedExchange.write("SENS1:SWE:TYPE LIN"),
            ScriptedExchange.query("TRIG:SOUR?", "IMM"),
            ScriptedExchange.write("TRIG:SOUR MAN"),
            ScriptedExchange.query("SENS1:AVER?", "ON"),
            ScriptedExchange.write("SENS1:AVER OFF"),
            ScriptedExchange.write("INIT1:IMM;*WAI"),
            ScriptedExchange.write("FORM:DATA ASC,0"),
            ScriptedExchange.query(
                "CALC1:MEAS1:X?",
                "4.8E9,5.0E9,5.2E9",
            ),
            ScriptedExchange.query(
                "CALC1:MEAS1:DATA:SDAT?",
                "1,0,0.25,-0.5,0.9,0.1",
            ),
            ScriptedExchange.write("SENS1:AVER ON"),
            ScriptedExchange.write("TRIG:SOUR IMM"),
        ]
    )
    driver = KeysightE5080B("vna", transport)

    driver.identify()
    driver.configure_linear_sweep(
        LinearSweepSettings(
            start_frequency_hz=4.8e9,
            stop_frequency_hz=5.2e9,
            points=3,
            if_bandwidth_hz=1.0e3,
            source_power_dbm=-30.0,
            s_parameter="S21",
        )
    )
    trace = driver.acquire_trace()

    assert trace.frequencies_hz == (4.8e9, 5.0e9, 5.2e9)
    assert trace.values == (1 + 0j, 0.25 - 0.5j, 0.9 + 0.1j)
    transport.assert_complete()


def test_e5080b_collect_restores_external_trigger_source() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.write("SENS1:SWE:TYPE LIN"),
            ScriptedExchange.query("TRIG:SOUR?", "EXT"),
            ScriptedExchange.write("TRIG:SOUR MAN"),
            ScriptedExchange.query("SENS1:AVER?", "OFF"),
            ScriptedExchange.write("INIT1:IMM;*WAI"),
            ScriptedExchange.write("FORM:DATA ASC,0"),
            ScriptedExchange.query("CALC1:MEAS1:X?", "4.9E9,5.1E9"),
            ScriptedExchange.query(
                "CALC1:MEAS1:DATA:SDAT?",
                "1,0,0.8,-0.1",
            ),
            ScriptedExchange.write("TRIG:SOUR EXT"),
        ]
    )
    driver = KeysightE5080B("vna", transport)

    receipt = driver.collect(
        _collect_request(
            NETWORK_SWEEP_ACQUISITION,
            NETWORK_SWEEP_S_PARAMETER_RESULT,
        )
    )

    assert receipt.status == "collected"
    transport.assert_complete()


def test_e5080b_collect_restores_averaging_and_trigger_after_parse_failure() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.write("SENS1:SWE:TYPE LIN"),
            ScriptedExchange.query("TRIG:SOUR?", "IMM"),
            ScriptedExchange.write("TRIG:SOUR MAN"),
            ScriptedExchange.query("SENS1:AVER?", "ON"),
            ScriptedExchange.write("SENS1:AVER OFF"),
            ScriptedExchange.write("INIT1:IMM;*WAI"),
            ScriptedExchange.write("FORM:DATA ASC,0"),
            ScriptedExchange.query("CALC1:MEAS1:X?", "4.9E9,5.1E9"),
            ScriptedExchange.query(
                "CALC1:MEAS1:DATA:SDAT?",
                "1,0,0.8",
            ),
            ScriptedExchange.write("SENS1:AVER ON"),
            ScriptedExchange.write("TRIG:SOUR IMM"),
        ]
    )
    driver = KeysightE5080B("vna", transport)

    receipt = driver.collect(
        _collect_request(
            NETWORK_SWEEP_ACQUISITION,
            NETWORK_SWEEP_S_PARAMETER_RESULT,
        )
    )

    assert receipt.status == "unknown"
    transport.assert_complete()


def test_e5080b_collect_restores_trigger_when_averaging_read_fails() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.write("SENS1:SWE:TYPE LIN"),
            ScriptedExchange.query("TRIG:SOUR?", "EXT"),
            ScriptedExchange.write("TRIG:SOUR MAN"),
            ScriptedExchange.query("SENS1:AVER?", "invalid"),
            ScriptedExchange.write("TRIG:SOUR EXT"),
        ]
    )
    driver = KeysightE5080B("vna", transport)

    receipt = driver.collect(
        _collect_request(
            NETWORK_SWEEP_ACQUISITION,
            NETWORK_SWEEP_S_PARAMETER_RESULT,
        )
    )

    assert receipt.status == "unknown"
    transport.assert_complete()
