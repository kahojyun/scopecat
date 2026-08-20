"""Typed helpers for text-based SCPI drivers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol


class ScpiTransport(Protocol):
    """Synchronous text transport owned by a driver."""

    def write(self, command: str) -> None: ...

    def query(self, command: str) -> str: ...

    def close(self) -> None: ...


class TransportError(ConnectionError):
    """A failed transport generation with explicit command certainty."""

    def __init__(
        self,
        message: str,
        *,
        operation: Literal["connect", "write", "read", "query", "exchange", "close"],
        command_may_have_reached_device: bool,
    ) -> None:
        self.operation = operation
        self.command_may_have_reached_device = command_may_have_reached_device
        self.requires_replacement = True
        super().__init__(message)


class ScpiProtocolError(ValueError):
    """A SCPI response that cannot be decoded as the requested type."""

    def __init__(self, command: str, response: str, message: str) -> None:
        self.command = command
        self.response = response
        super().__init__(f"{message} for SCPI command {command!r}: {response!r}")


@dataclass(frozen=True)
class ScpiIdentity:
    manufacturer: str
    model: str
    serial_number: str
    firmware: str
    raw: str


def format_number(value: float) -> str:
    """Format a finite number without unnecessary SCPI precision."""

    if not math.isfinite(value):
        raise ValueError("SCPI numeric values must be finite")
    return format(value, ".15g")


def parse_float(response: str, *, command: str) -> float:
    try:
        value = float(response.strip())
    except ValueError as error:
        raise ScpiProtocolError(
            command, response, "expected a floating-point response"
        ) from error
    if not math.isfinite(value):
        raise ScpiProtocolError(command, response, "expected a finite response")
    return value


def parse_int(response: str, *, command: str) -> int:
    try:
        return int(response.strip())
    except ValueError as error:
        raise ScpiProtocolError(
            command, response, "expected an integer response"
        ) from error


def parse_bool(response: str, *, command: str) -> bool:
    selected = response.strip().upper()
    if selected in {"1", "ON"}:
        return True
    if selected in {"0", "OFF"}:
        return False
    raise ScpiProtocolError(command, response, "expected a boolean response")


def parse_identity(response: str, *, command: str) -> ScpiIdentity:
    raw = response.strip()
    parts = [part.strip() for part in raw.split(",")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ScpiProtocolError(command, response, "expected an IEEE 488.2 identity")
    return ScpiIdentity(
        manufacturer=parts[0],
        model=parts[1],
        serial_number=parts[2] if len(parts) > 2 else "",
        firmware=",".join(parts[3:]) if len(parts) > 3 else "",
        raw=raw,
    )


def query_text(transport: ScpiTransport, command: str) -> str:
    return transport.query(command).strip()


def query_string(transport: ScpiTransport, command: str) -> str:
    response = query_text(transport, command)
    if len(response) >= 2 and response[0] == response[-1] and response[0] in {"'", '"'}:
        return response[1:-1]
    return response


def query_float(transport: ScpiTransport, command: str) -> float:
    return parse_float(transport.query(command), command=command)


def query_int(transport: ScpiTransport, command: str) -> int:
    return parse_int(transport.query(command), command=command)


def query_bool(transport: ScpiTransport, command: str) -> bool:
    return parse_bool(transport.query(command), command=command)


def query_csv_floats(transport: ScpiTransport, command: str) -> tuple[float, ...]:
    response = transport.query(command)
    return tuple(
        parse_float(part, command=command) for part in response.strip().split(",")
    )


def query_identity(transport: ScpiTransport, command: str = "*IDN?") -> ScpiIdentity:
    return parse_identity(transport.query(command), command=command)
