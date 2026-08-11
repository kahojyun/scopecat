"""Strict transcript transports for driver tests and notebook prototyping.

Generated adapters own the generic driver envelopes and ref mapping; concrete
drivers receive typed patches and operation/acquisition arguments. These helpers
therefore exercise device policy at the transport boundary: ``ScriptedTransport``
checks every command and response in order and ``assert_complete()`` verifies
that the driver consumed the complete expected exchange.
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
