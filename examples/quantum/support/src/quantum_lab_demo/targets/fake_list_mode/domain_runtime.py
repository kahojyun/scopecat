"""Host-visible invocation adapter for the fake list-mode target."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import cast

from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.sdk.domain.invocation import (
    ClosedDomainInvocation,
    DomainInvocationIntent,
    close_domain_invocation,
)
from scopecat.sdk.domain.runtime import (
    CorrelatedDomainFetch,
    DomainFetchCandidate,
    DomainFetchReceipt,
    DomainReconcileReceipt,
    DomainSubmissionId,
    DomainSubmitReceipt,
    domain_receipt_identity,
)
from scopecat_quantum import TargetAcquisitionAddress, TargetCompileEntryId

from quantum_lab_demo.targets.fake_list_mode.circuit_runtime import (
    RealizedFakeMeasurementRun,
    SelectedFakeMeasurementRealization,
    correlate_fake_list_run,
    realize_fake_measurements,
)
from quantum_lab_demo.targets.fake_list_mode.model import (
    acquisition_slot_identity_payload,
)
from quantum_lab_demo.targets.fake_list_mode.runtime import (
    FakeListRun,
    FakeListRuntime,
)

type ExecutableFakeMeasurementInvocation = ClosedDomainInvocation[
    TargetCompileEntryId,
    TargetAcquisitionAddress,
    SelectedFakeMeasurementRealization,
]


@dataclass(frozen=True, slots=True)
class _FakeListDomainJob:
    intent_fingerprint: str
    job_id: str
    target_run: FakeListRun | None = None
    result_problem: Problem | None = None


def close_fake_measurement_invocation(
    selection: SelectedFakeMeasurementRealization,
    *,
    invocation_id: str,
) -> ExecutableFakeMeasurementInvocation:
    """Close the selected artifact, result contract, and value policies."""

    if not isinstance(cast("object", selection), SelectedFakeMeasurementRealization):
        msg = "fake invocation closure requires a selected measurement realization"
        raise TypeError(msg)
    compiled = selection.compiled_target.compiled
    return close_domain_invocation(
        selection.core_outputs.mapping,
        invocation_id=invocation_id,
        target_id=compiled.target_id.value,
        compiler_id=compiled.compiler_id.value,
        capability_fingerprint=compiled.capability_fingerprint,
        artifact_id=compiled.artifact_id.value,
        artifact_fingerprint=compiled.artifact_fingerprint,
        adapter_intent={
            "schema": "quantum_lab_demo.fake_measurement_invocation.v1",
            "realizations": [
                {
                    "entry_id": output.result_address.entry_id.value,
                    "slot_id": acquisition_slot_identity_payload(
                        output.result_address.slot_id
                    ),
                    "kind": output.kind.value,
                }
                for output in selection.outputs
            ],
        },
        payload=selection,
    )


class FakeListDomainRuntime:
    """Idempotent job facade over the synchronous fake device primitive.

    Physical AWG playback and digitizer capture occur exactly once at first
    submit for a submission key.  Fetch and reconcile only read the retained
    in-memory job.
    """

    def __init__(self, device: FakeListRuntime | None = None) -> None:
        selected = FakeListRuntime() if device is None else device
        if not isinstance(cast("object", selected), FakeListRuntime):
            msg = "fake domain runtime requires a FakeListRuntime"
            raise TypeError(msg)
        self._device = selected
        self._jobs: dict[str, _FakeListDomainJob] = {}
        self._submit_calls = 0
        self._fetch_calls = 0
        self._reconcile_calls = 0
        self._physical_execution_count = 0
        self._lock = Lock()

    @property
    def submit_calls(self) -> int:
        with self._lock:
            return self._submit_calls

    @property
    def fetch_calls(self) -> int:
        with self._lock:
            return self._fetch_calls

    @property
    def reconcile_calls(self) -> int:
        with self._lock:
            return self._reconcile_calls

    @property
    def physical_execution_count(self) -> int:
        with self._lock:
            return self._physical_execution_count

    def submit(
        self,
        submission_id: DomainSubmissionId,
        invocation: ExecutableFakeMeasurementInvocation,
    ) -> DomainSubmitReceipt:
        attempt = submission_id
        identity = domain_receipt_identity(submission_id, invocation.intent)
        with self._lock:
            self._submit_calls += 1
            existing = self._jobs.get(attempt.submission_key)
            if existing is not None:
                if existing.intent_fingerprint != invocation.intent.intent_fingerprint:
                    return DomainSubmitReceipt(
                        identity=identity,
                        status="not_submitted",
                        problems=(
                            _fake_runtime_problem(
                                "fake_submission_key_conflict",
                                "submission key is already bound to another intent",
                                category=ProblemCategory.CONFLICT,
                            ),
                        ),
                    )
                if existing.result_problem is not None:
                    return DomainSubmitReceipt(
                        identity=identity,
                        status="unknown",
                        job_id=existing.job_id,
                        problems=(existing.result_problem,),
                    )
                return DomainSubmitReceipt(
                    identity=identity,
                    status="submitted",
                    job_id=existing.job_id,
                )

            job = _FakeListDomainJob(
                intent_fingerprint=invocation.intent.intent_fingerprint,
                job_id=f"fake-list-job:{attempt.submission_key}",
            )
            self._jobs[attempt.submission_key] = job
            self._physical_execution_count += 1
            try:
                target_run = self._device.execute(
                    invocation.payload.compiled_target.compiled
                )
            except Exception:
                self._jobs[attempt.submission_key] = _FakeListDomainJob(
                    intent_fingerprint=job.intent_fingerprint,
                    job_id=job.job_id,
                    result_problem=_fake_runtime_problem(
                        "fake_domain_result_unavailable",
                        (
                            "the fake device call failed after reserving the "
                            "submission key; result availability is unknown"
                        ),
                        category=ProblemCategory.OPERATION,
                    ),
                )
                raise
            job = _FakeListDomainJob(
                intent_fingerprint=job.intent_fingerprint,
                job_id=job.job_id,
                target_run=target_run,
            )
            self._jobs[attempt.submission_key] = job
            return DomainSubmitReceipt(
                identity=identity,
                status="submitted",
                job_id=job.job_id,
            )

    def fetch(
        self,
        submission_id: DomainSubmissionId,
        intent: DomainInvocationIntent,
        job_id: str,
    ) -> DomainFetchCandidate[FakeListRun]:
        attempt = submission_id
        identity = domain_receipt_identity(submission_id, intent)
        with self._lock:
            self._fetch_calls += 1
            job = self._jobs.get(attempt.submission_key)
            if job is None or job.job_id != job_id:
                return DomainFetchCandidate(
                    receipt=DomainFetchReceipt(
                        identity=identity,
                        job_id=job_id,
                        status="not_found",
                        problems=(
                            _fake_runtime_problem(
                                "fake_domain_job_not_found",
                                "fake list-mode job does not exist for this submission",
                                category=ProblemCategory.NOT_FOUND,
                            ),
                        ),
                    )
                )
            if job.intent_fingerprint != intent.intent_fingerprint:
                return DomainFetchCandidate(
                    receipt=DomainFetchReceipt(
                        identity=identity,
                        job_id=job_id,
                        status="unknown",
                        problems=(
                            _fake_runtime_problem(
                                "fake_domain_job_intent_mismatch",
                                "fake list-mode job belongs to another invocation",
                                category=ProblemCategory.PROVIDER_CONTRACT,
                            ),
                        ),
                    )
                )
            if job.result_problem is not None:
                return DomainFetchCandidate(
                    receipt=DomainFetchReceipt(
                        identity=identity,
                        job_id=job.job_id,
                        status="unknown",
                        problems=(job.result_problem,),
                    )
                )
            if job.target_run is None:
                return DomainFetchCandidate(
                    receipt=DomainFetchReceipt(
                        identity=identity,
                        job_id=job.job_id,
                        status="pending",
                    )
                )
            return DomainFetchCandidate(
                receipt=DomainFetchReceipt(
                    identity=identity,
                    job_id=job.job_id,
                    status="fetched",
                    result_fingerprint=job.target_run.fingerprint,
                    result_count=len(job.target_run.frames),
                ),
                result=job.target_run,
            )

    def reconcile(
        self,
        submission_id: DomainSubmissionId,
        intent: DomainInvocationIntent,
    ) -> DomainReconcileReceipt:
        attempt = submission_id
        identity = domain_receipt_identity(submission_id, intent)
        with self._lock:
            self._reconcile_calls += 1
            job = self._jobs.get(attempt.submission_key)
            if job is None:
                return DomainReconcileReceipt(
                    identity=identity,
                    status="absent",
                )
            if job.intent_fingerprint != intent.intent_fingerprint:
                return DomainReconcileReceipt(
                    identity=identity,
                    status="unknown",
                    job_id=job.job_id,
                    problems=(
                        _fake_runtime_problem(
                            "fake_domain_job_intent_mismatch",
                            "fake list-mode job belongs to another invocation",
                            category=ProblemCategory.PROVIDER_CONTRACT,
                        ),
                    ),
                )
            if job.result_problem is not None:
                return DomainReconcileReceipt(
                    identity=identity,
                    status="unknown",
                    job_id=job.job_id,
                    problems=(job.result_problem,),
                )
            return DomainReconcileReceipt(
                identity=identity,
                status="completed" if job.target_run is not None else "submitted",
                job_id=job.job_id,
            )


def realize_fetched_fake_measurements(
    invocation: ExecutableFakeMeasurementInvocation,
    fetched: CorrelatedDomainFetch[FakeListRun],
) -> RealizedFakeMeasurementRun:
    """Correlate and accept one fetched raw run under the closed policies."""

    if not isinstance(cast("object", invocation), ClosedDomainInvocation):
        msg = "fake measurement realization requires a closed domain invocation"
        raise TypeError(msg)
    if not isinstance(cast("object", fetched), CorrelatedDomainFetch):
        msg = "fake measurement realization requires a correlated domain fetch"
        raise TypeError(msg)
    if not isinstance(cast("object", fetched.result), FakeListRun):
        msg = "fake measurement realization requires a FakeListRun payload"
        raise TypeError(msg)
    if fetched.receipt.identity != domain_receipt_identity(
        fetched.submission.submission_id,
        invocation.intent,
    ):
        msg = "fetched fake target result does not belong to this invocation"
        raise ValueError(msg)
    if fetched.receipt.result_fingerprint != fetched.result.fingerprint:
        msg = "fetched fake target receipt does not cover its raw run"
        raise ValueError(msg)
    if fetched.receipt.result_count != len(fetched.result.frames):
        msg = "fetched fake target receipt has the wrong raw frame count"
        raise ValueError(msg)
    correlated = correlate_fake_list_run(
        invocation.payload.compiled_target,
        fetched.result,
    )
    return realize_fake_measurements(invocation.payload, correlated)


def _fake_runtime_problem(
    code: str,
    message: str,
    *,
    category: ProblemCategory,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=category,
        phase=ProblemPhase.EXECUTION,
        location=model_location("fake_list_domain_runtime"),
    )


__all__ = [
    "ExecutableFakeMeasurementInvocation",
    "FakeListDomainRuntime",
    "close_fake_measurement_invocation",
    "realize_fetched_fake_measurements",
]
