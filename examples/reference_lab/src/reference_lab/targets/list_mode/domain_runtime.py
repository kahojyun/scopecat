"""Host-visible invocation adapter for the list-mode target.

Submission assigns and stores one job before calling the synchronous device
primitive, making a repeated idempotency key incapable of replaying physical
work. Fetch is read-only. A device exception that yields
no captured run remains unknown evidence rather than being reported as pending
or definitive absence. Core, not this adapter, owns submission states,
journaling, retry authority, and receipt correlation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from threading import Lock
from typing import cast, override

import numpy as np
from numpy.typing import NDArray
from scopecat.kernel.json_types import JsonValue
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.records.artifact import command_payload_from_bytes
from scopecat.sdk.domain import (
    DomainFetchReceipt,
    DomainFetchResult,
    DomainInstrumentExecutor,
    DomainInvocationSpec,
    DomainResultValue,
    DomainSubmitReceipt,
)
from scopecat.sdk.instruments.commands import InstrumentOperationArgument
from scopecat.sdk.instruments.execution import RunHardwareBatch, RunHardwareInvoke
from scopecat.sdk.problems import (
    Problem,
    ProblemPhase,
    model_location,
    problem,
)
from scopecat_quantum._ids import AcquisitionSlotId, TargetCompileEntryId
from scopecat_quantum.program_results import MappedQuantumTarget
from scopecat_quantum.targets import (
    TargetAcquisitionAddress,
)

from reference_lab.bench_interfaces import (
    VIRTUAL_CAPTURE_LOAD,
    VIRTUAL_CAPTURE_QUEUE,
)
from reference_lab.payloads import (
    VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID,
    reference_lab_payload_codecs,
)
from reference_lab.targets.list_mode.circuit_runtime import (
    correlate_list_mode_run,
    realize_measurements,
)
from reference_lab.targets.list_mode.device_execution import (
    WORKER_ADC_DSP_FINGERPRINT,
    InstrumentListModeRuntime,
)
from reference_lab.targets.list_mode.model import (
    DigitizerAcquisitionWindow,
    DigitizerInputId,
    ListModeArtifact,
    acquisition_slot_identity_payload,
)
from reference_lab.targets.list_mode.runtime import (
    AcquisitionResponse,
    AwgPlayback,
    DigitizerValue,
    ListModeRun,
    run_fingerprint,
    waveform_fingerprint,
)

type MappedListModeTarget = MappedQuantumTarget[ListModeArtifact]
type ListModeMeasurementInvocationSpec = DomainInvocationSpec[MappedListModeTarget]


@dataclass(frozen=True, slots=True)
class _ListModeDomainJob:
    job_id: str
    target_run: ListModeRun | None = None
    result_problem: Problem | None = None


def list_mode_measurement_invocation_spec(
    mapped_target: MappedListModeTarget,
    *,
    invocation_id: str,
    response_intent: object | None = None,
) -> ListModeMeasurementInvocationSpec:
    """Declare target identity, realization, and response-affecting intent.

    A custom device response must supply stable ``response_intent`` whose
    content covers that response's fingerprint and configuration.
    """

    artifact = mapped_target.artifact
    selected_response_intent = (
        {
            "schema": "reference_lab.worker_adc_dsp_intent.v1",
            "response_fingerprint": WORKER_ADC_DSP_FINGERPRINT,
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
        execution_summary=_execution_summary(artifact),
        target_intent={
            "schema": "reference_lab.list_mode_measurement_invocation.v6",
            "configuration_fingerprint": artifact.configuration_fingerprint,
            "results": [
                _result_address_intent(result.result_address)
                for result in mapped_target.mapping.results
            ],
            "response": selected_response_intent,
        },
        payload=mapped_target,
    )


def _execution_summary(artifact: ListModeArtifact) -> dict[str, JsonValue]:
    """Project useful physical provenance without retaining device-state logs."""

    return cast(
        "dict[str, JsonValue]",
        {
            "schema": "reference_lab.list_mode_execution_summary.v1",
            "waveform_outputs": {
                program.instrument_id: sorted(
                    {
                        waveform.channel_id.value
                        for entry in program.entries
                        for waveform in entry.waveforms
                    }
                )
                for program in artifact.awg_programs
            },
            "digitizer_inputs": {
                program.instrument_id: {
                    "input_ids": sorted(
                        {
                            input_id.value
                            for entry in program.entries
                            for input_id in entry.input_ids
                        }
                    ),
                    "result_representation": program.result_representation,
                }
                for program in artifact.digitizer_programs
            },
            "local_oscillators": {
                oscillator.group_id: oscillator.instrument_id
                for oscillator in artifact.preparation.local_oscillators
            },
            "acquisition_semantics": sorted(
                {
                    window.intent.semantics_id
                    for entry in artifact.entries
                    for window in entry.acquisitions
                }
            ),
            "timing": {
                "domain_id": artifact.preparation.timing.domain_id,
                "trigger_instrument_id": (
                    artifact.preparation.timing.trigger_instrument_id
                ),
                "trigger_guarantee": artifact.preparation.timing.trigger_guarantee,
            },
            "preparation": {
                "scope": "invocation",
                "order": "reassert_before_program_load",
            },
        },
    )


def _result_address_intent(address: TargetAcquisitionAddress) -> object:
    return {
        "entry_id": address.entry_id.value,
        "slot_id": acquisition_slot_identity_payload(address.slot_id),
    }


class ListModeDomainRuntime:
    """Idempotent job facade over synchronous worker device programs.

    AWG playback and digitizer capture occur exactly once at first
    submit for a submission key. Fetch only reads the retained in-memory job.
    """

    def __init__(self) -> None:
        self._device = InstrumentListModeRuntime()
        self._jobs: dict[str, _ListModeDomainJob] = {}
        self._lock = Lock()

    def submit(
        self,
        submission_key: str,
        mapped_target: MappedListModeTarget,
        *,
        instruments: DomainInstrumentExecutor,
    ) -> DomainSubmitReceipt:
        with self._lock:
            existing = self._jobs.get(submission_key)
            if existing is not None:
                if existing.result_problem is not None:
                    return DomainSubmitReceipt(
                        submission_key=submission_key,
                        status="unknown",
                        job_id=existing.job_id,
                        problems=(existing.result_problem,),
                    )
                return DomainSubmitReceipt(
                    submission_key=submission_key,
                    status="submitted",
                    job_id=existing.job_id,
                )

            job = _ListModeDomainJob(
                job_id=f"list-mode-job:{submission_key}",
            )
            self._jobs[submission_key] = job
            try:
                target_run = self._execute_target(
                    mapped_target.artifact,
                    execution_id=submission_key,
                    instruments=instruments,
                )
            except Exception:
                self._jobs[submission_key] = _ListModeDomainJob(
                    job_id=job.job_id,
                    result_problem=_domain_runtime_problem(
                        "list_mode_domain_result_unavailable",
                        (
                            "the virtual device call failed after reserving the "
                            "submission key; result availability is unknown"
                        ),
                    ),
                )
                raise
            job = _ListModeDomainJob(
                job_id=job.job_id,
                target_run=target_run,
            )
            self._jobs[submission_key] = job
            return DomainSubmitReceipt(
                submission_key=submission_key,
                status="submitted",
                job_id=job.job_id,
            )

    def _execute_target(
        self,
        artifact: ListModeArtifact,
        *,
        execution_id: str,
        instruments: DomainInstrumentExecutor,
    ) -> ListModeRun:
        return self._device.execute(
            artifact,
            execution_id=execution_id,
            instruments=instruments,
        )

    def fetch(
        self,
        submission_key: str,
        job_id: str,
    ) -> DomainFetchReceipt | DomainFetchResult[ListModeRun]:
        with self._lock:
            job = self._jobs.get(submission_key)
            if job is None or job.job_id != job_id:
                return DomainFetchReceipt(
                    submission_key=submission_key,
                    job_id=job_id,
                    status="not_found",
                    problems=(
                        _domain_runtime_problem(
                            "list_mode_domain_job_not_found",
                            "list-mode job does not exist for this submission",
                        ),
                    ),
                )
            if job.result_problem is not None:
                return DomainFetchReceipt(
                    submission_key=submission_key,
                    job_id=job.job_id,
                    status="unknown",
                    problems=(job.result_problem,),
                )
            assert job.target_run is not None
            return DomainFetchResult(
                receipt=DomainFetchReceipt(
                    submission_key=submission_key,
                    job_id=job.job_id,
                    status="fetched",
                    result_fingerprint=job.target_run.fingerprint,
                    result_count=len(job.target_run.frames),
                ),
                result=job.target_run,
            )


class VirtualListModeDomainRuntime(ListModeDomainRuntime):
    """Program the worker-owned virtual plant before normal target execution."""

    def __init__(self, response: AcquisitionResponse) -> None:
        super().__init__()
        self._response = response

    @override
    def _execute_target(
        self,
        artifact: ListModeArtifact,
        *,
        execution_id: str,
        instruments: DomainInstrumentExecutor,
    ) -> ListModeRun:
        plant = _virtual_plant_preparation(artifact, self._response)
        receipt = instruments.execute(plant.batch)
        if receipt.indeterminate or receipt.problems:
            raise RuntimeError("virtual capture plant could not be prepared")
        target_run = super()._execute_target(
            artifact,
            execution_id=execution_id,
            instruments=instruments,
        )
        frames = tuple(
            replace(
                frame,
                value=(
                    frame.value
                    if plant.available[
                        (frame.shot_index, frame.entry_id, frame.slot_id)
                    ]
                    else None
                ),
            )
            for frame in target_run.frames
        )
        return ListModeRun(
            frames=frames,
            artifact=artifact,
            fingerprint=run_fingerprint(
                artifact=artifact,
                playbacks=plant.playbacks,
                frames=frames,
                response_fingerprint=self._response.fingerprint,
            ),
        )


@dataclass(frozen=True, slots=True)
class _VirtualPlantPreparation:
    batch: RunHardwareBatch
    playbacks: tuple[AwgPlayback, ...]
    available: dict[tuple[int, TargetCompileEntryId, AcquisitionSlotId], bool]


def _virtual_plant_preparation(
    artifact: ListModeArtifact,
    response: AcquisitionResponse,
) -> _VirtualPlantPreparation:
    captures: list[dict[str, object]] = []
    playbacks: list[AwgPlayback] = []
    available: dict[tuple[int, TargetCompileEntryId, AcquisitionSlotId], bool] = {}
    for shot_index in range(artifact.repetitions):
        for entry in artifact.entries:
            playback = AwgPlayback(
                shot_index=shot_index,
                entry_id=entry.entry_id,
                waveform_fingerprint=waveform_fingerprint(entry),
            )
            playbacks.append(playback)
            windows_by_input: dict[
                DigitizerInputId, list[DigitizerAcquisitionWindow]
            ] = {}
            for window in entry.acquisitions:
                windows_by_input.setdefault(window.input_id, []).append(window)
            traces: list[dict[str, object]] = []
            for input_id, windows in windows_by_input.items():
                desired = tuple(
                    response.value_for(playback=playback, window=window)
                    for window in windows
                )
                for window, value in zip(windows, desired, strict=True):
                    available[(shot_index, entry.entry_id, window.slot_id)] = (
                        value is not None
                    )
                traces.append(
                    {
                        "instrument_id": input_id.instrument_id,
                        "component_path": list(input_id.component_path),
                        "samples": list(
                            _synthesize_trace(
                                sample_count=entry.sample_count,
                                sample_rate_hz=artifact.sample_rate_hz,
                                windows=tuple(windows),
                                desired=desired,
                            )
                        ),
                    }
                )
            captures.append({"traces": traces})

    codecs = reference_lab_payload_codecs()
    encoded = codecs.encode(
        VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID,
        {"captures": captures},
    )
    payload_id = f"virtual-captures-{artifact.id.value}"
    payload = command_payload_from_bytes(
        id=payload_id,
        schema_id=encoded.schema_id,
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    )
    timing_id = artifact.preparation.timing.trigger_instrument_id
    return _VirtualPlantPreparation(
        batch=RunHardwareBatch(
            operation_id=f"target.virtual-plant:{artifact.id.value}",
            actions=(
                RunHardwareInvoke(
                    effect_id=f"virtual-plant:{timing_id}",
                    instrument_id=timing_id,
                    resource_id=timing_id,
                    interface_id=VIRTUAL_CAPTURE_LOAD.interface_id,
                    operation_id=VIRTUAL_CAPTURE_LOAD.operation_id,
                    arguments=(
                        InstrumentOperationArgument(
                            id=VIRTUAL_CAPTURE_QUEUE.argument_id,
                            value=StateValue(PayloadRef(payload_id=payload.id)),
                        ),
                    ),
                    payloads={payload.id: payload},
                ),
            ),
        ),
        playbacks=tuple(playbacks),
        available=available,
    )


def _synthesize_trace(
    *,
    sample_count: int,
    sample_rate_hz: int,
    windows: tuple[DigitizerAcquisitionWindow, ...],
    desired: tuple[DigitizerValue, ...],
) -> tuple[float, ...]:
    rows: list[NDArray[np.float64]] = []
    targets: list[float] = []
    for window, value in zip(windows, desired, strict=True):
        if value is None:
            continue
        coefficients = np.zeros(sample_count, dtype=np.float64)
        quadrature = np.zeros(sample_count, dtype=np.float64)
        frequency_hz = window.intent.demodulation_frequency_hz
        normalization = 1.0 if frequency_hz == 0.0 else 2.0
        for index in range(window.sample_count):
            absolute_index = window.start_sample + index
            phase = np.pi * 2.0 * frequency_hz * (absolute_index + 0.5) / sample_rate_hz
            coefficients[absolute_index] = (
                normalization * np.cos(phase) / window.sample_count
            )
            quadrature[absolute_index] = (
                -normalization * np.sin(phase) / window.sample_count
            )
        rows.extend((coefficients, quadrature))
        targets.extend((value.real, value.imag))
    if not rows:
        return (0.0,) * sample_count
    matrix = np.stack(rows)
    solution, _residuals, _rank, _singular_values = np.linalg.lstsq(
        matrix,
        np.asarray(targets),
        rcond=None,
    )
    return tuple(float(sample) for sample in solution)


def realize_fetched_measurements(
    mapped_target: MappedListModeTarget,
    fetched: DomainFetchResult[ListModeRun],
) -> tuple[DomainResultValue[TargetAcquisitionAddress], ...]:
    """Correlate and decode one fetched raw run under selected policies."""

    if fetched.receipt.result_fingerprint != fetched.result.fingerprint:
        msg = "fetched list-mode target receipt does not cover its raw run"
        raise ValueError(msg)
    if fetched.receipt.result_count != len(fetched.result.frames):
        msg = "fetched list-mode target receipt has the wrong raw frame count"
        raise ValueError(msg)
    correlated = correlate_list_mode_run(
        mapped_target,
        fetched.result,
    )
    return realize_measurements(correlated)


def _domain_runtime_problem(
    code: str,
    message: str,
) -> Problem:
    return problem(
        code,
        message,
        phase=ProblemPhase.EXECUTION,
        location=model_location("list_mode_domain_runtime"),
    )


__all__ = [
    "ListModeDomainRuntime",
    "ListModeMeasurementInvocationSpec",
    "MappedListModeTarget",
    "VirtualListModeDomainRuntime",
    "list_mode_measurement_invocation_spec",
    "realize_fetched_measurements",
]
