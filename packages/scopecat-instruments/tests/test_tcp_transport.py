from __future__ import annotations

import socket
from collections import deque
from collections.abc import Callable
from typing import cast

import pytest

from scopecat_instruments.transport import TcpScpiTransport, TransportError


class _Socket:
    def __init__(
        self,
        responses: tuple[bytes | OSError, ...] = (),
        *,
        write_error: OSError | None = None,
    ) -> None:
        self.responses = deque(responses)
        self.write_error = write_error
        self.closed = False

    def settimeout(self, _timeout: float | None) -> None:
        pass

    def sendall(self, _payload: bytes, _flags: int = 0) -> None:
        if self.write_error is not None:
            raise self.write_error

    def recv(self, _size: int, _flags: int = 0) -> bytes:
        response = self.responses.popleft()
        if isinstance(response, OSError):
            raise response
        return response

    def close(self) -> None:
        self.closed = True


def _connection_factory(
    connection: _Socket,
    calls: list[tuple[str, int]],
) -> Callable[..., socket.socket]:
    def create_connection(
        address: tuple[str, int],
        *,
        timeout: float | None = None,
    ) -> socket.socket:
        del timeout
        calls.append(address)
        return cast("socket.socket", cast("object", connection))

    return create_connection


def test_connect_failure_is_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, int]] = []

    def fail_connection(
        address: tuple[str, int],
        *,
        timeout: float | None = None,
    ) -> socket.socket:
        del timeout
        calls.append(address)
        raise OSError("offline")

    monkeypatch.setattr(socket, "create_connection", fail_connection)
    transport = TcpScpiTransport("device.test", 5025)

    with pytest.raises(TransportError, match="failed to connect"):
        transport.connect()
    with pytest.raises(TransportError, match="broken"):
        transport.connect()

    assert calls == [("device.test", 5025)]
    assert not transport.connected


def test_write_failure_never_reopens_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Socket(write_error=OSError("lost"))
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        socket,
        "create_connection",
        _connection_factory(connection, calls),
    )
    transport = TcpScpiTransport("device.test", 5025)

    with pytest.raises(TransportError, match="write failed"):
        transport.write("*IDN?")
    with pytest.raises(TransportError, match="broken"):
        transport.write("*IDN?")

    assert calls == [("device.test", 5025)]
    assert connection.closed
    assert not transport.connected


def test_broken_partial_response_is_cleared_without_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _Socket((b"partial", OSError("lost")))
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        socket,
        "create_connection",
        _connection_factory(connection, calls),
    )
    transport = TcpScpiTransport("device.test", 5025)

    with pytest.raises(TransportError, match="response read failed"):
        transport.query("*IDN?")
    with pytest.raises(TransportError, match="broken"):
        transport.query("*IDN?")

    assert calls == [("device.test", 5025)]
    assert transport._receive_buffer == bytearray()
    assert connection.closed


def test_oversize_and_decode_failures_break_the_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversize_socket = _Socket((b"12345",))
    decode_socket = _Socket((b"\xff\nunused",))
    connections = deque((oversize_socket, decode_socket))

    def create_connection(
        _address: tuple[str, int],
        *,
        timeout: float | None = None,
    ) -> socket.socket:
        del timeout
        return cast("socket.socket", cast("object", connections.popleft()))

    monkeypatch.setattr(socket, "create_connection", create_connection)
    oversize = TcpScpiTransport("device.test", 5025, max_response_bytes=4)
    invalid_text = TcpScpiTransport("device.test", 5025)

    with pytest.raises(TransportError, match="size limit"):
        oversize.query("READ?")
    with pytest.raises(TransportError, match="not valid text"):
        invalid_text.query("READ?")

    assert oversize._receive_buffer == bytearray()
    assert invalid_text._receive_buffer == bytearray()
    assert oversize_socket.closed
    assert decode_socket.closed


def test_closed_transport_does_not_reopen(monkeypatch: pytest.MonkeyPatch) -> None:
    connection = _Socket()
    calls: list[tuple[str, int]] = []
    monkeypatch.setattr(
        socket,
        "create_connection",
        _connection_factory(connection, calls),
    )
    transport = TcpScpiTransport("device.test", 5025)

    transport.connect()
    transport.close()
    with pytest.raises(TransportError, match="closed"):
        transport.connect()
    with pytest.raises(TransportError, match="closed"):
        transport.write("*IDN?")

    assert calls == [("device.test", 5025)]
    assert connection.closed
    assert not transport.connected
