from __future__ import annotations

from scopecat.daemon.views import (
    DriverManagedInstrumentConnectionSummary,
    SerialInstrumentConnectionSummary,
)
from scopecat.records.config import (
    DriverManagedInstrumentConnection,
    SerialInstrumentConnection,
)

from scopecat_server.instruments._runtime_support import (
    instrument_connection_summary,
)


def test_serial_connection_summary_exposes_port_without_driver_options() -> None:
    summary = instrument_connection_summary(
        SerialInstrumentConnection(
            port="/dev/ttyUSB0",
            baud_rate=115200,
            options={"slave_address": 7},
        )
    )

    assert summary == SerialInstrumentConnectionSummary(
        port="/dev/ttyUSB0",
        baud_rate=115200,
    )


def test_driver_managed_connection_summary_hides_factory_options() -> None:
    summary = instrument_connection_summary(
        DriverManagedInstrumentConnection(options={"boxes": {"box0": "192.0.2.1"}})
    )

    assert summary == DriverManagedInstrumentConnectionSummary()
