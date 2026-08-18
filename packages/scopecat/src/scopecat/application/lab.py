"""User-owned composition root shared by the daemon and notebook clients."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from scopecat.automation.calibration_definition import CalibrationRegistry
from scopecat.automation.definition import ProcedureRegistry
from scopecat.automation.intervals import ProcedureScheduleRegistry
from scopecat.records.config import ConfigProfileSnapshot

if TYPE_CHECKING:
    from scopecat.api.calibration_planner import CalibrationPlanningContext
    from scopecat.api.lab import LabClient
    from scopecat.api.procedure_planner import ProcedurePlanningContext
    from scopecat.automation.calibration_definition import RegisteredCalibration
    from scopecat.automation.definition import RegisteredProcedure
    from scopecat.automation.intervals import RegisteredProcedureSchedule
    from scopecat.planning.system import ExperimentSystemBuilder

type BootstrapConfigFactory = Callable[[], ConfigProfileSnapshot]


@dataclass(frozen=True, slots=True, init=False)
class LabApplication:
    """Version-controlled executable composition for one lab project.

    The application owns the initial snapshot because constructing configuration
    may require Python. Its factory stays lazy so ordinary notebook connections
    do not read seed inputs. Later accepted entries and activation state belong
    to the daemon. Instrument backend composition is declared separately in the
    project manifest and loaded only by the isolated worker.
    """

    build_experiment_system: ExperimentSystemBuilder | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    bootstrap_config: BootstrapConfigFactory | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    procedures: ProcedureRegistry = field(
        default_factory=ProcedureRegistry,
        repr=False,
    )
    procedure_schedules: ProcedureScheduleRegistry[ProcedurePlanningContext] = field(
        default_factory=ProcedureScheduleRegistry,
        repr=False,
    )
    calibrations: CalibrationRegistry[CalibrationPlanningContext] = field(
        default_factory=CalibrationRegistry,
        repr=False,
    )

    def __init__(
        self,
        build_experiment_system: ExperimentSystemBuilder | None = None,
        bootstrap_config: BootstrapConfigFactory | None = None,
        procedures: Iterable[RegisteredProcedure] | ProcedureRegistry = (),
        procedure_schedules: (
            Iterable[RegisteredProcedureSchedule[ProcedurePlanningContext]]
            | ProcedureScheduleRegistry[ProcedurePlanningContext]
        ) = (),
        calibrations: (
            Iterable[RegisteredCalibration[CalibrationPlanningContext]]
            | CalibrationRegistry[CalibrationPlanningContext]
        ) = (),
    ) -> None:
        object.__setattr__(
            self,
            "build_experiment_system",
            build_experiment_system,
        )
        object.__setattr__(self, "bootstrap_config", bootstrap_config)
        procedure_registry = (
            procedures
            if isinstance(procedures, ProcedureRegistry)
            else ProcedureRegistry(procedures)
        )
        schedule_registry = (
            procedure_schedules
            if isinstance(procedure_schedules, ProcedureScheduleRegistry)
            else ProcedureScheduleRegistry(procedure_schedules)
        )
        for schedule in schedule_registry.values():
            procedure_registry.resolve(schedule.procedure.ref)
        calibration_registry = (
            calibrations
            if isinstance(calibrations, CalibrationRegistry)
            else CalibrationRegistry(calibrations)
        )
        for definition in calibration_registry.values():
            procedure_registry.resolve(definition.procedure.ref)
        object.__setattr__(self, "procedures", procedure_registry)
        object.__setattr__(self, "procedure_schedules", schedule_registry)
        object.__setattr__(self, "calibrations", calibration_registry)

    def connect(
        self,
        daemon: str,
        *,
        operator: str = "operator",
    ) -> LabClient:
        """Connect notebook code while retaining locally authored closures."""

        from scopecat.api.lab import LabClient

        return LabClient(
            daemon,
            build_experiment_system=self.build_experiment_system,
            procedures=self.procedures,
            procedure_schedules=self.procedure_schedules,
            calibrations=self.calibrations,
            operator=operator,
        )


__all__ = [
    "BootstrapConfigFactory",
    "LabApplication",
]
