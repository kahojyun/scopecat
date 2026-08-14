"""Pulse-program payload codec shared by planning and the instrument worker."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass, field
from typing import Literal, cast

import numpy as np
from pydantic import BaseModel, ConfigDict, Field
from scopecat.sdk.payloads import PayloadCodec, PayloadCodecRegistry

SAMPLED_WAVEFORM_SCHEMA_ID = "sampled_waveform"
AWG_PROGRAM_SCHEMA_ID = "reference_lab.awg_program.v4"
DIGITIZER_PROGRAM_SCHEMA_ID = "reference_lab.digitizer_program.v1"
TRIGGER_PROGRAM_SCHEMA_ID = "reference_lab.trigger_program.v1"


@dataclass(frozen=True, slots=True)
class DecodedSampledWaveform:
    samples: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class DecodedAwgChannelWaveform:
    component_path: tuple[str, ...]
    samples: np.ndarray = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class DecodedAwgEntry:
    waveforms: tuple[DecodedAwgChannelWaveform, ...]


@dataclass(frozen=True, slots=True)
class DecodedMaterializedAwgProgram:
    """Ordinary per-entry DAC buffers ready for an AWG driver."""

    max_abs_amplitude: float
    entries: tuple[DecodedAwgEntry, ...]


@dataclass(frozen=True, slots=True)
class DecodedAwgPhaseTemplate:
    id: str
    i_component_path: tuple[str, ...]
    q_component_path: tuple[str, ...]
    start_sample: int
    logical_i: np.ndarray = field(repr=False, compare=False)
    logical_q: np.ndarray = field(repr=False, compare=False)
    mixer: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class DecodedAwgPhaseTemplateUse:
    template_id: str
    phase_radians: float


@dataclass(frozen=True, slots=True)
class DecodedPhaseSynthesizedAwgEntry:
    sample_count: int
    template_uses: tuple[DecodedAwgPhaseTemplateUse, ...]


@dataclass(frozen=True, slots=True)
class DecodedPhaseSynthesizedAwgProgram:
    """Compact phase rows that must become ordinary buffers before upload."""

    max_abs_amplitude: float
    templates: tuple[DecodedAwgPhaseTemplate, ...]
    entries: tuple[DecodedPhaseSynthesizedAwgEntry, ...]

    def materialize(self) -> DecodedMaterializedAwgProgram:
        templates = {template.id: template for template in self.templates}
        materialized = DecodedMaterializedAwgProgram(
            max_abs_amplitude=self.max_abs_amplitude,
            entries=tuple(
                _materialize_phase_entry(entry, templates=templates)
                for entry in self.entries
            ),
        )
        _validate_awg_amplitudes(materialized)
        return materialized


type DecodedAwgProgram = (
    DecodedMaterializedAwgProgram | DecodedPhaseSynthesizedAwgProgram
)


def materialize_awg_program(
    program: DecodedAwgProgram,
) -> DecodedMaterializedAwgProgram:
    """Cross the simple-AWG boundary with contiguous physical buffers."""

    if isinstance(program, DecodedPhaseSynthesizedAwgProgram):
        return program.materialize()
    _validate_awg_amplitudes(program)
    return program


@dataclass(frozen=True, slots=True)
class DecodedDigitizerDspWindow:
    component_path: tuple[str, ...]
    demodulator_slot_id: str
    start_sample: int
    sample_count: int
    demodulation_frequency_hz: float
    semantics_id: Literal["reference_lab.integrated_iq.ssb_midpoint.v1"]
    normalization: Literal["single_sideband_amplitude"]


@dataclass(frozen=True, slots=True)
class DecodedDigitizerProgramEntry:
    sample_count: int
    input_component_paths: tuple[tuple[str, ...], ...]
    windows: tuple[DecodedDigitizerDspWindow, ...]


@dataclass(frozen=True, slots=True)
class DecodedDigitizerProgram:
    entries: tuple[DecodedDigitizerProgramEntry, ...]


@dataclass(frozen=True, slots=True)
class DecodedTriggerProgramEntry:
    awg_instrument_ids: tuple[str, ...]
    digitizer_instrument_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DecodedTriggerProgram:
    program_id: str
    repetitions: int
    entries: tuple[DecodedTriggerProgramEntry, ...]


class _SampledWaveformDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    samples: tuple[float, ...] = Field(min_length=1)


class _DigitizerDspWindowDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    component_path: tuple[str, ...] = Field(min_length=1)
    demodulator_slot_id: str = Field(min_length=1)
    start_sample: int = Field(ge=0)
    sample_count: int = Field(gt=0)
    demodulation_frequency_hz: float
    semantics_id: Literal["reference_lab.integrated_iq.ssb_midpoint.v1"]
    normalization: Literal["single_sideband_amplitude"]


class _DigitizerProgramEntryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_count: int = Field(gt=0)
    input_component_paths: tuple[tuple[str, ...], ...]
    windows: tuple[_DigitizerDspWindowDocument, ...]


class _DigitizerProgramDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    entries: tuple[_DigitizerProgramEntryDocument, ...] = Field(min_length=1)


class _TriggerProgramEntryDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    awg_instrument_ids: tuple[str, ...]
    digitizer_instrument_ids: tuple[str, ...]


class _TriggerProgramDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_id: str = Field(min_length=1)
    repetitions: int = Field(gt=0)
    entries: tuple[_TriggerProgramEntryDocument, ...] = Field(min_length=1)


def reference_lab_payload_codecs() -> PayloadCodecRegistry:
    from reference_lab.virtual_lab.capture_payload import (
        VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID,
        virtual_capture_queue_codec,
    )

    return PayloadCodecRegistry(
        {
            DIGITIZER_PROGRAM_SCHEMA_ID: PayloadCodec(
                id="reference_lab.digitizer-program-json",
                version=1,
                media_type="application/json",
                encoder=_encode_digitizer_program,
                decoder=_decode_digitizer_program,
            ),
            TRIGGER_PROGRAM_SCHEMA_ID: PayloadCodec(
                id="reference_lab.trigger-program-json",
                version=1,
                media_type="application/json",
                encoder=_encode_trigger_program,
                decoder=_decode_trigger_program,
            ),
            VIRTUAL_CAPTURE_QUEUE_SCHEMA_ID: virtual_capture_queue_codec(),
            AWG_PROGRAM_SCHEMA_ID: PayloadCodec(
                id="reference_lab.awg-program-float64",
                version=4,
                media_type="application/vnd.scopecat.awg-program+float64",
                encoder=_encode_awg_program,
                decoder=_decode_awg_program,
            ),
            SAMPLED_WAVEFORM_SCHEMA_ID: PayloadCodec(
                id="reference_lab.sampled-waveform-json",
                version=1,
                media_type="application/json",
                encoder=_encode_sampled_waveform,
                decoder=_decode_sampled_waveform,
            ),
        }
    )


def _encode_sampled_waveform(value: object) -> bytes:
    document = _SampledWaveformDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_sampled_waveform(content: bytes) -> object:
    document = _SampledWaveformDocument.model_validate_json(content)
    return DecodedSampledWaveform(samples=document.samples)


def _encode_awg_program(value: object) -> bytes:
    document = cast("dict[str, object]", value)
    sample_views: list[memoryview] = []
    kind = cast("str", document["kind"])
    if kind == "materialized":
        encoded_entries: list[dict[str, object]] = []
        for entry in cast("list[dict[str, object]]", document["entries"]):
            encoded_waveforms: list[dict[str, object]] = []
            for waveform in cast("list[dict[str, object]]", entry["waveforms"]):
                samples = np.ascontiguousarray(waveform["samples"], dtype="<f8")
                encoded_waveforms.append(
                    {
                        "component_path": waveform["component_path"],
                        "sample_count": int(samples.size),
                    }
                )
                sample_views.append(memoryview(samples).cast("B"))
            encoded_entries.append({"waveforms": encoded_waveforms})
        header_document: dict[str, object] = {
            "kind": kind,
            "max_abs_amplitude": document["max_abs_amplitude"],
            "entries": encoded_entries,
        }
    elif kind == "phase_synthesized":
        encoded_templates: list[dict[str, object]] = []
        for template in cast("list[dict[str, object]]", document["templates"]):
            logical_i = np.ascontiguousarray(template["logical_i"], dtype="<f8")
            logical_q = np.ascontiguousarray(template["logical_q"], dtype="<f8")
            if logical_i.size != logical_q.size:
                raise ValueError("AWG phase-template bases must have equal lengths")
            sample_views.extend(
                (memoryview(logical_i).cast("B"), memoryview(logical_q).cast("B"))
            )
            encoded_templates.append(
                {
                    "id": template["id"],
                    "i_component_path": template["i_component_path"],
                    "q_component_path": template["q_component_path"],
                    "start_sample": template["start_sample"],
                    "sample_count": int(logical_i.size),
                    "mixer": template["mixer"],
                }
            )
        header_document = {
            "kind": kind,
            "max_abs_amplitude": document["max_abs_amplitude"],
            "templates": encoded_templates,
            "entries": document["entries"],
        }
    else:
        raise ValueError(f"unknown AWG program kind: {kind!r}")
    header = json.dumps(header_document, separators=(",", ":")).encode("utf-8")
    encoded = bytearray(8 + len(header) + sum(len(view) for view in sample_views))
    struct.pack_into("<Q", encoded, 0, len(header))
    encoded[8 : 8 + len(header)] = header
    offset = 8 + len(header)
    for view in sample_views:
        encoded[offset : offset + len(view)] = view
        offset += len(view)
    return bytes(encoded)


def _decode_awg_program(content: bytes) -> object:
    header_size = cast("int", struct.unpack_from("<Q", content)[0])
    body_offset = 8 + header_size
    document = cast(
        "dict[str, object]",
        json.loads(content[8:body_offset]),
    )
    kind = cast("str", document["kind"])
    if kind == "phase_synthesized":
        return _decode_phase_synthesized_awg_program(
            content,
            document,
            body_offset=body_offset,
        )
    if kind != "materialized":
        raise ValueError(f"unknown AWG program kind: {kind!r}")
    entries: list[DecodedAwgEntry] = []
    for entry in cast("list[dict[str, object]]", document["entries"]):
        waveforms: list[DecodedAwgChannelWaveform] = []
        for waveform in cast("list[dict[str, object]]", entry["waveforms"]):
            sample_count = cast("int", waveform["sample_count"])
            samples = np.frombuffer(
                content,
                dtype="<f8",
                count=sample_count,
                offset=body_offset,
            )
            body_offset += samples.nbytes
            waveforms.append(
                DecodedAwgChannelWaveform(
                    component_path=tuple(cast("list[str]", waveform["component_path"])),
                    samples=samples,
                )
            )
        entries.append(
            DecodedAwgEntry(
                waveforms=tuple(waveforms),
            )
        )
    return DecodedMaterializedAwgProgram(
        max_abs_amplitude=cast("float", document["max_abs_amplitude"]),
        entries=tuple(entries),
    )


def _decode_phase_synthesized_awg_program(
    content: bytes,
    document: dict[str, object],
    *,
    body_offset: int,
) -> DecodedPhaseSynthesizedAwgProgram:
    templates: list[DecodedAwgPhaseTemplate] = []
    for template in cast("list[dict[str, object]]", document["templates"]):
        sample_count = cast("int", template["sample_count"])
        logical_i = np.frombuffer(
            content,
            dtype="<f8",
            count=sample_count,
            offset=body_offset,
        )
        body_offset += logical_i.nbytes
        logical_q = np.frombuffer(
            content,
            dtype="<f8",
            count=sample_count,
            offset=body_offset,
        )
        body_offset += logical_q.nbytes
        mixer = cast("dict[str, float]", template["mixer"])
        templates.append(
            DecodedAwgPhaseTemplate(
                id=cast("str", template["id"]),
                i_component_path=tuple(cast("list[str]", template["i_component_path"])),
                q_component_path=tuple(cast("list[str]", template["q_component_path"])),
                start_sample=cast("int", template["start_sample"]),
                logical_i=logical_i,
                logical_q=logical_q,
                mixer=(mixer["ii"], mixer["iq"], mixer["qi"], mixer["qq"]),
            )
        )
    return DecodedPhaseSynthesizedAwgProgram(
        max_abs_amplitude=cast("float", document["max_abs_amplitude"]),
        templates=tuple(templates),
        entries=tuple(
            DecodedPhaseSynthesizedAwgEntry(
                sample_count=cast("int", entry["sample_count"]),
                template_uses=tuple(
                    DecodedAwgPhaseTemplateUse(
                        template_id=cast("str", use["template_id"]),
                        phase_radians=cast("float", use["phase_radians"]),
                    )
                    for use in cast(
                        "list[dict[str, object]]",
                        entry["template_uses"],
                    )
                ),
            )
            for entry in cast("list[dict[str, object]]", document["entries"])
        ),
    )


def _materialize_phase_entry(
    entry: DecodedPhaseSynthesizedAwgEntry,
    *,
    templates: dict[str, DecodedAwgPhaseTemplate],
) -> DecodedAwgEntry:
    buffers: dict[tuple[str, ...], np.ndarray] = {}
    for use in entry.template_uses:
        template = templates[use.template_id]
        logical_i = template.logical_i
        logical_q = template.logical_q
        ii, iq, qi, qq = template.mixer
        selected = slice(
            template.start_sample,
            template.start_sample + logical_i.size,
        )
        cosine = math.cos(use.phase_radians)
        sine = math.sin(use.phase_radians)
        for component_path, mixer_i, mixer_q in (
            (template.i_component_path, ii, iq),
            (template.q_component_path, qi, qq),
        ):
            buffer = buffers.setdefault(
                component_path,
                np.zeros(entry.sample_count, dtype=np.float64),
            )
            buffer[selected] += cosine * (
                mixer_i * logical_i + mixer_q * logical_q
            ) + sine * (-mixer_i * logical_q + mixer_q * logical_i)
    for samples in buffers.values():
        samples.flags.writeable = False
    return DecodedAwgEntry(
        waveforms=tuple(
            DecodedAwgChannelWaveform(
                component_path=component_path,
                samples=samples,
            )
            for component_path, samples in sorted(buffers.items())
        )
    )


def _validate_awg_amplitudes(program: DecodedMaterializedAwgProgram) -> None:
    for entry_index, entry in enumerate(program.entries):
        for waveform in entry.waveforms:
            peak = (
                float(cast("np.float64", np.max(np.abs(waveform.samples))))
                if waveform.samples.size
                else 0.0
            )
            if peak > program.max_abs_amplitude:
                component = "/".join(waveform.component_path)
                raise ValueError(
                    f"AWG entry {entry_index} waveform {component!r} has magnitude "
                    f"{peak!r}; device limit is {program.max_abs_amplitude!r}"
                )


def _encode_digitizer_program(value: object) -> bytes:
    document = _DigitizerProgramDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_digitizer_program(content: bytes) -> object:
    document = _DigitizerProgramDocument.model_validate_json(content)
    return DecodedDigitizerProgram(
        entries=tuple(
            DecodedDigitizerProgramEntry(
                sample_count=entry.sample_count,
                input_component_paths=entry.input_component_paths,
                windows=tuple(
                    _decoded_digitizer_window(window) for window in entry.windows
                ),
            )
            for entry in document.entries
        )
    )


def _decoded_digitizer_window(
    window: _DigitizerDspWindowDocument,
) -> DecodedDigitizerDspWindow:
    return DecodedDigitizerDspWindow(
        component_path=window.component_path,
        demodulator_slot_id=window.demodulator_slot_id,
        start_sample=window.start_sample,
        sample_count=window.sample_count,
        demodulation_frequency_hz=window.demodulation_frequency_hz,
        semantics_id=window.semantics_id,
        normalization=window.normalization,
    )


def _encode_trigger_program(value: object) -> bytes:
    document = _TriggerProgramDocument.model_validate(value)
    return document.model_dump_json().encode("utf-8")


def _decode_trigger_program(content: bytes) -> object:
    document = _TriggerProgramDocument.model_validate_json(content)
    return DecodedTriggerProgram(
        program_id=document.program_id,
        repetitions=document.repetitions,
        entries=tuple(
            DecodedTriggerProgramEntry(
                awg_instrument_ids=entry.awg_instrument_ids,
                digitizer_instrument_ids=entry.digitizer_instrument_ids,
            )
            for entry in document.entries
        ),
    )


__all__ = [
    "AWG_PROGRAM_SCHEMA_ID",
    "DIGITIZER_PROGRAM_SCHEMA_ID",
    "SAMPLED_WAVEFORM_SCHEMA_ID",
    "TRIGGER_PROGRAM_SCHEMA_ID",
    "DecodedAwgChannelWaveform",
    "DecodedAwgEntry",
    "DecodedAwgPhaseTemplate",
    "DecodedAwgPhaseTemplateUse",
    "DecodedAwgProgram",
    "DecodedDigitizerDspWindow",
    "DecodedDigitizerProgram",
    "DecodedDigitizerProgramEntry",
    "DecodedMaterializedAwgProgram",
    "DecodedPhaseSynthesizedAwgEntry",
    "DecodedPhaseSynthesizedAwgProgram",
    "DecodedSampledWaveform",
    "DecodedTriggerProgram",
    "DecodedTriggerProgramEntry",
    "materialize_awg_program",
    "reference_lab_payload_codecs",
]
