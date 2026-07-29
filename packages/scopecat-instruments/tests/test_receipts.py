from __future__ import annotations

import pytest
from scopecat.kernel.quantity import Quantity
from scopecat.sdk.instruments import (
    AcquisitionRef,
    AcquisitionResultRef,
    DriverAcquisition,
    DriverOperation,
    DriverRejected,
    DriverScalar,
    DriverStatePatch,
    DriverUnknown,
    PropertyRef,
)
from scopecat.sdk.instruments.scpi import TransportError

from scopecat_instruments.drivers import (
    KeysightE5080B,
    YokogawaGS200,
)
from scopecat_instruments.members import (
    DC_SOURCE_MODE,
    NETWORK_SWEEP,
    NETWORK_SWEEP_ACQUISITION,
    NETWORK_SWEEP_S_PARAMETER_RESULT,
    NETWORK_SWEEP_START_FREQUENCY,
)
from scopecat_instruments.testing import ScriptedTransport


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
                DC_SOURCE_MODE,
                "voltage",
            )
        )


def test_apply_transport_loss_reports_unknown_not_not_applied() -> None:
    driver = KeysightE5080B("vna", _FailingTransport())
    receipt = driver.apply_state(
        _apply_request(
            NETWORK_SWEEP_START_FREQUENCY,
            Quantity(4.9e9, "Hz"),
        )
    )

    assert isinstance(receipt, DriverUnknown)
    assert receipt.problems[0].code == "instrument_apply_outcome_unknown"


def test_acquisition_transport_loss_reports_unknown() -> None:
    driver = KeysightE5080B("vna", _FailingTransport())
    receipt = driver.collect(
        _collect_request(
            NETWORK_SWEEP_ACQUISITION,
            NETWORK_SWEEP_S_PARAMETER_RESULT,
        )
    )

    assert isinstance(receipt, DriverUnknown)
    assert receipt.problems[0].code == "instrument_collect_outcome_unknown"


def test_unsupported_invoke_returns_not_invoked_without_io() -> None:
    driver = KeysightE5080B("vna", ScriptedTransport([]))

    receipt = driver.invoke(
        DriverOperation(target=NETWORK_SWEEP.operation("calibrate"))
    )

    assert isinstance(receipt, DriverRejected)
    assert receipt.problems[0].code == "instrument_operation_not_implemented"


def _apply_request(
    target: PropertyRef,
    value: DriverScalar,
) -> DriverStatePatch:
    return DriverStatePatch(values={target: value})


def _collect_request(
    acquisition: AcquisitionRef,
    result: AcquisitionResultRef,
) -> DriverAcquisition:
    return DriverAcquisition(
        target=acquisition,
        results=frozenset({result}),
    )
