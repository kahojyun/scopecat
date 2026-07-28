from __future__ import annotations

import pytest
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments import (
    CollectCommand,
    CollectProductRequest,
    InstrumentStateCommand,
    InstrumentStateCommandField,
)

from scopecat_instruments._support import LinearSweepSettings
from scopecat_instruments.drivers import (
    KeysightE5080B,
    LakeShore372,
    RohdeSchwarzSGS100A,
    YokogawaGS200,
)
from scopecat_instruments.testing import ScriptedExchange, ScriptedTransport


def _state_command(
    instrument_id: str,
    capability_id: str,
    fields: list[tuple[str, bool | str | Quantity]],
) -> InstrumentStateCommand:
    return InstrumentStateCommand(
        instrument_id=instrument_id,
        fields=[
            InstrumentStateCommandField(
                resource_id=instrument_id,
                capability_id=capability_id,
                field_path=field_path,
                value=StateValue(value),
            )
            for field_path, value in fields
        ],
    )


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
        CollectCommand(
            instrument_id="bias",
            point_index=0,
            point_count=1,
            requests=[
                CollectProductRequest(
                    id="monitored_current",
                    capability_id="dc_output",
                    unit="A",
                )
            ],
        )
    )

    assert identity.model == "GS210"
    assert state.metadata["identity"] == identity.raw
    assert receipt.status == "collected"
    assert receipt.readback is not None
    measured = receipt.readback.values["monitored_current"]
    assert isinstance(measured, Quantity)
    assert measured.value == pytest.approx(1.25e-4)
    transport.assert_complete()


@pytest.mark.parametrize("enabled", [False, True], ids=["disable-first", "enable-last"])
def test_gs200_apply_orders_output_around_level_changes(enabled: bool) -> None:
    writes = [ScriptedExchange.write(":OUTP OFF")] if not enabled else []
    writes.extend(
        [
            ScriptedExchange.write(":SOUR:FUNC VOLT"),
            ScriptedExchange.write(":SOUR:LEV 0.125"),
        ]
    )
    if enabled:
        writes.append(ScriptedExchange.write(":OUTP ON"))
    transport = ScriptedTransport(
        [
            *writes,
            ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
            ScriptedExchange.query(":SOUR:RANG?", "1"),
            ScriptedExchange.query(":SOUR:LEV?", "0.125"),
            ScriptedExchange.query(":SOUR:PROT:VOLT?", "10"),
            ScriptedExchange.query(":SOUR:PROT:CURR?", "0.01"),
            ScriptedExchange.query(":OUTP?", "1" if enabled else "0"),
        ]
    )
    driver = YokogawaGS200("bias", transport)

    receipt = driver.apply_state(
        _state_command(
            "bias",
            "dc_output",
            [
                ("source_mode", "voltage"),
                ("voltage_level", Quantity(0.125, "V")),
                ("output_enabled", enabled),
            ],
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
            ScriptedExchange.write(":SOUR:POW -27.5"),
            ScriptedExchange.write(":SOUR:ROSC:SOUR EXT"),
            ScriptedExchange.write(":OUTP ON"),
            ScriptedExchange.query(":SOUR:FREQ?", "5.000000000000E+09"),
            ScriptedExchange.query(":SOUR:POW?", "-2.750000000000E+01"),
            ScriptedExchange.query(":OUTP?", "ON"),
            ScriptedExchange.query(":SOUR:ROSC:SOUR?", "EXT"),
        ]
    )
    driver = RohdeSchwarzSGS100A("readout-lo", transport)

    driver.identify()
    driver.set_frequency(5.0e9)
    driver.set_power(-27.5)
    driver.set_reference_source("external")
    driver.set_output(True)
    state = driver.read_state()

    fields = {field.field_path: field.value.root for field in state.fields}
    assert fields["reference_source"] == "external"
    assert fields["output_enabled"] is True
    transport.assert_complete()


@pytest.mark.parametrize("enabled", [False, True], ids=["disable-first", "enable-last"])
def test_sgs100a_apply_orders_output_around_frequency_and_power(
    enabled: bool,
) -> None:
    writes = [ScriptedExchange.write(":OUTP OFF")] if not enabled else []
    writes.extend(
        [
            ScriptedExchange.write(":SOUR:FREQ 5000000000"),
            ScriptedExchange.write(":SOUR:POW -27.5"),
        ]
    )
    if enabled:
        writes.append(ScriptedExchange.write(":OUTP ON"))
    transport = ScriptedTransport(
        [
            *writes,
            ScriptedExchange.query(":SOUR:FREQ?", "5.0E9"),
            ScriptedExchange.query(":SOUR:POW?", "-27.5"),
            ScriptedExchange.query(":OUTP?", "1" if enabled else "0"),
            ScriptedExchange.query(":SOUR:ROSC:SOUR?", "INT"),
        ]
    )
    driver = RohdeSchwarzSGS100A("readout-lo", transport)

    receipt = driver.apply_state(
        _state_command(
            "readout-lo",
            "rf_output",
            [
                ("frequency", Quantity(5.0e9, "Hz")),
                ("power", Quantity(-27.5, "dBm")),
                ("output_enabled", enabled),
            ],
        )
    )

    assert receipt.status == "applied"
    transport.assert_complete()


def test_lakeshore_372_read_only_telemetry_transcript() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(
                "*IDN?",
                "LSCI,MODEL372,LSA1234,1.4",
            ),
            ScriptedExchange.query("SCAN?", "5,1"),
            ScriptedExchange.query("KRDG? 5", "+2.050000E-02"),
            ScriptedExchange.query("SRDG? 5", "+6.720000E+03"),
            ScriptedExchange.query("RDGST? 5", "0"),
            ScriptedExchange.query("HTR?", "+1.250000E+00"),
            ScriptedExchange.query("RANGE? 0", "3"),
            ScriptedExchange.query("HTRST? 0", "0"),
        ]
    )
    driver = LakeShore372("fridge", transport)

    driver.identify()
    telemetry = driver.read_telemetry()

    assert telemetry.scan_channel == 5
    assert telemetry.autoscan_enabled is True
    assert telemetry.temperature_k == pytest.approx(0.0205)
    assert telemetry.resistance_ohm == pytest.approx(6720.0)
    assert telemetry.heater_output == pytest.approx(1.25)
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
            ScriptedExchange.query("INIT1:CONT?", "ON"),
            ScriptedExchange.write("INIT1:CONT OFF"),
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
            ScriptedExchange.write("INIT1:CONT ON"),
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


def test_e5080b_collect_keeps_disabled_continuous_trigger_unchanged() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("INIT1:CONT?", "OFF"),
            ScriptedExchange.write("INIT1:IMM;*WAI"),
            ScriptedExchange.write("FORM:DATA ASC,0"),
            ScriptedExchange.query("CALC1:MEAS1:X?", "4.9E9,5.1E9"),
            ScriptedExchange.query(
                "CALC1:MEAS1:DATA:SDAT?",
                "1,0,0.8,-0.1",
            ),
        ]
    )
    driver = KeysightE5080B("vna", transport)

    receipt = driver.collect(
        CollectCommand(
            instrument_id="vna",
            point_index=0,
            point_count=1,
            requests=[
                CollectProductRequest(
                    id="s_parameter",
                    capability_id="network_sweep",
                    unit="ratio",
                    dtype="complex128",
                )
            ],
        )
    )

    assert receipt.status == "collected"
    transport.assert_complete()


def test_e5080b_collect_restores_continuous_trigger_after_parse_failure() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("INIT1:CONT?", "ON"),
            ScriptedExchange.write("INIT1:CONT OFF"),
            ScriptedExchange.write("INIT1:IMM;*WAI"),
            ScriptedExchange.write("FORM:DATA ASC,0"),
            ScriptedExchange.query("CALC1:MEAS1:X?", "4.9E9,5.1E9"),
            ScriptedExchange.query(
                "CALC1:MEAS1:DATA:SDAT?",
                "1,0,0.8",
            ),
            ScriptedExchange.write("INIT1:CONT ON"),
        ]
    )
    driver = KeysightE5080B("vna", transport)

    receipt = driver.collect(
        CollectCommand(
            instrument_id="vna",
            point_index=0,
            point_count=1,
            requests=[
                CollectProductRequest(
                    id="s_parameter",
                    capability_id="network_sweep",
                    unit="ratio",
                    dtype="complex128",
                )
            ],
        )
    )

    assert receipt.status == "unknown"
    transport.assert_complete()
