"""Route-local environment operation workflow composition."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scopecat.environment_operation.operation_review import (
    EnvironmentOperationReview,
    review_uv_sync_operation,
)
from scopecat.environment_operation.runtime_probe import (
    UvRuntimeProbeExecutionRecord,
    UvRuntimeProbeIntent,
    UvRuntimeProbeResult,
    execute_uv_runtime_probe,
)
from scopecat.environment_operation.uv_sync import (
    DEFAULT_TIMEOUT_SECONDS,
    CommandRunner,
    UvSyncExecutionRecord,
    UvSyncIntent,
    UvSyncResult,
    execute_uv_sync,
)

SYNC_SUCCESS_STATUS = "uv_sync_completed_success"


@dataclass(frozen=True)
class UvSyncOperationRun:
    """Typed route-local composition of one uv sync operation vertical."""

    sync_intent: UvSyncIntent
    sync_execution_record: UvSyncExecutionRecord
    sync_result: UvSyncResult
    operation_review: EnvironmentOperationReview
    runtime_probe_state: str
    runtime_probe_intent: UvRuntimeProbeIntent | None
    runtime_probe_execution_record: UvRuntimeProbeExecutionRecord | None
    runtime_probe_result: UvRuntimeProbeResult | None

    def to_summary(self) -> dict[str, Any]:
        """Project the composed run into a local review summary."""

        return {
            "environment_operation_run_policy": {
                "summary_policy": "review_summary",
                "run_authority": "route_local_uv_sync_operation_workflow",
                "manager_scope": "uv_only",
                "process_execution": "performed_for_approved_uv_sync_intent",
                "operation_review": "performed",
                "runtime_probe": self.runtime_probe_state,
                "output_capture": "bounded_stdout_stderr_summaries",
                "dependency_sync_verification": "not_performed",
                "package_install_verification": "not_performed",
                "experiment_code_import": "not_performed",
                "experiment_code_execution": "not_performed",
                "hardware_probe": "not_performed",
                "run_blocking_decision": "not_made",
                "readiness_claim": "not_claimed",
            },
            "uv_sync_result": self.sync_result.to_summary(),
            "operation_review": self.operation_review.to_dict(),
            "runtime_probe": _runtime_probe_summary(
                self.runtime_probe_state,
                self.runtime_probe_intent,
                self.runtime_probe_result,
            ),
        }


def run_uv_sync_operation(
    intent: UvSyncIntent,
    *,
    workspace_root: Path,
    result_id: str | None = None,
    review_id: str | None = None,
    run_runtime_probe: bool = True,
    probe_result_id: str | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    runtime_probe_timeout_seconds: int | None = None,
    runner: CommandRunner | None = None,
    uv_executable: Path | str | None = None,
) -> UvSyncOperationRun:
    """Execute, review, and optionally probe one approved uv sync operation."""

    sync_execution_record = execute_uv_sync(
        intent,
        workspace_root=workspace_root,
        result_id=result_id,
        timeout_seconds=timeout_seconds,
        runner=runner,
        uv_executable=uv_executable,
    )
    sync_result = UvSyncResult.from_execution(intent, sync_execution_record)
    operation_review = review_uv_sync_operation(intent, sync_result, review_id=review_id)

    runtime_probe_state = _runtime_probe_state(run_runtime_probe, sync_result, operation_review)
    runtime_probe_intent = None
    runtime_probe_execution_record = None
    runtime_probe_result = None
    if runtime_probe_state == "performed":
        runtime_probe_intent = UvRuntimeProbeIntent.from_sync_result(intent, sync_result)
        runtime_probe_execution_record = execute_uv_runtime_probe(
            runtime_probe_intent,
            workspace_root=workspace_root,
            probe_result_id=probe_result_id,
            timeout_seconds=runtime_probe_timeout_seconds or timeout_seconds,
            runner=runner,
            uv_executable=uv_executable,
        )
        runtime_probe_result = runtime_probe_execution_record.to_result(runtime_probe_intent)

    return UvSyncOperationRun(
        sync_intent=intent,
        sync_execution_record=sync_execution_record,
        sync_result=sync_result,
        operation_review=operation_review,
        runtime_probe_state=runtime_probe_state,
        runtime_probe_intent=runtime_probe_intent,
        runtime_probe_execution_record=runtime_probe_execution_record,
        runtime_probe_result=runtime_probe_result,
    )


def _runtime_probe_state(
    run_runtime_probe: bool,
    sync_result: UvSyncResult,
    operation_review: EnvironmentOperationReview,
) -> str:
    if not run_runtime_probe:
        return "not_requested"
    if sync_result.result_status != SYNC_SUCCESS_STATUS:
        return "not_eligible_sync_not_successful"
    if sync_result.findings or operation_review.findings:
        return "not_eligible_review_has_findings"
    return "performed"


def _runtime_probe_summary(
    runtime_probe_state: str,
    runtime_probe_intent: UvRuntimeProbeIntent | None,
    runtime_probe_result: UvRuntimeProbeResult | None,
) -> dict[str, Any]:
    if runtime_probe_result is None:
        return {
            "runtime_probe_state": runtime_probe_state,
            "runtime_probe_request_ref": None,
            "runtime_probe_result": None,
            "does_not_claim": "runtime_readiness_or_experiment_execution",
        }
    return {
        "runtime_probe_state": runtime_probe_state,
        "runtime_probe_request_ref": (
            None if runtime_probe_intent is None else runtime_probe_intent.to_probe_request_ref()
        ),
        "runtime_probe_result": copy.deepcopy(runtime_probe_result.to_summary()),
        "does_not_claim": "runtime_readiness_or_experiment_execution",
    }
