"""Small synchronous transports for line-oriented SCPI instruments."""

from __future__ import annotations

import socket
from contextlib import suppress
from threading import RLock
from typing import Literal, Protocol


class ScpiTransport(Protocol):
    """The text command boundary shared by all drivers in this package."""

    def write(self, command: str) -> None: ...

    def query(self, command: str) -> str: ...

    def close(self) -> None: ...


class TransportError(ConnectionError):
    """A transport failure whose command may already have reached the device."""


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
                raise TransportError(f"SCPI transport is {self._state}")
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
                    f"failed to connect to {self.host}:{self.port}"
                ) from error
            self._socket = connection
            self._state = "connected"

    def write(self, command: str) -> None:
        with self._lock:
            connection = self._connection()
            try:
                payload = command.encode(self.encoding) + self.terminator
                connection.sendall(payload)
            except (OSError, UnicodeEncodeError) as error:
                self._break_connection()
                raise TransportError("SCPI write failed") from error

    def query(self, command: str) -> str:
        with self._lock:
            self.write(command)
            response = self._read_line()
            try:
                return response.decode(self.encoding)
            except UnicodeDecodeError as error:
                self._break_connection()
                raise TransportError("SCPI response is not valid text") from error

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
                raise TransportError("failed to close SCPI socket") from error

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
                raise TransportError("SCPI response read failed") from error
            if not chunk:
                self._break_connection()
                raise TransportError(
                    "SCPI connection closed before response terminator"
                )
            self._receive_buffer.extend(chunk)
            if len(self._receive_buffer) > self.max_response_bytes:
                self._break_connection()
                raise TransportError("SCPI response exceeded configured size limit")

    def _break_connection(self, connection: socket.socket | None = None) -> None:
        active = self._socket if connection is None else connection
        self._socket = None
        self._receive_buffer.clear()
        if self._state != "closed":
            self._state = "broken"
        if active is not None:
            with suppress(OSError):
                active.close()
