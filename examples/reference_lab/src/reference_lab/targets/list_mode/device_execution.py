"""Lower list-mode artifacts to typed commands for reserved bare devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scopecat.kernel.errors import OperationFailure
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.records.artifact import CommandPayload, command_payload_from_bytes
from scopecat.records.measurement import MeasurementArray, MeasurementUnavailable
from scopecat.sdk.domain import (
    DomainInstrumentExecutor,
    DomainStateAddress,
    DomainStateRequirement,
)
from scopecat.sdk.instruments import PropertyRef
from scopecat.sdk.instruments.commands import (
    CollectAxisRequest,
    CollectResultRequest,
    InstrumentOperationArgument,
    InstrumentStateAssignment,
)
from scopecat.sdk.instruments.execution import (
    RunHardwareApply,
    RunHardwareBatch,
    RunHardwareBatchReceipt,
    RunHardwareCollect,
    RunHardwareCollectBinding,
    RunHardwareInvoke,
)

from reference_lab.bench_interfaces import (
    ANALOG_WAVEFORM_OUTPUT_AMPLITUDE,
    ANALOG_WAVEFORM_OUTPUT_ENABLED,
    ANALOG_WAVEFORM_OUTPUT_OFFSET,
    AWG_ARM_ENTRY,
    AWG_ENTRY_INDEX,
    AWG_LOAD_PROGRAM,
    AWG_PROGRAM,
    AWG_RUN_MODE,
    AWG_SAMPLE_RATE,
    DIGITIZER_ARM,
    DIGITIZER_CONFIGURE_DSP,
    DIGITIZER_DSP_PROGRAM,
    DIGITIZER_FETCH,
    DIGITIZER_FETCH_IQ,
    DIGITIZER_FETCH_IQ_VALUE,
    DIGITIZER_FETCH_VOLTAGE,
    DIGITIZER_INPUT_COUPLING,
    DIGITIZER_INPUT_ENABLED,
    DIGITIZER_INPUT_RANGE,
    DIGITIZER_RECORD_LENGTH,
    DIGITIZER_SAMPLE_RATE,
    DIGITIZER_TRIGGER_SOURCE,
    TRIGGER_EPOCH,
    TRIGGER_FIRE,
    TRIGGER_FIRE_EPOCH,
    TRIGGER_IDEMPOTENT_EPOCH,
)
from reference_lab.interfaces import (
    CLOCK_REFERENCE_FREQUENCY,
    CLOCK_REFERENCE_SOURCE,
)
from reference_lab.payloads import (
    AWG_PROGRAM_SCHEMA_ID,
    DIGITIZER_DSP_PROGRAM_SCHEMA_ID,
    TRIGGER_EPOCH_SCHEMA_ID,
    reference_lab_payload_codecs,
)
from reference_lab.targets.list_mode.iq_semantics import (
    integrate_rectangular_iq,
)
from reference_lab.targets.list_mode.model import (
    DigitizerAcquisitionWindow,
    DigitizerInputId,
    ListModeArtifact,
    ListModeEntry,
)
from reference_lab.targets.list_mode.runtime import (
    AwgPlayback,
    DigitizerFrame,
    ListModeRun,
    run_fingerprint,
    waveform_fingerprint,
)


@dataclass(frozen=True, slots=True)
class InstrumentListModeRuntime:
    """Execute target device programs through the admitted instrument worker."""

    def prepare(
        self,
        artifact: ListModeArtifact,
        *,
        execution_id: str,
        instruments: DomainInstrumentExecutor,
    ) -> None:
        """Load device programs before host-managed requirements are reasserted."""

        _execute_batch(
            instruments,
            _load_batch(artifact, execution_id=execution_id),
        )

    def execute(
        self,
        artifact: ListModeArtifact,
        *,
        execution_id: str,
        instruments: DomainInstrumentExecutor,
    ) -> ListModeRun:
        _execute_batch(
            instruments,
            _preparation_batch(artifact, execution_id=execution_id),
        )
        playbacks: list[AwgPlayback] = []
        frames: list[DigitizerFrame] = []
        for shot_index in range(artifact.repetitions):
            for entry in artifact.entries:
                _execute_batch(
                    instruments,
                    _arm_batch(
                        artifact,
                        entry,
                        execution_id=execution_id,
                        shot_index=shot_index,
                    ),
                )
                _execute_batch(
                    instruments,
                    _trigger_batch(
                        artifact,
                        entry,
                        execution_id=execution_id,
                        shot_index=shot_index,
                    ),
                )
                receipt = _execute_batch(
                    instruments,
                    _fetch_batch(
                        artifact,
                        entry,
                        execution_id=execution_id,
                        shot_index=shot_index,
                    ),
                )
                playback = AwgPlayback(
                    shot_index=shot_index,
                    entry_id=entry.entry_id,
                    waveform_fingerprint=waveform_fingerprint(entry),
                )
                playbacks.append(playback)
                frames.extend(
                    _digitizer_frames(
                        artifact,
                        entry,
                        playback=playback,
                        receipt=receipt,
                    )
                )
        selected_playbacks = tuple(playbacks)
        selected_frames = tuple(frames)
        return ListModeRun(
            frames=selected_frames,
            artifact=artifact,
            fingerprint=run_fingerprint(
                artifact=artifact,
                playbacks=selected_playbacks,
                frames=selected_frames,
                response_fingerprint=WORKER_ADC_DSP_FINGERPRINT,
            ),
        )


WORKER_ADC_DSP_FINGERPRINT = "reference_lab.rectangular_adc_dsp.v2"


def list_mode_realtime_write_footprint(
    artifact: ListModeArtifact,
) -> tuple[DomainStateAddress, ...]:
    """Project the target's physical write footprint from typed preparation."""

    batch = _preparation_batch(artifact, execution_id="state-footprint")
    return tuple(
        sorted(
            {
                DomainStateAddress(
                    instrument_id=action.instrument_id,
                    interface_id=assignment.interface_id,
                    component_path=tuple(assignment.component_path),
                    property_id=assignment.property_id,
                )
                for action in batch.actions
                if isinstance(action, RunHardwareApply)
                for assignment in action.assignments
            }
        )
    )


def list_mode_state_requirements(
    artifact: ListModeArtifact,
) -> tuple[DomainStateRequirement, ...]:
    """Project host-provided full-AWG offsets required by this artifact."""

    return tuple(
        DomainStateRequirement(
            address=DomainStateAddress(
                instrument_id=requirement.channel_id.instrument_id,
                interface_id=ANALOG_WAVEFORM_OUTPUT_OFFSET.interface_id,
                component_path=requirement.channel_id.component_path,
                property_id=ANALOG_WAVEFORM_OUTPUT_OFFSET.property_id,
            ),
            value=StateValue(Quantity(requirement.offset_v, "V")),
        )
        for requirement in artifact.host_state_requirements.output_offsets
    )


def list_mode_setup_state_invalidations(
    artifact: ListModeArtifact,
) -> tuple[DomainStateAddress, ...]:
    """Declare host-managed offsets disturbed while AWG programs are loaded."""

    return tuple(
        requirement.address for requirement in list_mode_state_requirements(artifact)
    )


def _preparation_batch(
    artifact: ListModeArtifact,
    *,
    execution_id: str,
) -> RunHardwareBatch:
    prefix = _execution_prefix(artifact, execution_id=execution_id)
    actions: list[RunHardwareApply] = []
    clocks = {
        preparation.instrument_id: preparation
        for preparation in artifact.preparation.clocks
    }
    outputs = {
        preparation.channel_id: preparation
        for preparation in artifact.preparation.outputs
    }
    for awg_program in artifact.awg_programs:
        clock = clocks[awg_program.instrument_id]
        channels = sorted(
            {
                waveform.channel_id
                for entry in awg_program.entries
                for waveform in entry.waveforms
            }
        )
        assignments = [
            _assignment(
                awg_program.instrument_id,
                AWG_SAMPLE_RATE,
                Quantity(artifact.sample_rate_hz, "Hz"),
            ),
            _assignment(awg_program.instrument_id, AWG_RUN_MODE, "once"),
            _assignment(
                awg_program.instrument_id,
                CLOCK_REFERENCE_SOURCE,
                clock.source,
            ),
            _assignment(
                awg_program.instrument_id,
                CLOCK_REFERENCE_FREQUENCY,
                Quantity(clock.frequency_hz, "Hz"),
            ),
        ]
        for channel in channels:
            output = outputs[channel]
            assignments.extend(
                (
                    _assignment(
                        awg_program.instrument_id,
                        ANALOG_WAVEFORM_OUTPUT_AMPLITUDE,
                        Quantity(output.amplitude_v, "V"),
                        component_path=channel.component_path,
                    ),
                    _assignment(
                        awg_program.instrument_id,
                        ANALOG_WAVEFORM_OUTPUT_ENABLED,
                        output.output_enabled,
                        component_path=channel.component_path,
                    ),
                )
            )
        actions.append(
            RunHardwareApply(
                effect_id=f"{prefix}:prepare:{awg_program.instrument_id}",
                instrument_id=awg_program.instrument_id,
                assignments=tuple(assignments),
            )
        )

    for digitizer_program in artifact.digitizer_programs:
        inputs = sorted(
            {
                input_id
                for entry in digitizer_program.entries
                for input_id in entry.input_ids
            }
        )
        assignments = [
            _assignment(
                digitizer_program.instrument_id,
                DIGITIZER_SAMPLE_RATE,
                Quantity(digitizer_program.sample_rate_hz, "Hz"),
            ),
            _assignment(
                digitizer_program.instrument_id,
                DIGITIZER_RECORD_LENGTH,
                max(entry.sample_count for entry in digitizer_program.entries),
            ),
            _assignment(
                digitizer_program.instrument_id,
                DIGITIZER_TRIGGER_SOURCE,
                digitizer_program.trigger_source,
            ),
        ]
        for input_id in inputs:
            assignments.extend(
                (
                    _assignment(
                        digitizer_program.instrument_id,
                        DIGITIZER_INPUT_ENABLED,
                        True,
                        component_path=input_id.component_path,
                    ),
                    _assignment(
                        digitizer_program.instrument_id,
                        DIGITIZER_INPUT_RANGE,
                        Quantity(0.5, "V"),
                        component_path=input_id.component_path,
                    ),
                    _assignment(
                        digitizer_program.instrument_id,
                        DIGITIZER_INPUT_COUPLING,
                        "dc",
                        component_path=input_id.component_path,
                    ),
                )
            )
        actions.append(
            RunHardwareApply(
                effect_id=f"{prefix}:prepare:{digitizer_program.instrument_id}",
                instrument_id=digitizer_program.instrument_id,
                assignments=tuple(assignments),
            )
        )

    return RunHardwareBatch(
        operation_id=f"{prefix}:prepare",
        actions=tuple(actions),
    )


def _load_batch(
    artifact: ListModeArtifact,
    *,
    execution_id: str,
) -> RunHardwareBatch:
    prefix = _execution_prefix(artifact, execution_id=execution_id)
    actions: list[RunHardwareInvoke] = []
    codecs = reference_lab_payload_codecs()
    for awg_program in artifact.awg_programs:
        payload_id = f"awg-program-{awg_program.instrument_id}"
        encoded = codecs.encode(
            AWG_PROGRAM_SCHEMA_ID,
            {
                "entries": [
                    {
                        "waveforms": [
                            {
                                "component_path": list(
                                    waveform.channel_id.component_path
                                ),
                                "samples": list(waveform.samples),
                            }
                            for waveform in entry.waveforms
                        ]
                    }
                    for entry in awg_program.entries
                ]
            },
        )
        payload = command_payload_from_bytes(
            id=payload_id,
            schema_id=encoded.schema_id,
            codec_id=encoded.codec_id,
            codec_version=encoded.codec_version,
            media_type=encoded.media_type,
            content=encoded.content,
        )
        actions.append(
            RunHardwareInvoke(
                effect_id=f"{prefix}:load:{awg_program.instrument_id}",
                instrument_id=awg_program.instrument_id,
                resource_id=awg_program.instrument_id,
                interface_id=AWG_LOAD_PROGRAM.interface_id,
                operation_id=AWG_LOAD_PROGRAM.operation_id,
                arguments=(
                    InstrumentOperationArgument(
                        id=AWG_PROGRAM.argument_id,
                        value=StateValue(PayloadRef(payload_id=payload.id)),
                    ),
                ),
                payloads={payload.id: payload},
            )
        )
    return RunHardwareBatch(
        operation_id=f"{prefix}:load",
        actions=tuple(actions),
    )


def _arm_batch(
    artifact: ListModeArtifact,
    entry: ListModeEntry,
    *,
    execution_id: str,
    shot_index: int,
) -> RunHardwareBatch:
    prefix = _entry_prefix(
        artifact,
        entry,
        execution_id=execution_id,
        shot_index=shot_index,
    )
    actions: list[RunHardwareApply | RunHardwareInvoke] = []
    for digitizer_program in artifact.digitizer_programs:
        program_entry = next(
            selected
            for selected in digitizer_program.entries
            if selected.entry_id == entry.entry_id
        )
        if not program_entry.input_ids:
            continue
        actions.append(
            RunHardwareApply(
                effect_id=f"{prefix}:record-length:{digitizer_program.instrument_id}",
                instrument_id=digitizer_program.instrument_id,
                assignments=(
                    _assignment(
                        digitizer_program.instrument_id,
                        DIGITIZER_RECORD_LENGTH,
                        program_entry.sample_count,
                    ),
                ),
            )
        )
        if digitizer_program.result_representation == "integrated_iq":
            payload = _digitizer_dsp_payload(
                entry,
                instrument_id=digitizer_program.instrument_id,
            )
            actions.append(
                RunHardwareInvoke(
                    effect_id=(
                        f"{prefix}:configure-dsp:{digitizer_program.instrument_id}"
                    ),
                    instrument_id=digitizer_program.instrument_id,
                    resource_id=digitizer_program.instrument_id,
                    interface_id=DIGITIZER_CONFIGURE_DSP.interface_id,
                    operation_id=DIGITIZER_CONFIGURE_DSP.operation_id,
                    arguments=(
                        InstrumentOperationArgument(
                            id=DIGITIZER_DSP_PROGRAM.argument_id,
                            value=StateValue(PayloadRef(payload_id=payload.id)),
                        ),
                    ),
                    payloads={payload.id: payload},
                )
            )
        actions.append(
            RunHardwareInvoke(
                effect_id=f"{prefix}:arm:{digitizer_program.instrument_id}",
                instrument_id=digitizer_program.instrument_id,
                resource_id=digitizer_program.instrument_id,
                interface_id=DIGITIZER_ARM.interface_id,
                operation_id=DIGITIZER_ARM.operation_id,
            )
        )
    for awg_program in artifact.awg_programs:
        program_entry = next(
            selected
            for selected in awg_program.entries
            if selected.entry_id == entry.entry_id
        )
        if not program_entry.waveforms:
            continue
        actions.append(
            RunHardwareInvoke(
                effect_id=f"{prefix}:arm:{awg_program.instrument_id}",
                instrument_id=awg_program.instrument_id,
                resource_id=awg_program.instrument_id,
                interface_id=AWG_ARM_ENTRY.interface_id,
                operation_id=AWG_ARM_ENTRY.operation_id,
                arguments=(
                    InstrumentOperationArgument(
                        id=AWG_ENTRY_INDEX.argument_id,
                        value=StateValue(entry.list_index),
                    ),
                ),
            )
        )
    return RunHardwareBatch(operation_id=f"{prefix}:arm", actions=tuple(actions))


def _digitizer_dsp_payload(
    entry: ListModeEntry,
    *,
    instrument_id: str,
) -> CommandPayload:
    encoded = reference_lab_payload_codecs().encode(
        DIGITIZER_DSP_PROGRAM_SCHEMA_ID,
        {
            "windows": [
                {
                    "component_path": list(window.input_id.component_path),
                    "demodulator_slot_id": window.demodulator_slot_id.value,
                    "start_sample": window.start_sample,
                    "sample_count": window.sample_count,
                    "demodulation_frequency_hz": (
                        window.intent.demodulation_frequency_hz
                    ),
                    "semantics_id": window.intent.semantics_id,
                    "normalization": window.intent.normalization,
                }
                for window in entry.acquisitions
                if window.input_id.instrument_id == instrument_id
            ]
        },
    )
    return command_payload_from_bytes(
        id="digitizer-dsp-program",
        schema_id=encoded.schema_id,
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    )


def _trigger_batch(
    artifact: ListModeArtifact,
    entry: ListModeEntry,
    *,
    execution_id: str,
    shot_index: int,
) -> RunHardwareBatch:
    prefix = _entry_prefix(
        artifact,
        entry,
        execution_id=execution_id,
        shot_index=shot_index,
    )
    timing = artifact.preparation.timing
    trigger_operation = (
        TRIGGER_FIRE_EPOCH
        if timing.trigger_guarantee == "session_idempotent"
        else TRIGGER_FIRE
    )
    trigger_argument = (
        TRIGGER_IDEMPOTENT_EPOCH
        if timing.trigger_guarantee == "session_idempotent"
        else TRIGGER_EPOCH
    )
    epoch = artifact.trigger_epoch(
        entry,
        execution_id=execution_id,
        shot_index=shot_index,
    )
    encoded = reference_lab_payload_codecs().encode(
        TRIGGER_EPOCH_SCHEMA_ID,
        {
            "epoch_id": epoch.id,
            "awg_instrument_ids": list(epoch.awg_instrument_ids),
            "digitizer_instrument_ids": list(epoch.digitizer_instrument_ids),
        },
    )
    payload = command_payload_from_bytes(
        id="trigger-epoch",
        schema_id=encoded.schema_id,
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    )
    return RunHardwareBatch(
        operation_id=f"{prefix}:trigger",
        actions=(
            RunHardwareInvoke(
                effect_id=f"{prefix}:trigger:{timing.trigger_instrument_id}",
                instrument_id=timing.trigger_instrument_id,
                resource_id=timing.trigger_instrument_id,
                interface_id=trigger_operation.interface_id,
                operation_id=trigger_operation.operation_id,
                arguments=(
                    InstrumentOperationArgument(
                        id=trigger_argument.argument_id,
                        value=StateValue(PayloadRef(payload_id=payload.id)),
                    ),
                ),
                payloads={payload.id: payload},
            ),
        ),
    )


def _fetch_batch(
    artifact: ListModeArtifact,
    entry: ListModeEntry,
    *,
    execution_id: str,
    shot_index: int,
) -> RunHardwareBatch:
    prefix = _entry_prefix(
        artifact,
        entry,
        execution_id=execution_id,
        shot_index=shot_index,
    )
    actions: list[RunHardwareCollect] = []
    digitizer_inputs = {window.input_id for window in entry.acquisitions}

    for input_id in sorted(digitizer_inputs):
        windows = tuple(
            window for window in entry.acquisitions if window.input_id == input_id
        )
        representation = windows[0].lowering.device_result_representation
        request_id = (
            _raw_value_id(input_id)
            if representation == "raw_trace"
            else _iq_value_id(input_id)
        )
        actions.append(
            RunHardwareCollect(
                effect_id=f"{prefix}:collect:{input_id.value}",
                instrument_id=input_id.instrument_id,
                point_count=1,
                requests=(
                    CollectResultRequest(
                        id=request_id,
                        interface_id=DIGITIZER_FETCH.interface_id,
                        component_path=list(input_id.component_path),
                        acquisition_id=(
                            DIGITIZER_FETCH.acquisition_id
                            if representation == "raw_trace"
                            else DIGITIZER_FETCH_IQ.acquisition_id
                        ),
                        result_id=(
                            DIGITIZER_FETCH_VOLTAGE.result_id
                            if representation == "raw_trace"
                            else DIGITIZER_FETCH_IQ_VALUE.result_id
                        ),
                        unit="V",
                        dtype=(
                            "float64" if representation == "raw_trace" else "complex128"
                        ),
                        dimensions=[
                            CollectAxisRequest(
                                id=(
                                    "sample"
                                    if representation == "raw_trace"
                                    else "demodulator"
                                ),
                                kind=(
                                    "time" if representation == "raw_trace" else "index"
                                ),
                                size=(
                                    entry.sample_count
                                    if representation == "raw_trace"
                                    else len(windows)
                                ),
                                unit=("s" if representation == "raw_trace" else None),
                            )
                        ],
                    ),
                ),
                bindings=(
                    RunHardwareCollectBinding(
                        request_id=request_id,
                        value_ids=(request_id,),
                    ),
                ),
            )
        )
    return RunHardwareBatch(operation_id=f"{prefix}:fetch", actions=tuple(actions))


def _execution_prefix(artifact: ListModeArtifact, *, execution_id: str) -> str:
    return f"target:{execution_id}:{artifact.id.value}"


def _entry_prefix(
    artifact: ListModeArtifact,
    entry: ListModeEntry,
    *,
    execution_id: str,
    shot_index: int,
) -> str:
    return (
        f"{_execution_prefix(artifact, execution_id=execution_id)}:"
        f"shot-{shot_index}:entry-{entry.list_index}"
    )


def _assignment(
    instrument_id: str,
    target: PropertyRef,
    value: bool | float | str | Quantity,
    *,
    component_path: tuple[str, ...] = (),
) -> InstrumentStateAssignment:
    return InstrumentStateAssignment(
        resource_id=instrument_id,
        interface_id=target.interface_id,
        component_path=list(component_path),
        property_id=target.property_id,
        value=StateValue(value),
    )


def _execute_batch(
    instruments: DomainInstrumentExecutor,
    batch: RunHardwareBatch,
) -> RunHardwareBatchReceipt:
    receipt = instruments.execute(batch)
    if receipt.operation_id != batch.operation_id:
        raise RuntimeError("instrument worker returned a mismatched target receipt")
    if receipt.indeterminate:
        raise RuntimeError("target device-program outcome is indeterminate")
    if receipt.problems:
        raise OperationFailure(receipt.problems)
    return receipt


def _digitizer_frames(
    artifact: ListModeArtifact,
    entry: ListModeEntry,
    *,
    playback: AwgPlayback,
    receipt: RunHardwareBatchReceipt | None,
) -> tuple[DigitizerFrame, ...]:
    if not entry.acquisitions:
        return ()
    if receipt is None:
        raise RuntimeError("digitizer acquisitions produced no hardware receipt")
    values = {value.value_id: value.value for value in receipt.values}
    expected_ids = {
        (
            _raw_value_id(window.input_id)
            if window.lowering.device_result_representation == "raw_trace"
            else _iq_value_id(window.input_id)
        )
        for window in entry.acquisitions
    }
    if set(values) != expected_ids:
        raise RuntimeError(
            "digitizer receipt values do not match the target ADC program"
        )

    traces: dict[DigitizerInputId, tuple[float, ...] | None] = {}
    device_iq: dict[DigitizerAcquisitionWindow, complex | None] = {}
    windows_by_input: dict[DigitizerInputId, list[DigitizerAcquisitionWindow]] = {}
    for window in entry.acquisitions:
        windows_by_input.setdefault(window.input_id, []).append(window)
    for input_id, windows in windows_by_input.items():
        if windows[0].lowering.device_result_representation == "raw_trace":
            value = values[_raw_value_id(input_id)]
            traces[input_id] = _worker_trace(
                value,
                sample_count=entry.sample_count,
            )
            continue
        lowered_values = _worker_iq_values(
            values[_iq_value_id(input_id)],
            result_count=len(windows),
        )
        device_iq.update(zip(windows, lowered_values, strict=True))

    return tuple(
        DigitizerFrame(
            shot_index=playback.shot_index,
            entry_id=playback.entry_id,
            slot_id=window.slot_id,
            value=(
                device_iq[window]
                if window.lowering.execution == "device"
                else _demodulate(
                    traces[window.input_id],
                    window=window,
                    sample_rate_hz=artifact.sample_rate_hz,
                )
            ),
        )
        for window in entry.acquisitions
    )


def _raw_value_id(input_id: DigitizerInputId) -> str:
    return f"raw:{input_id.value}"


def _iq_value_id(input_id: DigitizerInputId) -> str:
    return f"integrated-iq:{input_id.value}"


def _worker_trace(
    value: object,
    *,
    sample_count: int,
) -> tuple[float, ...] | None:
    if isinstance(value, MeasurementUnavailable):
        return None
    if not isinstance(value, MeasurementArray):
        raise RuntimeError("digitizer ADC result is not an array")
    if value.dtype != "float64" or value.unit != "V" or value.shape != (sample_count,):
        raise RuntimeError("digitizer ADC result does not match the requested trace")
    samples = cast("NDArray[np.float64]", value.values)
    return tuple(cast("list[float]", samples.tolist()))


def _worker_iq_values(
    value: object,
    *,
    result_count: int,
) -> tuple[complex | None, ...]:
    if isinstance(value, MeasurementUnavailable):
        return (None,) * result_count
    if not isinstance(value, MeasurementArray):
        raise RuntimeError("digitizer DSP result is not an array")
    if (
        value.dtype != "complex128"
        or value.unit != "V"
        or value.shape != (result_count,)
    ):
        raise RuntimeError("digitizer DSP result does not match requested IQ values")
    values = cast("NDArray[np.complex128]", value.values)
    return tuple(cast("list[complex]", values.tolist()))


def _demodulate(
    trace: tuple[float, ...] | None,
    *,
    window: DigitizerAcquisitionWindow,
    sample_rate_hz: int,
) -> complex | None:
    if trace is None:
        return None
    return integrate_rectangular_iq(
        trace,
        start_sample=window.start_sample,
        sample_count=window.sample_count,
        sample_rate_hz=sample_rate_hz,
        demodulation_frequency_hz=window.intent.demodulation_frequency_hz,
    )


__all__ = [
    "WORKER_ADC_DSP_FINGERPRINT",
    "InstrumentListModeRuntime",
    "list_mode_realtime_write_footprint",
    "list_mode_setup_state_invalidations",
    "list_mode_state_requirements",
]
