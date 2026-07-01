"""Black-box readout-frequency data recorder derived from a synthetic sample."""

from __future__ import annotations

from scopecat.experiments import PlanSnapshot
from scopecat.instruments.state import ExecutionPoint
from scopecat.models.parameter import Quantity
from scopecat.runner import (
    MeasurementSink,
    RunnerAdapterResult,
    RunnerContext,
)

from quantum_lab_demo.readout.responses import (
    ReadoutResponseModel,
    _record_raw_measurement,
    _settings_from_config,
)


class ReadoutFrequencyCalibrationAdapter:
    adapter_id = "quantum_lab_demo.readout_frequency_calibration"
    adapter_version = "v0"

    def __init__(self, response_model: ReadoutResponseModel) -> None:
        self._response_model = response_model

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        settings = _settings_from_config(context.config)
        assert isinstance(context.plan, PlanSnapshot)
        for point in context.plan.points:
            readout_frequency = point.row["readout_frequency"]
            if not isinstance(readout_frequency, Quantity):
                continue
            lo_frequency = point.row.get("lo_frequency")
            coordinates = {"readout_frequency": readout_frequency}
            if isinstance(lo_frequency, Quantity):
                coordinates["lo_frequency"] = lo_frequency
            _record_raw_measurement(
                sink=sink,
                point=ExecutionPoint(
                    index=point.point_id,
                    coordinates=coordinates,
                ),
                settings=settings,
                response_model=self._response_model,
                producer_id=self.adapter_id,
                producer_kind="adapter",
            )
        return RunnerAdapterResult(
            metadata={
                "source": "quantum-lab-demo",
                "sample_reference": "sample-public://readout/frequency-calibration-s21",
                "source_function": "readout frequency response",
            }
        )


__all__ = [
    "ReadoutFrequencyCalibrationAdapter",
]
