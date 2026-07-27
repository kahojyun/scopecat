"""Host-visible invocation adapter for the fake list-mode target.

Submission assigns and stores one job before calling the synchronous device
primitive, making a repeated idempotency key incapable of replaying physical
work. Fetch is read-only. A device exception that yields
no captured run remains unknown evidence rather than being reported as pending
or definitive absence. Core, not this adapter, owns submission states,
journaling, retry authority, and receipt correlation.
"""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from scopecat.sdk.domain import (
    CorrelatedDomainFetch,
    DomainFetchCandidate,
    DomainFetchReceipt,
    DomainFetchRequest,
    DomainInvocationSpec,
    DomainResultValue,
    DomainSubmitReceipt,
    DomainSubmitRequest,
)
from scopecat.sdk.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat_quantum.program_results import MappedQuantumTarget
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
)

from quantum_lab_demo.targets.fake_list_mode.circuit_runtime import (
    correlate_fake_list_run,
    realize_fake_measurements,
)
from quantum_lab_demo.targets.fake_list_mode.model import (
    FakeListArtifact,
    acquisition_slot_identity_payload,
)
from quantum_lab_demo.targets.fake_list_mode.runtime import (
    DeterministicFakeAcquisitionResponse,
    FakeListRun,
    FakeListRuntime,
)

type MappedFakeListTarget = MappedQuantumTarget[FakeListArtifact]
type FakeMeasurementInvocationSpec = DomainInvocationSpec[MappedFakeListTarget]


@dataclass(frozen=True, slots=True)
class _FakeListDomainJob:
    intent_fingerprint: str
    job_id: str
    target_run: FakeListRun | None = None
    result_problem: Problem | None = None


def fake_measurement_invocation_spec(
    mapped_target: MappedFakeListTarget,
    *,
    invocation_id: str,
    response_intent: object | None = None,
) -> FakeMeasurementInvocationSpec:
    """Declare target identity, realization, and response-affecting intent.

    A custom device response must supply stable ``response_intent`` whose
    content covers that response's fingerprint and configuration.
    """

    artifact = mapped_target.artifact
    selected_response_intent = (
        {
            "schema": "quantum_lab_demo.fake_acquisition_response_intent.v1",
            "response_fingerprint": DeterministicFakeAcquisitionResponse().fingerprint,
        }
        if response_intent is None
        else response_intent
    )
    return DomainInvocationSpec(
        invocation_id=invocation_id,
        target_id=artifact.target_id.value,
        compiler_id=artifact.compiler_id.value,
        capability_fingerprint=artifact.capability_fingerprint,
        artifact_id=artifact.id.value,
        artifact_fingerprint=artifact.artifact_fingerprint,
        target_intent={
            "schema": "quantum_lab_demo.fake_measurement_invocation.v4",
            "results": [
                _result_address_intent(result.result_address)
                for result in mapped_target.mapping.results
            ],
            "response": selected_response_intent,
        },
        payload=mapped_target,
    )


def _result_address_intent(address: TargetAcquisitionAddress) -> object:
    return {
        "entry_id": address.entry_id.value,
        "slot_id": acquisition_slot_identity_payload(address.slot_id),
    }


class FakeListDomainRuntime:
    """Idempotent job facade over the synchronous fake device primitive.

    Physical AWG playback and digitizer capture occur exactly once at first
    submit for a submission key. Fetch only reads the retained in-memory job.
    """

    def __init__(self, device: FakeListRuntime | None = None) -> None:
        selected = FakeListRuntime() if device is None else device
        self._device = selected
        self._jobs: dict[str, _FakeListDomainJob] = {}
        self._lock = Lock()

    def submit(
        self,
        request: DomainSubmitRequest[MappedFakeListTarget],
    ) -> DomainSubmitReceipt:
        submission_id = request.submission_id
        mapped_target = request.payload
        with self._lock:
            existing = self._jobs.get(submission_id.submission_key)
            if existing is not None:
                if existing.intent_fingerprint != submission_id.intent_fingerprint:
                    return DomainSubmitReceipt(
                        submission_key=submission_id.submission_key,
                        status="not_submitted",
                        problems=(
                            _fake_runtime_problem(
                                "fake_submission_key_conflict",
                                "submission key is already bound to another intent",
                            ),
                        ),
                    )
                if existing.result_problem is not None:
                    return DomainSubmitReceipt(
                        submission_key=submission_id.submission_key,
                        status="unknown",
                        job_id=existing.job_id,
                        problems=(existing.result_problem,),
                    )
                return DomainSubmitReceipt(
                    submission_key=submission_id.submission_key,
                    status="submitted",
                    job_id=existing.job_id,
                )

            job = _FakeListDomainJob(
                intent_fingerprint=submission_id.intent_fingerprint,
                job_id=f"fake-list-job:{submission_id.submission_key}",
            )
            self._jobs[submission_id.submission_key] = job
            try:
                target_run = self._device.execute(mapped_target.artifact)
            except Exception:
                self._jobs[submission_id.submission_key] = _FakeListDomainJob(
                    intent_fingerprint=job.intent_fingerprint,
                    job_id=job.job_id,
                    result_problem=_fake_runtime_problem(
                        "fake_domain_result_unavailable",
                        (
                            "the fake device call failed after reserving the "
                            "submission key; result availability is unknown"
                        ),
                    ),
                )
                raise
            job = _FakeListDomainJob(
                intent_fingerprint=job.intent_fingerprint,
                job_id=job.job_id,
                target_run=target_run,
            )
            self._jobs[submission_id.submission_key] = job
            return DomainSubmitReceipt(
                submission_key=submission_id.submission_key,
                status="submitted",
                job_id=job.job_id,
            )

    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[FakeListRun]:
        submission_id = request.submission_id
        job_id = request.job_id
        with self._lock:
            job = self._jobs.get(submission_id.submission_key)
            if job is None or job.job_id != job_id:
                return DomainFetchCandidate(
                    receipt=DomainFetchReceipt(
                        submission_key=submission_id.submission_key,
                        job_id=job_id,
                        status="not_found",
                        problems=(
                            _fake_runtime_problem(
                                "fake_domain_job_not_found",
                                "fake list-mode job does not exist for this submission",
                            ),
                        ),
                    )
                )
            if job.intent_fingerprint != submission_id.intent_fingerprint:
                return DomainFetchCandidate(
                    receipt=DomainFetchReceipt(
                        submission_key=submission_id.submission_key,
                        job_id=job_id,
                        status="unknown",
                        problems=(
                            _fake_runtime_problem(
                                "fake_domain_job_intent_mismatch",
                                "fake list-mode job belongs to another invocation",
                            ),
                        ),
                    )
                )
            if job.result_problem is not None:
                return DomainFetchCandidate(
                    receipt=DomainFetchReceipt(
                        submission_key=submission_id.submission_key,
                        job_id=job.job_id,
                        status="unknown",
                        problems=(job.result_problem,),
                    )
                )
            assert job.target_run is not None
            return DomainFetchCandidate(
                receipt=DomainFetchReceipt(
                    submission_key=submission_id.submission_key,
                    job_id=job.job_id,
                    status="fetched",
                    result_fingerprint=job.target_run.fingerprint,
                    result_count=len(job.target_run.frames),
                ),
                result=job.target_run,
            )


def realize_fetched_fake_measurements(
    mapped_target: MappedFakeListTarget,
    fetched: CorrelatedDomainFetch[FakeListRun],
) -> tuple[DomainResultValue[TargetAcquisitionAddress], ...]:
    """Correlate and decode one fetched raw run under selected policies."""

    if fetched.receipt.result_fingerprint != fetched.result.fingerprint:
        msg = "fetched fake target receipt does not cover its raw run"
        raise ValueError(msg)
    if fetched.receipt.result_count != len(fetched.result.frames):
        msg = "fetched fake target receipt has the wrong raw frame count"
        raise ValueError(msg)
    correlated = correlate_fake_list_run(
        mapped_target,
        fetched.result,
    )
    return realize_fake_measurements(correlated)


def _fake_runtime_problem(
    code: str,
    message: str,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=model_location("fake_list_domain_runtime"),
    )


__all__ = [
    "FakeListDomainRuntime",
    "FakeMeasurementInvocationSpec",
    "MappedFakeListTarget",
    "fake_measurement_invocation_spec",
    "realize_fetched_fake_measurements",
]
