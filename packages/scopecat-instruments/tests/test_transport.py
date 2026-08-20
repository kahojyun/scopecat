from __future__ import annotations

from typing import final

import pytest
from pytest import MonkeyPatch
from scopecat.sdk.instruments import TransportError
from serial import SerialTimeoutException

import scopecat_instruments.transport as transport_module
from scopecat_instruments.testing import (
    ScriptedBinaryExchange,
    ScriptedBinaryTransport,
)
from scopecat_instruments.transport import SerialByteTransport


@final
class _FakeSerial:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.writes: list[bytes] = []
        self.flushed = False
        self.closed = False

    def write(self, request: bytes) -> int:
        self.writes.append(request)
        return len(request)

    def flush(self) -> None:
        self.flushed = True

    def read(self, size: int) -> bytes:
        return self.response[:size]

    def close(self) -> None:
        self.closed = True


def test_serial_transport_exchanges_one_exact_binary_frame(
    monkeypatch: MonkeyPatch,
) -> None:
    connection = _FakeSerial(b"ack")
    opened_with: dict[str, object] = {}

    def open_serial(**options: object) -> _FakeSerial:
        opened_with.update(options)
        return connection

    monkeypatch.setattr(transport_module, "Serial", open_serial)
    transport = SerialByteTransport(
        "/dev/tty-test",
        baud_rate=115200,
        parity="even",
        stop_bits=1.5,
    )

    assert transport.exchange(b"request", 3) == b"ack"
    assert connection.writes == [b"request"]
    assert connection.flushed is True
    assert opened_with["port"] == "/dev/tty-test"
    assert opened_with["baudrate"] == 115200
    transport.close()
    assert connection.closed is True


def test_serial_transport_breaks_generation_when_ack_is_missing(
    monkeypatch: MonkeyPatch,
) -> None:
    connection = _FakeSerial(b"")

    def open_silent_serial(**_options: object) -> _FakeSerial:
        return connection

    monkeypatch.setattr(transport_module, "Serial", open_silent_serial)
    transport = SerialByteTransport("COM-test")

    with pytest.raises(TransportError) as caught:
        transport.exchange(b"request", 3)

    assert caught.value.operation == "exchange"
    assert caught.value.command_may_have_reached_device is True
    assert caught.value.requires_replacement is True
    assert connection.closed is True
    with pytest.raises(TransportError, match="broken"):
        transport.connect()


def test_serial_transport_rejects_partial_write_as_unknown(
    monkeypatch: MonkeyPatch,
) -> None:
    connection = _FakeSerial(b"ack")

    def partial_write(request: bytes) -> int:
        del request
        raise SerialTimeoutException("write timed out")

    connection.write = partial_write  # type: ignore[method-assign]

    def open_partial_serial(**_options: object) -> _FakeSerial:
        return connection

    monkeypatch.setattr(transport_module, "Serial", open_partial_serial)

    with pytest.raises(TransportError) as caught:
        SerialByteTransport("COM-test").exchange(b"request", 3)

    assert caught.value.command_may_have_reached_device is True


def test_scripted_binary_transport_checks_exact_frames() -> None:
    transport = ScriptedBinaryTransport(
        [ScriptedBinaryExchange(b"request", b"response")]
    )

    assert transport.exchange(b"request", 8) == b"response"
    transport.assert_complete()
