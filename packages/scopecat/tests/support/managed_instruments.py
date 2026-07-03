from __future__ import annotations

from pathlib import Path

from scopecat.experiments import plan_experiment
from scopecat.instruments import (
    DriverDiagnostic,
    ManagedInstrument,
    MeasurementContext,
    StateChange,
    asset_field,
    capability,
    number_field,
    quantity_field,
)
from scopecat.instruments.sdk import AcquisitionContext
from scopecat.instruments.state import (
    AcquisitionPlan,
    DesiredResourceState,
    DesiredStateField,
    ExecutionPoint,
    StateValue,
)
from scopecat.models.config import ConfigProfileSnapshot, load_config_profile
from scopecat.models.parameter import Quantity
from scopecat.results import MeasurementSink
from tests.support.workflow_fixtures import load_experiment

EXAMPLE_DIR = Path(__file__).parents[4] / "fixtures" / "core" / "simple_scan"


class ManagedSignalInstrument(ManagedInstrument):
    def __init__(self, *, instrument_id: str = "source-0") -> None:
        self.contexts: list[MeasurementContext] = []
        self.applied: list[StateChange] = []
        super().__init__(
            instrument_id=instrument_id,
            implementation_id="tests.managed_signal",
            implementation_version="v0",
            capabilities=[
                capability(
                    "set_frequency",
                    fields=[quantity_field("frequency", unit="GHz")],
                ),
                capability("set_gain", fields=[number_field("gain")]),
                capability("play_program", fields=[asset_field("program")]),
                capability("scalar_signal", acquisition=True),
            ],
            metadata={"mode": "test_offline"},
        )

    def apply_state(self, changes: StateChange) -> None:
        self.applied.append(changes)

    def measure(
        self,
        context: MeasurementContext,
        sink: MeasurementSink,
    ) -> None:
        self.contexts.append(context)
        if context.acquisition_kind != "scalar":
            return
        sink.record(
            point_index=context.point_index,
            coordinates=context.coordinates,
            observables={"signal": Quantity(value=1.0, unit="ratio")},
            metadata={"implementation": self.implementation_id},
        )


class BlockingManagedInstrument(ManagedSignalInstrument):
    def validate_state(self, changes: StateChange):
        del changes
        return [
            DriverDiagnostic(
                severity="error",
                code="managed_driver_blocked",
                message="driver blocked",
                path="driver",
            )
        ]


class FailingManagedInstrument(ManagedSignalInstrument):
    def measure(
        self,
        context: MeasurementContext,
        sink: MeasurementSink,
    ) -> None:
        del context, sink
        raise DriverDiagnostic(
            severity="error",
            code="managed_measure_failed",
            message="measurement failed",
            path="measure",
        )


def load_config() -> ConfigProfileSnapshot:
    return load_config_profile(EXAMPLE_DIR / "config-profile.json")


def desired_field(
    *,
    capability_id: str,
    field_path: str,
    value: StateValue,
) -> list[DesiredResourceState]:
    return [
        DesiredResourceState(
            resource_id="source-0",
            capability_id=capability_id,
            fields=[DesiredStateField(field_path=field_path, value=value)],
        )
    ]


def quantity_state(value: float, unit: str) -> StateValue:
    return StateValue(kind="quantity", quantity=Quantity(value=value, unit=unit))


def number_state(value: float) -> StateValue:
    return StateValue(kind="number", value=value)


def asset_state(asset_id: str) -> StateValue:
    return StateValue(kind="asset", asset_id=asset_id)


def context_for_first_point() -> AcquisitionContext:
    config = load_config()
    assert config.parameter_build is not None
    plan = plan_experiment(load_experiment(), config.parameter_build)
    desired = desired_field(
        capability_id="set_frequency",
        field_path="frequency",
        value=quantity_state(4.9, "GHz"),
    )
    return AcquisitionContext(
        run_id="run_test",
        plan=plan,
        point=ExecutionPoint(
            index=0,
            coordinates={"drive_frequency": Quantity(value=4.9, unit="GHz")},
        ),
        point_count=len(plan.points),
        record_index_offset=0,
        records_for_point=1,
        acquisition_plan=AcquisitionPlan(
            kind=plan.acquisition.kind,
            record="point",
            shots=plan.acquisition.shots,
            repetitions=plan.acquisition.repetitions,
            estimated_records=plan.acquisition.estimated_records,
        ),
        desired_state=desired,
    )
