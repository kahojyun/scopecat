"""Small synchronous transports for line-oriented SCPI instruments."""

from __future__ import annotations

import socket
from contextlib import suppress
from threading import RLock
from typing import Literal

from scopecat.sdk.instruments.scpi import TransportError
from serial import (
    EIGHTBITS,
    FIVEBITS,
    PARITY_EVEN,
    PARITY_MARK,
    PARITY_NONE,
    PARITY_ODD,
    PARITY_SPACE,
    SEVENBITS,
    SIXBITS,
    STOPBITS_ONE,
    STOPBITS_ONE_POINT_FIVE,
    STOPBITS_TWO,
    Serial,
    SerialException,
    SerialTimeoutException,
)

_SERIAL_DATA_BITS = {5: FIVEBITS, 6: SIXBITS, 7: SEVENBITS, 8: EIGHTBITS}
_SERIAL_PARITY = {
    "none": PARITY_NONE,
    "even": PARITY_EVEN,
    "odd": PARITY_ODD,
    "mark": PARITY_MARK,
    "space": PARITY_SPACE,
}
_SERIAL_STOP_BITS: dict[float, float] = {
    1: STOPBITS_ONE,
    1.5: STOPBITS_ONE_POINT_FIVE,
    2: STOPBITS_TWO,
}


class TcpScpiTransport:
    """Dependency-free raw TCP transport for newline-terminated SCPI.

    The socket is opened lazily. A transport can therefore be created during
    provider setup or description without contacting hardware. Each instance
    owns at most one socket generation: any connection or protocol failure
    requires the provider to construct and identify a new driver.
    """

    def __init__(
        self,
        host: str,
        port: int,
        *,
        timeout_seconds: float = 5.0,
        terminator: bytes = b"\n",
        encoding: str = "ascii",
        max_response_bytes: int = 16 * 1024 * 1024,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.terminator = terminator
        self.encoding = encoding
        self.max_response_bytes = max_response_bytes
        self._socket: socket.socket | None = None
        self._receive_buffer = bytearray()
        self._state: Literal["new", "connected", "broken", "closed"] = "new"
        self._lock = RLock()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._state == "connected"

    def connect(self) -> None:
        with self._lock:
            if self._state == "connected":
                return
            if self._state != "new":
                raise TransportError(
                    f"SCPI transport is {self._state}",
                    operation="connect",
                    command_may_have_reached_device=False,
                )
            connection: socket.socket | None = None
            try:
                connection = socket.create_connection(
                    (self.host, self.port),
                    timeout=self.timeout_seconds,
                )
                connection.settimeout(self.timeout_seconds)
            except OSError as error:
                self._break_connection(connection)
                raise TransportError(
                    f"failed to connect to {self.host}:{self.port}",
                    operation="connect",
                    command_may_have_reached_device=False,
                ) from error
            self._socket = connection
            self._state = "connected"

    def write(self, command: str) -> None:
        with self._lock:
            connection = self._connection()
            try:
                payload = command.encode(self.encoding) + self.terminator
            except UnicodeEncodeError as error:
                self._break_connection()
                raise TransportError(
                    "SCPI command is not valid transport text",
                    operation="write",
                    command_may_have_reached_device=False,
                ) from error
            try:
                connection.sendall(payload)
            except OSError as error:
                self._break_connection()
                raise TransportError(
                    "SCPI write failed",
                    operation="write",
                    command_may_have_reached_device=True,
                ) from error

    def query(self, command: str) -> str:
        with self._lock:
            self.write(command)
            response = self._read_line()
            try:
                return response.decode(self.encoding)
            except UnicodeDecodeError as error:
                self._break_connection()
                raise TransportError(
                    "SCPI response is not valid text",
                    operation="query",
                    command_may_have_reached_device=True,
                ) from error

    def close(self) -> None:
        with self._lock:
            connection = self._socket
            self._socket = None
            self._receive_buffer.clear()
            self._state = "closed"
            if connection is None:
                return
            try:
                connection.close()
            except OSError as error:
                raise TransportError(
                    "failed to close SCPI socket",
                    operation="close",
                    command_may_have_reached_device=False,
                ) from error

    def _connection(self) -> socket.socket:
        self.connect()
        connection = self._socket
        assert connection is not None
        return connection

    def _read_line(self) -> bytes:
        terminator = self.terminator
        while True:
            boundary = self._receive_buffer.find(terminator)
            if boundary >= 0:
                response = bytes(self._receive_buffer[:boundary])
                del self._receive_buffer[: boundary + len(terminator)]
                return response
            connection = self._connection()
            try:
                chunk = connection.recv(64 * 1024)
            except OSError as error:
                self._break_connection()
                raise TransportError(
                    "SCPI response read failed",
                    operation="query",
                    command_may_have_reached_device=True,
                ) from error
            if not chunk:
                self._break_connection()
                raise TransportError(
                    "SCPI connection closed before response terminator",
                    operation="query",
                    command_may_have_reached_device=True,
                )
            self._receive_buffer.extend(chunk)
            if len(self._receive_buffer) > self.max_response_bytes:
                self._break_connection()
                raise TransportError(
                    "SCPI response exceeded configured size limit",
                    operation="query",
                    command_may_have_reached_device=True,
                )

    def _break_connection(self, connection: socket.socket | None = None) -> None:
        active = self._socket if connection is None else connection
        self._socket = None
        self._receive_buffer.clear()
        if self._state != "closed":
            self._state = "broken"
        if active is not None:
            with suppress(OSError):
                active.close()


class SerialByteTransport:
    """One-generation binary serial transport with explicit response framing."""

    def __init__(
        self,
        port: str,
        *,
        baud_rate: int = 9600,
        timeout_seconds: float = 1.0,
        write_timeout_seconds: float = 1.0,
        data_bits: Literal[5, 6, 7, 8] = 8,
        parity: Literal["none", "even", "odd", "mark", "space"] = "none",
        stop_bits: float = 1.0,
        xonxoff: bool = False,
        rtscts: bool = False,
        dsrdtr: bool = False,
    ) -> None:
        if stop_bits not in _SERIAL_STOP_BITS:
            raise ValueError("serial stop_bits must be 1, 1.5, or 2")
        self.port = port
        self.baud_rate = baud_rate
        self.timeout_seconds = timeout_seconds
        self.write_timeout_seconds = write_timeout_seconds
        self.data_bits = data_bits
        self.parity = parity
        self.stop_bits = stop_bits
        self.xonxoff = xonxoff
        self.rtscts = rtscts
        self.dsrdtr = dsrdtr
        self._serial: Serial | None = None
        self._state: Literal["new", "connected", "broken", "closed"] = "new"
        self._lock = RLock()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._state == "connected"

    def connect(self) -> None:
        with self._lock:
            if self._state == "connected":
                return
            if self._state != "new":
                raise TransportError(
                    f"serial transport is {self._state}",
                    operation="connect",
                    command_may_have_reached_device=False,
                )
            try:
                connection = Serial(
                    port=self.port,
                    baudrate=self.baud_rate,
                    bytesize=_SERIAL_DATA_BITS[self.data_bits],
                    parity=_SERIAL_PARITY[self.parity],
                    stopbits=_SERIAL_STOP_BITS[self.stop_bits],
                    timeout=self.timeout_seconds,
                    write_timeout=self.write_timeout_seconds,
                    xonxoff=self.xonxoff,
                    rtscts=self.rtscts,
                    dsrdtr=self.dsrdtr,
                )
            except (OSError, SerialException, ValueError) as error:
                self._state = "broken"
                raise TransportError(
                    f"failed to open serial port {self.port!r}",
                    operation="connect",
                    command_may_have_reached_device=False,
                ) from error
            self._serial = connection
            self._state = "connected"

    def send(self, request: bytes, /) -> None:
        if not request:
            raise ValueError("serial request must be non-empty")
        with self._lock:
            connection = self._connection()
            try:
                self._write_request(connection, request)
            except (OSError, SerialException) as error:
                self._break_connection()
                raise TransportError(
                    "serial write outcome is unknown",
                    operation="write",
                    command_may_have_reached_device=True,
                ) from error

    def exchange(self, request: bytes, response_size: int, /) -> bytes:
        if not request:
            raise ValueError("serial request must be non-empty")
        if response_size < 1:
            raise ValueError("serial response size must be positive")
        with self._lock:
            connection = self._connection()
            try:
                self._write_request(connection, request)
                response = connection.read(response_size)
                if len(response) != response_size:
                    raise SerialTimeoutException("serial response timed out")
                return response
            except (OSError, SerialException) as error:
                self._break_connection()
                raise TransportError(
                    "serial request outcome is unknown",
                    operation="exchange",
                    command_may_have_reached_device=True,
                ) from error

    @staticmethod
    def _write_request(connection: Serial, request: bytes) -> None:
        written = connection.write(request)
        connection.flush()
        if written != len(request):
            raise SerialTimeoutException("partial serial write")

    def close(self) -> None:
        with self._lock:
            connection = self._serial
            self._serial = None
            self._state = "closed"
            if connection is None:
                return
            try:
                connection.close()
            except (OSError, SerialException) as error:
                raise TransportError(
                    "failed to close serial port",
                    operation="close",
                    command_may_have_reached_device=False,
                ) from error

    def _connection(self) -> Serial:
        self.connect()
        connection = self._serial
        assert connection is not None
        return connection

    def _break_connection(self) -> None:
        connection = self._serial
        self._serial = None
        if self._state != "closed":
            self._state = "broken"
        if connection is not None:
            with suppress(OSError, SerialException):
                connection.close()


__all__ = ["SerialByteTransport", "TcpScpiTransport"]
