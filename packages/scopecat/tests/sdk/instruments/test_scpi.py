from __future__ import annotations

import pytest

import scopecat.sdk.instruments as instrument_sdk
from scopecat.sdk.instruments import (
    ScpiProtocolError,
    format_number,
    parse_bool,
    query_bool,
    query_csv_floats,
    query_float,
    query_identity,
    query_int,
    query_string,
    query_text,
)


class StubTransport:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses

    def write(self, command: str) -> None:
        pass

    def query(self, command: str) -> str:
        return self.responses[command]

    def close(self) -> None:
        pass


def test_scpi_helpers_are_public_from_the_sdk_facade() -> None:
    assert instrument_sdk.query_float is query_float
    assert instrument_sdk.ScpiProtocolError is ScpiProtocolError


def test_typed_queries_decode_text_responses() -> None:
    transport = StubTransport(
        {
            "TEXT?": " response \n",
            "STRING?": ' "trace" \n',
            "FLOAT?": "1.25\n",
            "INT?": "42\n",
            "BOOL?": "ON\n",
            "CSV?": "1, 2.5, -3\n",
        }
    )

    assert query_text(transport, "TEXT?") == "response"
    assert query_string(transport, "STRING?") == "trace"
    assert query_float(transport, "FLOAT?") == 1.25
    assert query_int(transport, "INT?") == 42
    assert query_bool(transport, "BOOL?") is True
    assert query_csv_floats(transport, "CSV?") == (1.0, 2.5, -3.0)


def test_identity_query_preserves_vendor_fields() -> None:
    identity = query_identity(
        StubTransport({"*IDN?": "Vendor,Model,Serial,FW,Build\n"})
    )

    assert identity.manufacturer == "Vendor"
    assert identity.model == "Model"
    assert identity.serial_number == "Serial"
    assert identity.firmware == "FW,Build"
    assert identity.raw == "Vendor,Model,Serial,FW,Build"


def test_protocol_error_identifies_the_failed_command() -> None:
    with pytest.raises(ScpiProtocolError, match=r"VOLT\?") as raised:
        query_float(StubTransport({"VOLT?": "not-a-number"}), "VOLT?")

    assert raised.value.command == "VOLT?"
    assert raised.value.response == "not-a-number"


@pytest.mark.parametrize(
    ("response", "expected"),
    [("1", True), ("on", True), ("0", False), ("OFF", False)],
)
def test_parse_bool_accepts_standard_scpi_literals(
    response: str,
    expected: bool,
) -> None:
    assert parse_bool(response, command="OUTP?") is expected


def test_format_number_rejects_non_finite_values() -> None:
    assert format_number(1.25) == "1.25"
    with pytest.raises(ValueError, match="finite"):
        format_number(float("inf"))
