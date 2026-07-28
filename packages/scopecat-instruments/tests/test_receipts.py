from __future__ import annotations

import pytest
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import StateValue
from scopecat.sdk.instruments import (
    DriverApplyRequest,
    DriverCollectRequest,
    DriverCollectResult,
    DriverInvokeRequest,
    DriverPropertyWrite,
)

from scopecat_instruments.drivers import (
    KeysightE5080B,
    YokogawaGS200,
)
from scopecat_instruments.interfaces import (
    DC_MONITOR,
    DC_SOURCE,
    NETWORK_SWEEP,
)
from scopecat_instruments.testing import ScriptedTransport
from scopecat_instruments.transport import TransportError


class _FailingTransport:
    def write(self, command: str) -> None:
        raise TransportError(f"failed write: {command}")

    def query(self, command: str) -> str:
        raise TransportError(f"failed query: {command}")

    def close(self) -> None:
        pass


def test_gs200_baseline_transport_loss_is_raised() -> None:
    driver = YokogawaGS200("bias", _FailingTransport())

    with pytest.raises(TransportError, match="failed query"):
        driver.apply_state(
            _apply_request(
                DC_SOURCE,
                "source_mode",
                StateValue("voltage"),
            )
        )


def test_apply_transport_loss_reports_unknown_not_not_applied() -> None:
    driver = KeysightE5080B("vna", _FailingTransport())
    receipt = driver.apply_state(
        _apply_request(
            NETWORK_SWEEP,
            "start_frequency",
            StateValue(Quantity(4.9e9, "Hz")),
        )
    )

    assert receipt.status == "unknown"
    assert receipt.problems[0].code == "instrument_apply_outcome_unknown"


def test_acquisition_transport_loss_reports_unknown() -> None:
    driver = KeysightE5080B("vna", _FailingTransport())
    receipt = driver.collect(_collect_request(NETWORK_SWEEP, "sweep", "s_parameter"))

    assert receipt.status == "unknown"
    assert receipt.problems[0].code == "instrument_collect_outcome_unknown"


def test_collect_without_monitor_option_is_not_collected_without_io() -> None:
    driver = YokogawaGS200("bias", ScriptedTransport([]))

    receipt = driver.collect(
        _collect_request(DC_MONITOR, "monitor", "monitored_current")
    )

    assert receipt.status == "not_collected"
    assert receipt.problems[0].code == "gs200_monitor_option_required"


def test_unsupported_invoke_returns_not_invoked_without_io() -> None:
    driver = KeysightE5080B("vna", ScriptedTransport([]))

    receipt = driver.invoke(
        DriverInvokeRequest(
            interface_id=NETWORK_SWEEP,
            operation_id="calibrate",
        )
    )

    assert receipt.status == "not_invoked"
    assert receipt.problems[0].code == "instrument_operation_not_implemented"


def _apply_request(
    interface_id: str,
    property_id: str,
    value: StateValue,
) -> DriverApplyRequest:
    return DriverApplyRequest(
        assignments=(
            DriverPropertyWrite(
                interface_id=interface_id,
                property_id=property_id,
                value=value,
            ),
        )
    )


def _collect_request(
    interface_id: str,
    acquisition_id: str,
    result_id: str,
) -> DriverCollectRequest:
    return DriverCollectRequest(
        interface_id=interface_id,
        acquisition_id=acquisition_id,
        results=(
            DriverCollectResult(
                request_id=result_id,
                result_id=result_id,
            ),
        ),
    )
