"""Virtual acquisition plant layered outside the physical list-mode target."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import override

import numpy as np
from numpy.typing import NDArray
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.kernel.value_types import Payload, Scalar
from scopecat.records.artifact import command_payload_from_bytes
from scopecat.sdk.domain import (
    DomainInstrumentExecutor,
)
from scopecat.sdk.instruments import (
    InterfaceRef,
    InterfaceSpec,
    interface,
    operation,
    operation_argument,
)
from scopecat.sdk.instruments.commands import InstrumentOperationArgument
from scopecat.sdk.instruments.execution import RunHardwareBatch, RunHardwareInvoke
from scopecat_quantum._ids import AcquisitionSlotId, TargetCompileEntryId

from reference_lab.payloads import reference_lab_payload_codecs
from reference_lab.targets.list_mode.domain_runtime import ListModeDomainRuntime
from reference_lab.targets.list_mode.execution_model import (
    AcquisitionResponse,
    AwgPlayback,
    DigitizerValue,
    ListModeRun,
    run_fingerprint,
    waveform_fingerprint,
)
from reference_lab.targets.list_mode.model import (
    DigitizerAcquisitionWindow,
    DigitizerInputId,
    ListModeArtifact,
)
from reference_lab.virtual_lab.capture_payload import (
    VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID,
)

VIRTUAL_CAPTURE_SOURCE = InterfaceRef("reference_lab.virtual_capture_source/v1")
VIRTUAL_CAPTURE_LOAD = VIRTUAL_CAPTURE_SOURCE.operation("load")
VIRTUAL_CAPTURE_QUEUE = VIRTUAL_CAPTURE_LOAD.argument("captures")


def virtual_capture_source_interface() -> InterfaceSpec:
    """Describe the test-only worker input for synthetic ADC traces."""

    return interface(
        VIRTUAL_CAPTURE_SOURCE.interface_id,
        label="Virtual capture source",
        description="Test-only plant input for queued raw ADC captures.",
        operations=(
            operation(
                VIRTUAL_CAPTURE_LOAD.operation_id,
                label="Load raw capture queue",
                arguments=(
                    operation_argument(
                        VIRTUAL_CAPTURE_QUEUE.argument_id,
                        value_type=Scalar(Payload(VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID)),
                    ),
                ),
            ),
        ),
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
        plant = _virtual_plant_preparation(
            artifact,
            self._response,
            execution_id=execution_id,
        )
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
    *,
    execution_id: str,
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

    encoded = reference_lab_payload_codecs().encode(
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
    prefix = f"target:{execution_id}:{artifact.id.value}"
    return _VirtualPlantPreparation(
        batch=RunHardwareBatch(
            operation_id=f"{prefix}:virtual-plant",
            actions=(
                RunHardwareInvoke(
                    effect_id=f"{prefix}:virtual-plant:{timing_id}",
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


__all__ = [
    "VIRTUAL_CAPTURE_LOAD",
    "VIRTUAL_CAPTURE_QUEUE",
    "VIRTUAL_CAPTURE_SOURCE",
    "VirtualListModeDomainRuntime",
    "virtual_capture_source_interface",
]
