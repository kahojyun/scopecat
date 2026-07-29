from __future__ import annotations

from typing import override

import pytest
from scopecat.kernel.quantity import Quantity
from scopecat.records.measurement import MeasurementScalar, MeasurementUnavailable
from scopecat.sdk.instruments import (
    AcquisitionRef,
    AcquisitionResultRef,
    DriverAcquisition,
    DriverOutcome,
    DriverReadback,
    DriverRejected,
    DriverScalar,
    DriverStatePatch,
    DriverSuccess,
    DriverUnknown,
    PropertyRef,
)
from scopecat.sdk.instruments.scpi import TransportError

import scopecat_instruments.drivers.lakeshore372 as lakeshore372_driver
from scopecat_instruments._support import LinearSweepSettings
from scopecat_instruments.drivers import (
    KeysightE5080B,
    LakeShore372,
    RohdeSchwarzSGS100A,
    YokogawaGS200,
)
from scopecat_instruments.members import (
    DC_MONITOR_ACQUISITION,
    DC_MONITOR_CURRENT_RESULT,
    DC_MONITOR_INTEGRATION_CYCLES,
    DC_MONITOR_MEASUREMENT_DELAY,
    DC_MONITOR_MEASUREMENT_ENABLED,
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
    properties: list[tuple[PropertyRef, DriverScalar]],
) -> DriverStatePatch:
    return DriverStatePatch(values=dict(properties))


def _collect_request(
    acquisition: AcquisitionRef,
    *results: AcquisitionResultRef,
) -> DriverAcquisition:
    return DriverAcquisition(
        target=acquisition,
        results=frozenset(results),
    )


def _readback(outcome: DriverOutcome[DriverReadback]) -> DriverReadback:
    assert isinstance(outcome, DriverSuccess)
    return outcome.value


def _gs200_state_readback(
    *,
    mode: str,
    source_range: str,
    source_level: str,
    output_enabled: bool,
    voltage_protection: str = "10",
    current_protection: str = "0.01",
    monitor_enabled: bool | None = None,
    integration_cycles: str = "1",
    measurement_delay: str = "0",
    remote_sense: bool = False,
    guard_enabled: bool = False,
) -> list[ScriptedExchange]:
    exchanges = [
        ScriptedExchange.query(":SENS:REM?", "1" if remote_sense else "0"),
        ScriptedExchange.query(":SENS:GUAR?", "1" if guard_enabled else "0"),
        ScriptedExchange.query(":SOUR:FUNC?", mode),
        ScriptedExchange.query(":SOUR:RANG?", source_range),
        ScriptedExchange.query(":SOUR:LEV?", source_level),
        ScriptedExchange.query(":SOUR:PROT:VOLT?", voltage_protection),
        ScriptedExchange.query(":SOUR:PROT:CURR?", current_protection),
        ScriptedExchange.query(":OUTP?", "1" if output_enabled else "0"),
    ]
    if monitor_enabled is not None:
        exchanges.extend(
            [
                ScriptedExchange.query(
                    ":SENS?",
                    "1" if monitor_enabled else "0",
                ),
                ScriptedExchange.query(":SENS:NPLC?", integration_cycles),
                ScriptedExchange.query(":SENS:DEL?", measurement_delay),
            ]
        )
    return exchanges


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
            ScriptedExchange.query("*OPT?", "/MON"),
            ScriptedExchange.query(":SENS:REM?", "0"),
            ScriptedExchange.query(":SENS:GUAR?", "0"),
            ScriptedExchange.write(":SOUR:FUNC VOLT"),
            ScriptedExchange.write(":SOUR:RANG 1"),
            ScriptedExchange.write(":SOUR:LEV 0.125"),
            ScriptedExchange.write(":SOUR:PROT:VOLT 12"),
            ScriptedExchange.write(":SOUR:PROT:CURR 0.01"),
            ScriptedExchange.write(":OUTP ON"),
            *_gs200_state_readback(
                mode="VOLT",
                source_range="+1.000000E+00",
                source_level="+1.250000E-01",
                voltage_protection="+1.200000E+01",
                current_protection="+1.000000E-02",
                output_enabled=True,
                monitor_enabled=True,
                integration_cycles="5",
                measurement_delay="0.01",
            ),
            ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
            ScriptedExchange.query(":OUTP?", "1"),
            ScriptedExchange.query(":SENS?", "1"),
            ScriptedExchange.query(":SOUR:RANG?", "1"),
            ScriptedExchange.query(":SENS:NULL?", "0"),
            ScriptedExchange.query(":SENS:TRIG?", "COMM"),
            ScriptedExchange.query(":MEAS?", "+1.250000E-04"),
            ScriptedExchange.query(":STAT:COND?", "17"),
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
    assert set(state.metadata) == {"manufacturer", "model", "identity"}
    assert state.values[DC_MONITOR_MEASUREMENT_ENABLED] is True
    assert state.values[DC_MONITOR_INTEGRATION_CYCLES] == 5
    assert state.values[DC_MONITOR_MEASUREMENT_DELAY] == Quantity(
        0.01,
        "s",
    )
    measured = _readback(receipt).values[DC_MONITOR_CURRENT_RESULT]
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

    assert isinstance(receipt, DriverSuccess)
    transport.assert_complete()


def test_gs200_applies_and_monitors_current_source_case() -> None:
    transport = ScriptedTransport(
        [
            *_gs200_state_readback(
                mode="VOLT",
                source_range="1",
                source_level="0",
                output_enabled=False,
                monitor_enabled=True,
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
                monitor_enabled=True,
            ),
            ScriptedExchange.query(":SOUR:FUNC?", "CURR"),
            ScriptedExchange.query(":OUTP?", "1"),
            ScriptedExchange.query(":SENS?", "1"),
            ScriptedExchange.query(":SENS:NULL?", "0"),
            ScriptedExchange.query(":SENS:TRIG?", "COMM"),
            ScriptedExchange.query(":MEAS?", "1"),
            ScriptedExchange.query(":STAT:COND?", "17"),
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

    assert isinstance(applied, DriverSuccess)
    assert _readback(monitored).values[
        DC_MONITOR_VOLTAGE_RESULT
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

    assert isinstance(receipt, DriverSuccess)
    transport.assert_complete()


def test_gs200_identify_rejects_missing_monitor_option() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(
                "*IDN?",
                "YOKOGAWA,GS200,91X000001,2.03",
            ),
            ScriptedExchange.query("*OPT?", "0"),
        ]
    )
    driver = YokogawaGS200("bias", transport, monitor_option=True)

    with pytest.raises(ValueError, match="/MON option"):
        driver.identify()

    transport.assert_complete()


def test_gs200_identify_skips_unrequested_monitor_option_probe() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(
                "*IDN?",
                "YOKOGAWA,GS200,91X000001,2.03",
            ),
            ScriptedExchange.query(":SENS:REM?", "0"),
            ScriptedExchange.query(":SENS:GUAR?", "0"),
        ]
    )
    driver = YokogawaGS200("bias", transport)

    identity = driver.identify()

    assert identity.model == "GS200"
    transport.assert_complete()


@pytest.mark.parametrize(
    ("remote_sense", "guard_enabled", "actual_remote", "actual_guard", "message"),
    [
        (True, False, False, False, "remote-sense"),
        (False, True, False, False, "guard state"),
    ],
)
def test_gs200_identify_rejects_connection_profile_drift(
    remote_sense: bool,
    guard_enabled: bool,
    actual_remote: bool,
    actual_guard: bool,
    message: str,
) -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(
                "*IDN?",
                "YOKOGAWA,GS200,91X000001,2.03",
            ),
            ScriptedExchange.query("*OPT?", "/MON"),
            ScriptedExchange.query(
                ":SENS:REM?",
                "1" if actual_remote else "0",
            ),
            ScriptedExchange.query(
                ":SENS:GUAR?",
                "1" if actual_guard else "0",
            ),
        ]
    )
    driver = YokogawaGS200(
        "bias",
        transport,
        monitor_option=True,
        remote_sense=remote_sense,
        guard_enabled=guard_enabled,
    )

    with pytest.raises(ValueError, match=message):
        driver.identify()

    transport.assert_complete()


def test_gs200_read_state_rejects_connection_profile_drift() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(":SENS:REM?", "0"),
            ScriptedExchange.query(":SENS:GUAR?", "1"),
        ]
    )
    driver = YokogawaGS200("bias", transport)

    with pytest.raises(ValueError, match="guard state"):
        driver.read_state()

    transport.assert_complete()


def test_gs200_read_state_rejects_remote_sense_on_a_millivolt_range() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(":SENS:REM?", "1"),
            ScriptedExchange.query(":SENS:GUAR?", "0"),
            ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
            ScriptedExchange.query(":SOUR:RANG?", "0.1"),
        ]
    )
    driver = YokogawaGS200("bias", transport, remote_sense=True)

    with pytest.raises(ValueError, match="at least 1 V"):
        driver.read_state()

    transport.assert_complete()


def test_gs200_rejects_a_millivolt_range_before_mutating_remote_sense_source() -> None:
    transport = ScriptedTransport(
        _gs200_state_readback(
            mode="CURR",
            source_range="0.01",
            source_level="0.001",
            output_enabled=True,
            remote_sense=True,
        )
    )
    driver = YokogawaGS200("bias", transport, remote_sense=True)

    receipt = driver.apply_state(
        _apply_request(
            [
                (DC_SOURCE_MODE, "voltage"),
                (DC_SOURCE_VOLTAGE_RANGE, Quantity(0.1, "V")),
                (DC_SOURCE_VOLTAGE_LEVEL, Quantity(0.0, "V")),
            ]
        )
    )

    assert isinstance(receipt, DriverRejected)
    assert receipt.problems[0].code == "gs200_remote_sense_voltage_range_incompatible"
    assert all(entry.operation == "query" for entry in transport.transcript)
    transport.assert_complete()


def test_gs200_applies_monitor_settings_while_measurement_is_disabled() -> None:
    transport = ScriptedTransport(
        [
            *_gs200_state_readback(
                mode="VOLT",
                source_range="1",
                source_level="0.125",
                output_enabled=True,
                monitor_enabled=True,
                integration_cycles="1",
                measurement_delay="0",
            ),
            ScriptedExchange.write(":SENS OFF"),
            ScriptedExchange.write(":SENS:NPLC 10"),
            ScriptedExchange.write(":SENS:DEL 0.25"),
            ScriptedExchange.write(":SENS ON"),
            *_gs200_state_readback(
                mode="VOLT",
                source_range="1",
                source_level="0.125",
                output_enabled=True,
                monitor_enabled=True,
                integration_cycles="10",
                measurement_delay="0.25",
            ),
        ]
    )
    driver = YokogawaGS200("bias", transport, monitor_option=True)

    receipt = driver.apply_state(
        _apply_request(
            [
                (DC_MONITOR_INTEGRATION_CYCLES, 10),
                (DC_MONITOR_MEASUREMENT_DELAY, Quantity(0.25, "s")),
            ]
        )
    )

    assert isinstance(receipt, DriverSuccess)
    assert receipt.value is not None
    properties = receipt.value.values
    assert properties[DC_MONITOR_MEASUREMENT_ENABLED] is True
    assert properties[DC_MONITOR_INTEGRATION_CYCLES] == 10
    assert properties[DC_MONITOR_MEASUREMENT_DELAY] == Quantity(
        0.25,
        "s",
    )
    transport.assert_complete()


@pytest.mark.parametrize(
    ("exchanges", "result", "problem_code"),
    [
        (
            [ScriptedExchange.query(":SOUR:FUNC?", "VOLT")],
            DC_MONITOR_VOLTAGE_RESULT,
            "gs200_monitor_result_inactive",
        ),
        (
            [
                ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
                ScriptedExchange.query(":OUTP?", "0"),
            ],
            DC_MONITOR_CURRENT_RESULT,
            "gs200_output_disabled",
        ),
        (
            [
                ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
                ScriptedExchange.query(":OUTP?", "1"),
                ScriptedExchange.query(":SENS?", "0"),
            ],
            DC_MONITOR_CURRENT_RESULT,
            "gs200_monitor_disabled",
        ),
        (
            [
                ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
                ScriptedExchange.query(":OUTP?", "1"),
                ScriptedExchange.query(":SENS?", "1"),
                ScriptedExchange.query(":SOUR:RANG?", "0.1"),
            ],
            DC_MONITOR_CURRENT_RESULT,
            "gs200_monitor_voltage_range_too_low",
        ),
        (
            [
                ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
                ScriptedExchange.query(":OUTP?", "1"),
                ScriptedExchange.query(":SENS?", "1"),
                ScriptedExchange.query(":SOUR:RANG?", "1"),
                ScriptedExchange.query(":SENS:NULL?", "1"),
            ],
            DC_MONITOR_CURRENT_RESULT,
            "gs200_monitor_null_enabled",
        ),
    ],
    ids=[
        "inactive-result",
        "output-off",
        "measurement-off",
        "voltage-range",
        "null-on",
    ],
)
def test_gs200_collect_guards_do_not_trigger_measurement(
    exchanges: list[ScriptedExchange],
    result: AcquisitionResultRef,
    problem_code: str,
) -> None:
    transport = ScriptedTransport(exchanges)
    driver = YokogawaGS200("bias", transport, monitor_option=True)

    receipt = driver.collect(_collect_request(DC_MONITOR_ACQUISITION, result))

    assert isinstance(receipt, DriverRejected)
    assert receipt.problems[0].code == problem_code
    assert all(entry.operation == "query" for entry in transport.transcript)
    transport.assert_complete()


def test_gs200_collect_uses_communication_trigger_then_restores_it() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
            ScriptedExchange.query(":OUTP?", "1"),
            ScriptedExchange.query(":SENS?", "1"),
            ScriptedExchange.query(":SOUR:RANG?", "1"),
            ScriptedExchange.query(":SENS:NULL?", "0"),
            ScriptedExchange.query(":SENS:TRIG?", "IMM"),
            ScriptedExchange.write(":SENS:TRIG COMM"),
            ScriptedExchange.query(":MEAS?", "0.000125"),
            ScriptedExchange.query(":STAT:COND?", "17"),
            ScriptedExchange.write(":SENS:TRIG IMM"),
        ]
    )
    driver = YokogawaGS200("bias", transport, monitor_option=True)

    receipt = driver.collect(
        _collect_request(DC_MONITOR_ACQUISITION, DC_MONITOR_CURRENT_RESULT)
    )

    assert _readback(receipt).values[
        DC_MONITOR_CURRENT_RESULT
    ] == MeasurementScalar.create(
        dtype="float64",
        unit="A",
        value=0.000125,
    )
    transport.assert_complete()


def test_gs200_collect_reports_monitor_overload_as_unavailable() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(":SOUR:FUNC?", "CURR"),
            ScriptedExchange.query(":OUTP?", "1"),
            ScriptedExchange.query(":SENS?", "1"),
            ScriptedExchange.query(":SENS:NULL?", "0"),
            ScriptedExchange.query(":SENS:TRIG?", "TIM"),
            ScriptedExchange.write(":SENS:TRIG COMM"),
            ScriptedExchange.query(":MEAS?", "9.91E+37"),
            ScriptedExchange.query(":STAT:COND?", "19"),
            ScriptedExchange.write(":SENS:TRIG TIM"),
        ]
    )
    driver = YokogawaGS200("bias", transport, monitor_option=True)

    receipt = driver.collect(
        _collect_request(DC_MONITOR_ACQUISITION, DC_MONITOR_VOLTAGE_RESULT)
    )

    assert _readback(receipt).values[
        DC_MONITOR_VOLTAGE_RESULT
    ] == MeasurementUnavailable.create(
        reason="overload",
        dtype="float64",
        unit="V",
        shape=(),
        metadata={"status_condition": 19},
    )
    transport.assert_complete()


@pytest.mark.parametrize("condition", [1, 16], ids=["sampling-error", "incomplete"])
def test_gs200_collect_reports_invalid_measurement_status(condition: int) -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query(":SOUR:FUNC?", "CURR"),
            ScriptedExchange.query(":OUTP?", "1"),
            ScriptedExchange.query(":SENS?", "1"),
            ScriptedExchange.query(":SENS:NULL?", "0"),
            ScriptedExchange.query(":SENS:TRIG?", "COMM"),
            ScriptedExchange.query(":MEAS?", "0.125"),
            ScriptedExchange.query(":STAT:COND?", str(condition)),
        ]
    )
    driver = YokogawaGS200("bias", transport, monitor_option=True)

    receipt = driver.collect(
        _collect_request(DC_MONITOR_ACQUISITION, DC_MONITOR_VOLTAGE_RESULT)
    )

    assert _readback(receipt).values[
        DC_MONITOR_VOLTAGE_RESULT
    ] == MeasurementUnavailable.create(
        reason="invalid",
        dtype="float64",
        unit="V",
        shape=(),
        metadata={"status_condition": condition},
    )
    transport.assert_complete()


class _RestoreFailingTransport(ScriptedTransport):
    @override
    def write(self, command: str) -> None:
        if command == ":SENS:TRIG IMM":
            raise TransportError("trigger restore failed")
        super().write(command)


def test_gs200_trigger_restore_failure_reports_unknown() -> None:
    transport = _RestoreFailingTransport(
        [
            ScriptedExchange.query(":SOUR:FUNC?", "VOLT"),
            ScriptedExchange.query(":OUTP?", "1"),
            ScriptedExchange.query(":SENS?", "1"),
            ScriptedExchange.query(":SOUR:RANG?", "1"),
            ScriptedExchange.query(":SENS:NULL?", "0"),
            ScriptedExchange.query(":SENS:TRIG?", "IMM"),
            ScriptedExchange.write(":SENS:TRIG COMM"),
            ScriptedExchange.query(":MEAS?", "0.000125"),
            ScriptedExchange.query(":STAT:COND?", "17"),
        ]
    )
    driver = YokogawaGS200("bias", transport, monitor_option=True)

    receipt = driver.collect(
        _collect_request(DC_MONITOR_ACQUISITION, DC_MONITOR_CURRENT_RESULT)
    )

    assert isinstance(receipt, DriverUnknown)
    assert receipt.problems[0].code == "instrument_collect_outcome_unknown"
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

    assert state.values[RF_OUTPUT_FREQUENCY] == Quantity(5.0e9, "Hz")
    assert state.values[RF_OUTPUT_POWER] == Quantity(-27.5, "dBm")
    assert state.values[RF_OUTPUT_REFERENCE_SOURCE] == "external"
    assert state.values[RF_OUTPUT_ENABLED] is True
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

    assert isinstance(receipt, DriverSuccess)
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

    properties = state.values
    assert set(properties) == {
        TEMPERATURE_READOUT_SCAN_CHANNEL,
        TEMPERATURE_READOUT_AUTOSCAN_ENABLED,
    }
    assert properties[TEMPERATURE_READOUT_SCAN_CHANNEL] == 5
    assert properties[TEMPERATURE_READOUT_AUTOSCAN_ENABLED] is True
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

    readback = _readback(receipt)
    temperature = readback.values[TEMPERATURE_READOUT_TEMPERATURE_RESULT]
    resistance = readback.values[TEMPERATURE_READOUT_RESISTANCE_RESULT]
    assert isinstance(temperature, MeasurementScalar)
    assert isinstance(resistance, MeasurementScalar)
    assert temperature.value == pytest.approx(0.0205)
    assert resistance.value == pytest.approx(6720.0)
    assert readback.metadata["curve_number"] == 21
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

    assert "curve_number" not in _readback(receipt).metadata
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

    assert _readback(receipt).metadata["scan_channel"] == 5
    transport.assert_complete()


def test_lakeshore_372_missing_curve_only_marks_temperature_unavailable() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("INCRV? 5", "0"),
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
            TEMPERATURE_READOUT_TEMPERATURE_RESULT,
            TEMPERATURE_READOUT_RESISTANCE_RESULT,
        )
    )

    readback = _readback(receipt)
    temperature = readback.values[TEMPERATURE_READOUT_TEMPERATURE_RESULT]
    resistance = readback.values[TEMPERATURE_READOUT_RESISTANCE_RESULT]
    assert isinstance(temperature, MeasurementUnavailable)
    assert temperature.reason == "missing"
    assert temperature.shape == ()
    assert temperature.metadata["code"] == "lakeshore_temperature_curve_missing"
    assert isinstance(resistance, MeasurementScalar)
    assert resistance.value == pytest.approx(6720.0)
    assert readback.metadata["curve_number"] == 0
    transport.assert_complete()


def test_lakeshore_372_invalid_status_marks_every_result_unavailable() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("INCRV? 5", "21"),
            ScriptedExchange.query("KRDG? 5", "+2.050000E-02"),
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
            TEMPERATURE_READOUT_TEMPERATURE_RESULT,
            TEMPERATURE_READOUT_RESISTANCE_RESULT,
        )
    )

    readback = _readback(receipt)
    assert readback.metadata["reading_status"] == 64
    for value in readback.values.values():
        assert isinstance(value, MeasurementUnavailable)
        assert value.reason == "invalid"
        assert value.metadata["reading_status"] == 64
    transport.assert_complete()


def test_lakeshore_372_explicit_overload_status_is_preserved() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("RDGSTL?", "0,0"),
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("SRDG? 5", "+1.000000E+08"),
            ScriptedExchange.query("RDGST? 5", "8"),
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

    unavailable = _readback(receipt).values[TEMPERATURE_READOUT_RESISTANCE_RESULT]
    assert isinstance(unavailable, MeasurementUnavailable)
    assert unavailable.reason == "overload"
    transport.assert_complete()


def test_lakeshore_372_settle_timeout_is_collected_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter((0.0, 11.0))
    monkeypatch.setattr(lakeshore372_driver, "monotonic", lambda: next(times))
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "5,0"),
            ScriptedExchange.query("RDGSTL?", "0,1"),
        ]
    )
    driver = LakeShore372("fridge", transport)

    receipt = driver.collect(
        _collect_request(
            TEMPERATURE_READOUT_SAMPLE,
            TEMPERATURE_READOUT_TEMPERATURE_RESULT,
        )
    )

    unavailable = _readback(receipt).values[TEMPERATURE_READOUT_TEMPERATURE_RESULT]
    assert isinstance(unavailable, MeasurementUnavailable)
    assert unavailable.reason == "invalid"
    assert unavailable.metadata["code"] == "lakeshore_reading_settle_timeout"
    transport.assert_complete()


def test_lakeshore_372_scan_coherence_timeout_is_collected_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    times = iter((0.0, 11.0))
    monkeypatch.setattr(lakeshore372_driver, "monotonic", lambda: next(times))
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "4,1"),
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

    unavailable = _readback(receipt).values[TEMPERATURE_READOUT_RESISTANCE_RESULT]
    assert isinstance(unavailable, MeasurementUnavailable)
    assert unavailable.reason == "invalid"
    assert unavailable.metadata["code"] == "lakeshore_scan_coherence_timeout"
    transport.assert_complete()


def test_lakeshore_372_protocol_error_keeps_collection_unknown() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SCAN?", "malformed"),
        ]
    )
    driver = LakeShore372("fridge", transport)

    receipt = driver.collect(
        _collect_request(
            TEMPERATURE_READOUT_SAMPLE,
            TEMPERATURE_READOUT_RESISTANCE_RESULT,
        )
    )

    assert isinstance(receipt, DriverUnknown)
    assert receipt.problems[0].code == "instrument_collect_outcome_unknown"
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
            ScriptedExchange.query("SENS1:SWE:TYPE?", "LIN"),
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


def test_e5080b_state_sync_rejects_non_linear_front_panel_mode() -> None:
    transport = ScriptedTransport([ScriptedExchange.query("SENS1:SWE:TYPE?", "LOG")])
    driver = KeysightE5080B("vna", transport)

    with pytest.raises(ValueError, match="linear-sweep profile"):
        driver.read_state()

    transport.assert_complete()


def test_e5080b_collect_restores_external_trigger_source() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SENS1:SWE:TYPE?", "LIN"),
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

    assert isinstance(receipt, DriverSuccess)
    transport.assert_complete()


def test_e5080b_collect_restores_averaging_and_trigger_after_parse_failure() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SENS1:SWE:TYPE?", "LIN"),
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

    assert isinstance(receipt, DriverUnknown)
    transport.assert_complete()


def test_e5080b_collect_restores_trigger_when_averaging_read_fails() -> None:
    transport = ScriptedTransport(
        [
            ScriptedExchange.query("SENS1:SWE:TYPE?", "LIN"),
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

    assert isinstance(receipt, DriverUnknown)
    transport.assert_complete()
