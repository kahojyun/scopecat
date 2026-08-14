"""Lower list-mode artifacts to typed commands for reserved bare devices."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
from numpy.typing import NDArray
from scopecat.kernel.errors import OperationFailure
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.state import PayloadRef, StateValue
from scopecat.records.artifact import command_payload_from_bytes
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
from scopecat_quantum.targets import TargetAcquisitionAddress

from reference_lab.bench_interfaces import (
    ANALOG_WAVEFORM_OUTPUT_AMPLITUDE,
    ANALOG_WAVEFORM_OUTPUT_ENABLED,
    ANALOG_WAVEFORM_OUTPUT_OFFSET,
    AWG_ARM_PROGRAM,
    AWG_LOAD_PROGRAM,
    AWG_PROGRAM,
    AWG_RUN_MODE,
    AWG_SAMPLE_RATE,
    DIGITIZER_ARM_PROGRAM,
    DIGITIZER_FETCH_PROGRAM,
    DIGITIZER_FETCH_PROGRAM_IQ,
    DIGITIZER_FETCH_PROGRAM_IQ_VALUE,
    DIGITIZER_FETCH_PROGRAM_VALUE,
    DIGITIZER_INPUT_COUPLING,
    DIGITIZER_INPUT_ENABLED,
    DIGITIZER_INPUT_RANGE,
    DIGITIZER_LOAD_PROGRAM,
    DIGITIZER_PROGRAM,
    DIGITIZER_RECORD_LENGTH,
    DIGITIZER_SAMPLE_RATE,
    DIGITIZER_TRIGGER_SOURCE,
    TRIGGER_LOAD_PROGRAM,
    TRIGGER_PROGRAM,
    TRIGGER_START_PROGRAM,
    TRIGGER_START_PROGRAM_IDEMPOTENT,
)
from reference_lab.interfaces import (
    CLOCK_REFERENCE_FREQUENCY,
    CLOCK_REFERENCE_SOURCE,
)
from reference_lab.payloads import (
    AWG_PROGRAM_SCHEMA_ID,
    DIGITIZER_PROGRAM_SCHEMA_ID,
    TRIGGER_PROGRAM_SCHEMA_ID,
    reference_lab_payload_codecs,
)
from reference_lab.targets.list_mode.execution_model import (
    DigitizerResultBatch,
    ListModeRun,
    digitizer_addresses,
    run_fingerprint,
)
from reference_lab.targets.list_mode.iq_semantics import (
    integrate_rectangular_iq,
)
from reference_lab.targets.list_mode.model import (
    DigitizerAcquisitionWindow,
    DigitizerInputId,
    ListModeArtifact,
    ListModeEntry,
    MaterializedAwgProgram,
    PhaseSynthesizedAwgProgram,
)


@dataclass(frozen=True, slots=True)
class InstrumentListModeRuntime:
    """Execute target programs through the admitted instrument worker.

    ``prepare`` loads complete AWG, segmented-digitizer, and timing programs as a
    destructive setup phase. Core then reasserts host-owned offset requirements
    before ``execute`` applies target-owned preparation, arms each device once,
    starts the timing program, and fetches one result block per ADC input. Shots
    and list entries remain inside the realtime program rather than expanding into
    host actions. Program identity is scoped to the domain execution so identical
    artifacts in two invocations do not share a worker receipt.
    """

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
        receipt = _execute_batch(
            instruments,
            _execution_batch(artifact, execution_id=execution_id),
        )
        blocks = _result_blocks(
            artifact,
            receipt=receipt,
            execution_id=execution_id,
        )
        block_offsets = dict.fromkeys(blocks, 0)
        addresses = digitizer_addresses(artifact)
        row_by_address = {
            address: row_index for row_index, address in enumerate(addresses)
        }
        values = np.zeros(
            (len(addresses), artifact.repetitions),
            dtype=np.complex128,
        )
        available = np.ones(values.shape, dtype=np.bool_)
        for shot_index in range(artifact.repetitions):
            for entry in artifact.entries:
                _write_digitizer_results(
                    artifact,
                    entry,
                    shot_index=shot_index,
                    blocks=blocks,
                    block_offsets=block_offsets,
                    row_by_address=row_by_address,
                    values=values,
                    available=available,
                )
        if any(
            block_offsets[input_id] != block.result_count
            for input_id, block in blocks.items()
        ):
            raise RuntimeError("digitizer result block contains unclaimed values")
        results = DigitizerResultBatch(
            addresses=addresses,
            values=values,
            available=available,
        )
        return ListModeRun(
            results=results,
            artifact=artifact,
            fingerprint=run_fingerprint(
                artifact=artifact,
                results=results,
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
        if isinstance(awg_program, MaterializedAwgProgram):
            channels = sorted(
                {
                    waveform.channel_id
                    for entry in awg_program.entries
                    for waveform in entry.waveforms
                }
            )
        else:
            channels = sorted(
                {
                    channel_id
                    for template in awg_program.templates
                    for channel_id in template.channel_ids
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
            _awg_payload_document(awg_program),
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

    for digitizer_program in artifact.digitizer_programs:
        payload_id = f"digitizer-program-{digitizer_program.instrument_id}"
        encoded = codecs.encode(
            DIGITIZER_PROGRAM_SCHEMA_ID,
            {
                "entries": [
                    {
                        "sample_count": program_entry.sample_count,
                        "input_component_paths": [
                            list(input_id.component_path)
                            for input_id in program_entry.input_ids
                        ],
                        "windows": [
                            {
                                "component_path": list(window.input_id.component_path),
                                "demodulator_slot_id": (
                                    window.demodulator_slot_id.value
                                ),
                                "start_sample": window.start_sample,
                                "sample_count": window.sample_count,
                                "demodulation_frequency_hz": (
                                    window.intent.demodulation_frequency_hz
                                ),
                                "semantics_id": window.intent.semantics_id,
                                "normalization": window.intent.normalization,
                            }
                            for window in artifact.entries[entry_index].acquisitions
                            if window.input_id.instrument_id
                            == digitizer_program.instrument_id
                        ],
                    }
                    for entry_index, program_entry in enumerate(
                        digitizer_program.entries
                    )
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
                effect_id=f"{prefix}:load:{digitizer_program.instrument_id}",
                instrument_id=digitizer_program.instrument_id,
                resource_id=digitizer_program.instrument_id,
                interface_id=DIGITIZER_LOAD_PROGRAM.interface_id,
                operation_id=DIGITIZER_LOAD_PROGRAM.operation_id,
                arguments=(
                    InstrumentOperationArgument(
                        id=DIGITIZER_PROGRAM.argument_id,
                        value=StateValue(PayloadRef(payload_id=payload.id)),
                    ),
                ),
                payloads={payload.id: payload},
            )
        )

    timing = artifact.preparation.timing
    timing_payload_id = f"trigger-program-{timing.trigger_instrument_id}"
    trigger_entries = tuple(
        artifact.trigger_participants(entry) for entry in artifact.entries
    )
    encoded = codecs.encode(
        TRIGGER_PROGRAM_SCHEMA_ID,
        {
            "program_id": prefix,
            "repetitions": artifact.repetitions,
            "entries": [
                {
                    "awg_instrument_ids": list(entry.awg_instrument_ids),
                    "digitizer_instrument_ids": list(entry.digitizer_instrument_ids),
                }
                for entry in trigger_entries
            ],
        },
    )
    payload = command_payload_from_bytes(
        id=timing_payload_id,
        schema_id=encoded.schema_id,
        codec_id=encoded.codec_id,
        codec_version=encoded.codec_version,
        media_type=encoded.media_type,
        content=encoded.content,
    )
    actions.append(
        RunHardwareInvoke(
            effect_id=f"{prefix}:load:{timing.trigger_instrument_id}",
            instrument_id=timing.trigger_instrument_id,
            resource_id=timing.trigger_instrument_id,
            interface_id=TRIGGER_LOAD_PROGRAM.interface_id,
            operation_id=TRIGGER_LOAD_PROGRAM.operation_id,
            arguments=(
                InstrumentOperationArgument(
                    id=TRIGGER_PROGRAM.argument_id,
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


def _awg_payload_document(
    program: MaterializedAwgProgram | PhaseSynthesizedAwgProgram,
) -> dict[str, object]:
    if isinstance(program, MaterializedAwgProgram):
        return {
            "kind": "materialized",
            "max_abs_amplitude": program.max_abs_amplitude,
            "entries": [
                {
                    "waveforms": [
                        {
                            "component_path": list(waveform.channel_id.component_path),
                            "samples": waveform.samples,
                        }
                        for waveform in entry.waveforms
                    ]
                }
                for entry in program.entries
            ],
        }
    return {
        "kind": "phase_synthesized",
        "max_abs_amplitude": program.max_abs_amplitude,
        "templates": [
            {
                "id": template.id,
                "i_component_path": list(template.i_channel_id.component_path),
                "q_component_path": list(template.q_channel_id.component_path),
                "start_sample": template.start_sample,
                "logical_i": template.logical_i,
                "logical_q": template.logical_q,
                "mixer": {
                    "ii": template.mixer.ii,
                    "iq": template.mixer.iq,
                    "qi": template.mixer.qi,
                    "qq": template.mixer.qq,
                },
            }
            for template in program.templates
        ],
        "entries": [
            {
                "sample_count": entry.sample_count,
                "template_uses": [
                    {
                        "template_id": use.template_id,
                        "phase_radians": use.phase_radians,
                    }
                    for use in entry.template_uses
                ],
            }
            for entry in program.entries
        ],
    }


def _execution_batch(
    artifact: ListModeArtifact,
    *,
    execution_id: str,
) -> RunHardwareBatch:
    prefix = _execution_prefix(artifact, execution_id=execution_id)
    actions: list[RunHardwareInvoke | RunHardwareCollect] = []
    for digitizer_program in artifact.digitizer_programs:
        actions.append(
            RunHardwareInvoke(
                effect_id=f"{prefix}:arm:{digitizer_program.instrument_id}",
                instrument_id=digitizer_program.instrument_id,
                resource_id=digitizer_program.instrument_id,
                interface_id=DIGITIZER_ARM_PROGRAM.interface_id,
                operation_id=DIGITIZER_ARM_PROGRAM.operation_id,
            )
        )
    for awg_program in artifact.awg_programs:
        actions.append(
            RunHardwareInvoke(
                effect_id=f"{prefix}:arm:{awg_program.instrument_id}",
                instrument_id=awg_program.instrument_id,
                resource_id=awg_program.instrument_id,
                interface_id=AWG_ARM_PROGRAM.interface_id,
                operation_id=AWG_ARM_PROGRAM.operation_id,
            )
        )
    timing = artifact.preparation.timing
    trigger_operation = (
        TRIGGER_START_PROGRAM_IDEMPOTENT
        if timing.program_start_guarantee == "session_idempotent"
        else TRIGGER_START_PROGRAM
    )
    actions.append(
        RunHardwareInvoke(
            effect_id=f"{prefix}:start:{timing.trigger_instrument_id}",
            instrument_id=timing.trigger_instrument_id,
            resource_id=timing.trigger_instrument_id,
            interface_id=trigger_operation.interface_id,
            operation_id=trigger_operation.operation_id,
        )
    )
    digitizer_inputs = sorted(
        {window.input_id for entry in artifact.entries for window in entry.acquisitions}
    )
    for input_id in digitizer_inputs:
        windows = tuple(
            window
            for entry in artifact.entries
            for window in entry.acquisitions
            if window.input_id == input_id
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
                        interface_id=DIGITIZER_FETCH_PROGRAM.interface_id,
                        component_path=list(input_id.component_path),
                        acquisition_id=(
                            DIGITIZER_FETCH_PROGRAM.acquisition_id
                            if representation == "raw_trace"
                            else DIGITIZER_FETCH_PROGRAM_IQ.acquisition_id
                        ),
                        result_id=(
                            DIGITIZER_FETCH_PROGRAM_VALUE.result_id
                            if representation == "raw_trace"
                            else DIGITIZER_FETCH_PROGRAM_IQ_VALUE.result_id
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
                                    artifact.repetitions
                                    * sum(
                                        entry.sample_count
                                        for entry in artifact.entries
                                        if any(
                                            window.input_id == input_id
                                            for window in entry.acquisitions
                                        )
                                    )
                                    if representation == "raw_trace"
                                    else artifact.repetitions * len(windows)
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
    return RunHardwareBatch(operation_id=f"{prefix}:execute", actions=tuple(actions))


def _execution_prefix(artifact: ListModeArtifact, *, execution_id: str) -> str:
    return f"target:{execution_id}:{artifact.id.value}"


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


@dataclass(frozen=True, slots=True)
class _ResultBlock:
    values: NDArray[np.float64] | NDArray[np.complex128] | None
    result_count: int


def _result_blocks(
    artifact: ListModeArtifact,
    *,
    receipt: RunHardwareBatchReceipt,
    execution_id: str,
) -> dict[DigitizerInputId, _ResultBlock]:
    prefix = _execution_prefix(artifact, execution_id=execution_id)
    inputs = sorted(
        {window.input_id for entry in artifact.entries for window in entry.acquisitions}
    )
    collect_effect_ids = {f"{prefix}:collect:{input_id.value}" for input_id in inputs}
    values = {
        value.value_id: value.value
        for value in receipt.values
        if value.evidence.command_id in collect_effect_ids
    }
    expected_ids = {
        (
            _raw_value_id(input_id)
            if _input_representation(artifact, input_id) == "raw_trace"
            else _iq_value_id(input_id)
        )
        for input_id in inputs
    }
    if set(values) != expected_ids:
        raise RuntimeError(
            "digitizer receipt values do not match the target ADC program"
        )

    blocks: dict[DigitizerInputId, _ResultBlock] = {}
    for input_id in inputs:
        representation = _input_representation(artifact, input_id)
        result_count = _input_result_count(artifact, input_id)
        value = values[
            _raw_value_id(input_id)
            if representation == "raw_trace"
            else _iq_value_id(input_id)
        ]
        blocks[input_id] = _worker_result_block(
            value,
            representation=representation,
            result_count=result_count,
        )
    return blocks


def _write_digitizer_results(
    artifact: ListModeArtifact,
    entry: ListModeEntry,
    *,
    shot_index: int,
    blocks: dict[DigitizerInputId, _ResultBlock],
    block_offsets: dict[DigitizerInputId, int],
    row_by_address: dict[TargetAcquisitionAddress, int],
    values: NDArray[np.complex128],
    available: NDArray[np.bool_],
) -> None:
    traces: dict[DigitizerInputId, NDArray[np.float64] | None] = {}
    device_iq: dict[DigitizerAcquisitionWindow, complex | None] = {}
    windows_by_input: dict[DigitizerInputId, list[DigitizerAcquisitionWindow]] = {}
    for window in entry.acquisitions:
        windows_by_input.setdefault(window.input_id, []).append(window)
    for input_id, windows in windows_by_input.items():
        offset = block_offsets[input_id]
        block = blocks[input_id]
        if windows[0].lowering.device_result_representation == "raw_trace":
            traces[input_id] = (
                None
                if block.values is None
                else cast(
                    "NDArray[np.float64]",
                    block.values[offset : offset + entry.sample_count],
                )
            )
            block_offsets[input_id] += entry.sample_count
            continue
        lowered_values = (
            None
            if block.values is None
            else cast(
                "NDArray[np.complex128]",
                block.values[offset : offset + len(windows)],
            )
        )
        block_offsets[input_id] += len(windows)
        for index, window in enumerate(windows):
            device_iq[window] = (
                None
                if lowered_values is None
                else complex(cast("np.complex128", lowered_values[index]))
            )

    for window in entry.acquisitions:
        value = (
            device_iq[window]
            if window.lowering.execution == "device"
            else _demodulate(
                traces[window.input_id],
                window=window,
                sample_rate_hz=artifact.sample_rate_hz,
            )
        )
        address = TargetAcquisitionAddress(
            entry_id=entry.entry_id,
            slot_id=window.slot_id,
        )
        row_index = row_by_address[address]
        if value is None:
            available[row_index, shot_index] = False
        else:
            values[row_index, shot_index] = value


def _raw_value_id(input_id: DigitizerInputId) -> str:
    return f"raw:{input_id.value}"


def _iq_value_id(input_id: DigitizerInputId) -> str:
    return f"integrated-iq:{input_id.value}"


def _input_representation(
    artifact: ListModeArtifact,
    input_id: DigitizerInputId,
) -> str:
    return next(
        window.lowering.device_result_representation
        for entry in artifact.entries
        for window in entry.acquisitions
        if window.input_id == input_id
    )


def _input_result_count(
    artifact: ListModeArtifact,
    input_id: DigitizerInputId,
) -> int:
    if _input_representation(artifact, input_id) == "raw_trace":
        per_shot = sum(
            entry.sample_count
            for entry in artifact.entries
            if any(window.input_id == input_id for window in entry.acquisitions)
        )
    else:
        per_shot = sum(
            window.input_id == input_id
            for entry in artifact.entries
            for window in entry.acquisitions
        )
    return artifact.repetitions * per_shot


def _worker_result_block(
    value: object,
    *,
    representation: str,
    result_count: int,
) -> _ResultBlock:
    if isinstance(value, MeasurementUnavailable):
        return _ResultBlock(values=None, result_count=result_count)
    if not isinstance(value, MeasurementArray):
        raise RuntimeError("digitizer ADC result is not an array")
    dtype = "float64" if representation == "raw_trace" else "complex128"
    if value.dtype != dtype or value.unit != "V" or value.shape != (result_count,):
        raise RuntimeError("digitizer result does not match requested program block")
    values = cast("NDArray[np.float64] | NDArray[np.complex128]", value.values)
    return _ResultBlock(values=values, result_count=result_count)


def _demodulate(
    trace: NDArray[np.float64] | None,
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
