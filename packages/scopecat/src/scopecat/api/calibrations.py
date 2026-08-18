"""High-level project calibration cohort operations."""

from __future__ import annotations

from scopecat.api._config import LabConfigOperations
from scopecat.api.calibration_planner import (
    CalibrationPlanningContext,
    ProjectCalibrationEvaluator,
)
from scopecat.automation.calibration_definition import CalibrationRegistry
from scopecat.automation.calibration_wire import (
    CalibrationCohortCreateCommand,
    CalibrationCohortCreateReceipt,
    CalibrationCohortListQuery,
    CalibrationCohortMemberListQuery,
    CalibrationCohortMemberPage,
    CalibrationCohortPage,
    CalibrationStatusQuery,
)
from scopecat.automation.calibrations import (
    CalibrationCohort,
    CalibrationCohortSpec,
    CalibrationConfigSourceRef,
    CalibrationStatusSnapshot,
)
from scopecat.automation.definition import ProcedureRegistry
from scopecat.daemon.client import DaemonClient
from scopecat.records.run import ConfigRegistryRunConfigSource


class LabCalibrationOperations:
    """Evaluate, admit, and inspect project-owned calibration cohorts."""

    __slots__ = ("_client", "_config", "_registry")

    def __init__(
        self,
        *,
        client: DaemonClient,
        config: LabConfigOperations,
        procedures: ProcedureRegistry,
        registry: CalibrationRegistry[CalibrationPlanningContext],
    ) -> None:
        for definition in registry.values():
            procedures.resolve(definition.procedure.ref)
        self._client = client
        self._config = config
        self._registry = registry

    @property
    def registry(self) -> CalibrationRegistry[CalibrationPlanningContext]:
        return self._registry

    def planning_context(self) -> CalibrationPlanningContext:
        config, source = self._config.resolve_with_source("active")
        if not isinstance(source, ConfigRegistryRunConfigSource):
            raise RuntimeError(
                "calibration planning requires exact active registry provenance"
            )
        if source.registry_generation is None:
            raise RuntimeError(
                "calibration planning requires an active registry generation"
            )
        return CalibrationPlanningContext(
            config=config,
            config_source=CalibrationConfigSourceRef.from_run_config_source(source),
        )

    def evaluator(self) -> ProjectCalibrationEvaluator:
        """Build a project evaluator over this exact application registry."""

        return ProjectCalibrationEvaluator(
            self,
            self._registry,
            self.planning_context,
        )

    def status(
        self,
        calibration_keys: tuple[str, ...],
        *,
        fanout_scope: str,
    ) -> CalibrationStatusSnapshot:
        receipt = self._client.query_calibration_status(
            CalibrationStatusQuery(
                calibration_keys=calibration_keys,
                fanout_scope=fanout_scope,
            )
        )
        return receipt.snapshot

    def create(
        self,
        cohort_id: str,
        spec: CalibrationCohortSpec,
    ) -> CalibrationCohortCreateReceipt:
        return self._client.create_calibration_cohort(
            CalibrationCohortCreateCommand(cohort_id=cohort_id, spec=spec)
        )

    def get(self, cohort_id: str) -> CalibrationCohort:
        return self._client.get_calibration_cohort(cohort_id).cohort

    def list(
        self,
        *,
        limit: int = 50,
        before: int | None = None,
        fanout_scope: str | None = None,
    ) -> CalibrationCohortPage:
        return self._client.list_calibration_cohorts(
            CalibrationCohortListQuery(
                cursor=before,
                limit=limit,
                fanout_scope=fanout_scope,
            )
        )

    def members(
        self,
        cohort_id: str,
        *,
        limit: int = 50,
        after: int | None = None,
    ) -> CalibrationCohortMemberPage:
        return self._client.list_calibration_cohort_members(
            CalibrationCohortMemberListQuery(
                cohort_id=cohort_id,
                cursor=after,
                limit=limit,
            )
        )


__all__ = ["LabCalibrationOperations"]
