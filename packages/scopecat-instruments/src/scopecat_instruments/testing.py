"""Strict transcript transports for driver tests and notebook prototyping.

Generated adapters own the generic driver envelopes and ref mapping; concrete
drivers receive typed patches and operation/acquisition arguments. These helpers
therefore exercise device policy at the transport boundary: ``ScriptedTransport``
checks every command and response in order and ``assert_complete()`` verifies
that the driver consumed the complete expected exchange. Binary serial drivers
use the parallel ``ScriptedBinaryTransport``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ScriptedExchange:
    operation: Literal["write", "query"]
    command: str
    response: str | None = None

    @classmethod
    def write(cls, command: str) -> ScriptedExchange:
        return cls(operation="write", command=command)

    @classmethod
    def query(cls, command: str, response: str) -> ScriptedExchange:
        return cls(operation="query", command=command, response=response)


@dataclass(frozen=True)
class TranscriptEntry:
    operation: Literal["write", "query"]
    command: str
    response: str | None = None


@dataclass(frozen=True)
class ScriptedBinaryExchange:
    request: bytes
    response: bytes | None = None

    @classmethod
    def send(cls, request: bytes) -> ScriptedBinaryExchange:
        return cls(request)

    @classmethod
    def exchange(cls, request: bytes, response: bytes) -> ScriptedBinaryExchange:
        return cls(request, response)


@dataclass(frozen=True)
class BinaryTranscriptEntry:
    request: bytes
    response: bytes | None = None


class ScriptedTransport:
    """Transport that validates and records one ordered SCPI transcript."""

    def __init__(self, exchanges: list[ScriptedExchange]) -> None:
        self._exchanges = tuple(exchanges)
        self._index = 0
        self.transcript: list[TranscriptEntry] = []
        self.closed = False

    @property
    def remaining(self) -> int:
        return len(self._exchanges) - self._index

    def write(self, command: str) -> None:
        exchange = self._next()
        if exchange.operation != "write" or exchange.command != command:
            raise AssertionError(
                "unexpected SCPI write: "
                f"{command!r}; expected {exchange.operation} {exchange.command!r}"
            )
        self.transcript.append(TranscriptEntry("write", command))

    def query(self, command: str) -> str:
        exchange = self._next()
        if exchange.operation != "query" or exchange.command != command:
            raise AssertionError(
                "unexpected SCPI query: "
                f"{command!r}; expected {exchange.operation} {exchange.command!r}"
            )
        response = exchange.response
        assert response is not None
        self.transcript.append(TranscriptEntry("query", command, response))
        return response

    def close(self) -> None:
        self.closed = True

    def assert_complete(self) -> None:
        if self.remaining:
            next_exchange = self._exchanges[self._index]
            raise AssertionError(
                f"{self.remaining} scripted exchange(s) remain; next is "
                f"{next_exchange.operation} {next_exchange.command!r}"
            )

    def _next(self) -> ScriptedExchange:
        if self._index >= len(self._exchanges):
            raise AssertionError("unexpected SCPI command after transcript end")
        exchange = self._exchanges[self._index]
        self._index += 1
        return exchange


class ScriptedBinaryTransport:
    """Transport that validates exact ordered binary request/response frames."""

    def __init__(self, exchanges: list[ScriptedBinaryExchange]) -> None:
        self._exchanges = tuple(exchanges)
        self._index = 0
        self.transcript: list[BinaryTranscriptEntry] = []
        self.closed = False

    @property
    def remaining(self) -> int:
        return len(self._exchanges) - self._index

    def send(self, request: bytes, /) -> None:
        exchange = self._next(request)
        if exchange.response is not None:
            raise AssertionError("scripted binary send unexpectedly has a response")
        self.transcript.append(BinaryTranscriptEntry(request))

    def exchange(self, request: bytes, response_size: int, /) -> bytes:
        exchange = self._next(request)
        response = exchange.response
        if response is None:
            raise AssertionError("scripted binary exchange has no response")
        if response_size != len(response):
            raise AssertionError(
                f"binary response size {response_size} does not match scripted "
                f"size {len(response)}"
            )
        self.transcript.append(BinaryTranscriptEntry(request, response))
        return response

    def _next(self, request: bytes) -> ScriptedBinaryExchange:
        if self._index >= len(self._exchanges):
            raise AssertionError("unexpected binary request after transcript end")
        exchange = self._exchanges[self._index]
        self._index += 1
        if request != exchange.request:
            raise AssertionError(
                f"unexpected binary request {request.hex()}; "
                f"expected {exchange.request.hex()}"
            )
        return exchange

    def close(self) -> None:
        self.closed = True

    def assert_complete(self) -> None:
        if self.remaining:
            next_exchange = self._exchanges[self._index]
            raise AssertionError(
                f"{self.remaining} scripted binary exchange(s) remain; next is "
                f"{next_exchange.request.hex()}"
            )


__all__ = [
    "BinaryTranscriptEntry",
    "ScriptedBinaryExchange",
    "ScriptedBinaryTransport",
    "ScriptedExchange",
    "ScriptedTransport",
    "TranscriptEntry",
]
