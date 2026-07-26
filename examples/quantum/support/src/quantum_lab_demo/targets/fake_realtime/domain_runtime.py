"""Domain execution adapter for the synchronous fake realtime target."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock

from scopecat.records.measurement import ComplexQuantity, MeasurementArray
from scopecat.sdk.domain import (
    CorrelatedDomainFetch,
    DomainFetchCandidate,
    DomainFetchReceipt,
    DomainFetchRequest,
    DomainInvocationSpec,
    DomainMappedResult,
    DomainResultMapping,
    DomainResultValue,
    DomainSubmitReceipt,
    DomainSubmitRequest,
    DomainTargetArtifactIdentity,
)
from scopecat.sdk.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat_quantum.result_collections import result_collection_axes
from scopecat_quantum.targets import (
    CompiledTargetArtifact,
    TargetAcquisitionAddress,
    TargetResultAddress,
    target_result_acquisition_addresses,
)

from quantum_lab_demo.targets.fake_realtime.model import FakeRealtimeArtifact
from quantum_lab_demo.targets.fake_realtime.runtime import (
    FakeRealtimeRun,
    FakeRealtimeRuntime,
)


@dataclass(frozen=True, slots=True)
class FakeRealtimeInvocation:
    compiled: CompiledTargetArtifact[FakeRealtimeArtifact]
    measurements: tuple[tuple[str, tuple[int, ...]], ...]


@dataclass(frozen=True, slots=True)
class _FakeRealtimeJob:
    intent_fingerprint: str
    job_id: str
    run: FakeRealtimeRun


def fake_realtime_invocation_spec(
    compiled: CompiledTargetArtifact[FakeRealtimeArtifact],
    measurements: tuple[tuple[str, tuple[int, ...]], ...],
    *,
    invocation_id: str,
) -> DomainInvocationSpec[FakeRealtimeInvocation]:
    artifact = compiled.artifact
    return DomainInvocationSpec(
        invocation_id=invocation_id,
        target=DomainTargetArtifactIdentity(
            target_id=compiled.target_id.value,
            compiler_id=compiled.compiler_id.value,
            capability_fingerprint=compiled.capability_fingerprint,
            artifact_id=compiled.artifact_id.value,
            artifact_fingerprint=compiled.artifact_fingerprint,
        ),
        target_intent={
            "schema": "quantum_lab_demo.fake_realtime_invocation.v1",
            "program_id": artifact.program.source_program_id.value,
            "measurements": [
                {"result_id": result_id, "bits": list(bits)}
                for result_id, bits in measurements
            ],
        },
        payload=FakeRealtimeInvocation(compiled, measurements),
    )


class FakeRealtimeDomainRuntime:
    """Idempotent in-memory facade over the realtime interpreter."""

    def __init__(self, device: FakeRealtimeRuntime) -> None:
        self._device = device
        self._jobs: dict[str, _FakeRealtimeJob] = {}
        self._lock = Lock()

    def submit(
        self,
        request: DomainSubmitRequest[FakeRealtimeInvocation],
    ) -> DomainSubmitReceipt:
        key = request.submission_id.submission_key
        with self._lock:
            existing = self._jobs.get(key)
            if existing is not None:
                if (
                    existing.intent_fingerprint
                    != request.submission_id.intent_fingerprint
                ):
                    return DomainSubmitReceipt(
                        submission_key=key,
                        status="not_submitted",
                        problems=(
                            _problem(
                                "fake_realtime_submission_key_conflict",
                                "submission key is already bound to another intent",
                            ),
                        ),
                    )
                return DomainSubmitReceipt(
                    submission_key=key,
                    status="submitted",
                    job_id=existing.job_id,
                )

            job_id = f"fake-realtime-job:{key}"
            run = self._device.execute(
                request.payload.compiled,
                dict(request.payload.measurements),
            )
            self._jobs[key] = _FakeRealtimeJob(
                request.submission_id.intent_fingerprint,
                job_id,
                run,
            )
            return DomainSubmitReceipt(
                submission_key=key,
                status="submitted",
                job_id=job_id,
            )

    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[FakeRealtimeRun]:
        key = request.submission_id.submission_key
        with self._lock:
            job = self._jobs.get(key)
            if job is None or job.job_id != request.job_id:
                return DomainFetchCandidate(
                    receipt=DomainFetchReceipt(
                        submission_key=key,
                        job_id=request.job_id,
                        status="not_found",
                        problems=(
                            _problem(
                                "fake_realtime_job_not_found",
                                "fake realtime job does not exist",
                            ),
                        ),
                    )
                )
            if job.intent_fingerprint != request.submission_id.intent_fingerprint:
                return DomainFetchCandidate(
                    receipt=DomainFetchReceipt(
                        submission_key=key,
                        job_id=request.job_id,
                        status="unknown",
                        problems=(
                            _problem(
                                "fake_realtime_job_intent_mismatch",
                                "fake realtime job belongs to another invocation",
                            ),
                        ),
                    )
                )
            return DomainFetchCandidate(
                receipt=DomainFetchReceipt(
                    submission_key=key,
                    job_id=request.job_id,
                    status="fetched",
                    result_fingerprint=job.run.fingerprint,
                    result_count=len(job.run.records),
                ),
                result=job.run,
            )


def realize_fetched_realtime_results(
    mapping: DomainResultMapping[TargetResultAddress],
    fetched: CorrelatedDomainFetch[FakeRealtimeRun],
) -> tuple[DomainResultValue[TargetResultAddress], ...]:
    """Decode target records according to each mapped logical result contract."""

    run = fetched.result
    if fetched.receipt.result_fingerprint != run.fingerprint:
        raise ValueError("fetched realtime receipt does not cover its run")
    if fetched.receipt.result_count != len(run.records):
        raise ValueError("fetched realtime receipt has the wrong result count")
    return tuple(_result_value(result, run) for result in mapping.results)


def _result_value(
    result: DomainMappedResult[TargetResultAddress],
    run: FakeRealtimeRun,
) -> DomainResultValue[TargetResultAddress]:
    addresses = target_result_acquisition_addresses(result.result_address)
    result_ids = {address.slot_id.local_id for address in addresses}
    if len(result_ids) != 1:
        raise ValueError("one realtime result tree must retain one result id")
    [result_id] = result_ids
    records = tuple(record for record in run.records if record.result_id == result_id)
    shots = run.artifact.repetitions
    if len(records) != shots * len(addresses):
        raise ValueError("realtime records do not cover the mapped result shape")
    by_shot_address = {
        (shot_index, address): records[shot_index * len(addresses) + address_index]
        for shot_index in range(shots)
        for address_index, address in enumerate(addresses)
    }
    dtype = result.product.dtype
    unit = result.product.unit
    return DomainResultValue(
        result.result_address,
        MeasurementArray(
            dtype=dtype,
            unit=unit,
            shape=[
                shots,
                *(
                    size
                    for _axis_id, size in result_collection_axes(result.result_address)
                ),
            ],
            values=[
                _collection_values(
                    result.result_address,
                    {
                        address: _decode_bit(
                            by_shot_address[(shot_index, address)].value,
                            dtype=dtype,
                            unit=unit,
                        )
                        for address in addresses
                    },
                )
                for shot_index in range(shots)
            ],
        ),
    )


def _collection_values(
    address: TargetResultAddress,
    values: dict[TargetAcquisitionAddress, object],
) -> object:
    if isinstance(address, TargetAcquisitionAddress):
        return values[address]
    return [_collection_values(item, values) for item in address.items]


def _bit_iq(bit: int, *, unit: str) -> ComplexQuantity:
    return ComplexQuantity(real=-1.0 if bit == 0 else 1.0, imag=0.0, unit=unit)


def _decode_bit(bit: int, *, dtype: str, unit: str | None) -> object:
    if dtype == "complex128":
        if unit is None:
            raise ValueError("complex realtime results require a physical unit")
        return _bit_iq(bit, unit=unit)
    if dtype == "int64":
        return bit
    if dtype == "bool":
        return bool(bit)
    raise ValueError(f"unsupported realtime result dtype {dtype!r}")


def _problem(code: str, message: str) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=model_location("fake_realtime_domain_runtime"),
    )


__all__ = [
    "FakeRealtimeDomainRuntime",
    "FakeRealtimeInvocation",
    "fake_realtime_invocation_spec",
    "realize_fetched_realtime_results",
]
