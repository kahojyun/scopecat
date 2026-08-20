from __future__ import annotations

from scopecat.daemon.views import SerialInstrumentConnectionSummary
from scopecat.records.config import SerialInstrumentConnection

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
