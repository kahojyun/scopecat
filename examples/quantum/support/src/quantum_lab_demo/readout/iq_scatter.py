"""Black-box shot-level readout IQ data recorder."""

from __future__ import annotations

from scopecat.experiments import PlanSnapshot
from scopecat.runner import (
    MeasurementSink,
    RunnerAdapterResult,
    RunnerContext,
)

from quantum_lab_demo.readout.responses import (
    ReadoutIQResponseModel,
    _record_iq_shot,
)


class ReadoutIQScatterAdapter:
    adapter_id = "quantum_lab_demo.readout_iq_scatter"
    adapter_version = "v0"

    def __init__(self, response_model: ReadoutIQResponseModel) -> None:
        self._response_model = response_model

    def run(
        self,
        context: RunnerContext,
        sink: MeasurementSink,
    ) -> RunnerAdapterResult:
        assert isinstance(context.plan, PlanSnapshot)
        shot_count = context.plan.acquisition.estimated_records
        for shot_index in range(shot_count):
            _record_iq_shot(
                sink=sink,
                point_index=shot_index,
                shot_index=shot_index,
                response_model=self._response_model,
                producer_id=self.adapter_id,
                producer_kind="adapter",
            )
        return RunnerAdapterResult(
            metadata={
                "source": "quantum-lab-demo",
                "sample_reference": "sample-public://readout/iq-quality",
                "source_function": "readout IQ scatter",
            }
        )


__all__ = [
    "ReadoutIQScatterAdapter",
]
