"""Run admission application service."""

from __future__ import annotations

from scopecat.adapters.sqlite import (
    ControlPlaneConflict,
    ControlPlaneNotFound,
    SQLiteControlPlane,
    SQLiteRunRepository,
)
from scopecat.control.models import (
    ControlRun,
    RunAdmissionRecord,
)
from scopecat.daemon.wire import (
    AttentionResolutionReceipt,
    RunAdmission,
    RunSubmission,
)
from scopecat.kernel.problems import (
    ProblemPhase,
    problem,
)
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.runs.admission import build_run_admission
from scopecat.runs.repository import (
    TerminalRunCommit,
)

from .errors import BackendConflict, BackendNotFound


class AdmissionService:
    """Own idempotent admission and admitted snapshots."""

    def __init__(
        self,
        *,
        control: SQLiteControlPlane,
        runs: SQLiteRunRepository,
    ) -> None:
        self._control = control
        self._runs = runs

    def submit_run(self, submission: RunSubmission) -> RunAdmission:
        skeleton = build_run_admission(
            config=submission.config,
            request=submission.request,
            config_source=submission.config_source,
        )
        admission = RunAdmissionRecord(
            submission_id=submission.submission_id,
            submission_content_hash=submission.intent_content_hash,
            run_id=skeleton.manifest.run_id,
            plan=submission.plan,
            admitted_at=skeleton.manifest.created_at,
        )
        prepared = self._runs.prepare_run_skeleton(skeleton)
        try:
            with self._control.transaction() as connection:
                run = self._control.admit_run_in_transaction(connection, admission)
                if run.run_id == admission.run_id:
                    self._runs.commit_run_skeleton_in_transaction(
                        connection,
                        prepared,
                    )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        return self._wire_admission(run)

    def resolve_attention(
        self,
        run_id: str,
    ) -> AttentionResolutionReceipt:
        run = self._control_run(run_id)
        if run.state != "attention_required":
            raise BackendConflict("run does not require operator attention")
        outcome = RunOutcome(
            run_id=run_id,
            result="failed",
            certainty="indeterminate",
            problems=(
                problem(
                    "daemon.executor_loss_reconciled",
                    "operator reconciled external state after executor loss",
                    phase=ProblemPhase.EXECUTION,
                ),
            ),
        )
        prepared = self._runs.prepare_terminal_commit(
            TerminalRunCommit(run_id=run_id, outcome=outcome)
        )
        try:
            with self._control.transaction() as connection:
                released = self._control.release_run_resources_in_transaction(
                    connection,
                    run_id,
                )
                self._runs.commit_prepared_terminal_in_transaction(
                    connection,
                    prepared,
                )
                self._control.close_run_in_transaction(
                    connection,
                    run_id,
                )
        except ControlPlaneConflict as error:
            raise BackendConflict(str(error)) from error
        return AttentionResolutionReceipt(
            run_id=run_id,
            state="closed",
            released_resource_count=released,
        )

    def _control_run(self, run_id: str) -> ControlRun:
        try:
            return self._control.get_run(run_id)
        except ControlPlaneNotFound as error:
            raise BackendNotFound(str(error)) from error

    def _wire_admission(self, run: ControlRun) -> RunAdmission:
        return RunAdmission(
            submission_id=run.admission.submission_id,
            manifest=self._runs.read_manifest(run.run_id),
        )
