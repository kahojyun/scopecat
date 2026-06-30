from __future__ import annotations

from scopecat.results import MeasurementSink
from tests.support.managed_instruments import (
    BlockingManagedInstrument,
    FailingManagedInstrument,
    desired_field,
    native_context_for_first_point,
    quantity_state,
)


def test_managed_driver_diagnostics_are_stable() -> None:
    validation_diagnostics = BlockingManagedInstrument().validate(
        desired_field(
            capability_id="set_frequency",
            field_path="frequency",
            value=quantity_state(5.0, "GHz"),
        )
    )
    result = FailingManagedInstrument().acquire(
        context=native_context_for_first_point(),
        sink=MeasurementSink(run_id="run_test"),
    )

    assert validation_diagnostics[0].code == "managed_driver_blocked"
    assert result.diagnostics[0].code == "managed_measure_failed"
