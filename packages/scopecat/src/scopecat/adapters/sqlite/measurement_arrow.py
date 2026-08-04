# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false
"""Arrow IPC codec for immutable measurement append chunks."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

import numpy as np
import pyarrow as pa

from scopecat.records._metadata import JsonMetadata, validate_json_metadata
from scopecat.records.measurement import (
    ComplexComponents,
    InstrumentAcquisitionEvidence,
    MeasurementArray,
    MeasurementDType,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementScalarData,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
    MeasurementValue,
)
from scopecat.records.measurement_recording import MeasurementDatasetAppend

MEASUREMENT_APPEND_ARROW_FORMAT = "scopecat.measurement_append.arrow.v1"

_FORMAT_KEY = b"scopecat.format"
_RUN_ID_KEY = b"scopecat.run_id"
_HEADER_CONTENT_HASH_KEY = b"scopecat.header_content_hash"
_START_INDEX_KEY = b"scopecat.start_index"
_OPERATION_ID_KEY = b"scopecat.operation_id"
_CONTENT_HASH_KEY = b"scopecat.content_hash"
_RECORD_COUNT_KEY = b"scopecat.record_count"

_COMPLEX_TYPE = pa.struct(
    [
        pa.field("real", pa.float64(), nullable=False),
        pa.field("imag", pa.float64(), nullable=False),
    ]
)
_VALUE_TYPE = pa.struct(
    [
        pa.field("kind", pa.string(), nullable=False),
        pa.field("dtype", pa.string(), nullable=False),
        pa.field("storage_dtype", pa.string()),
        pa.field("unit", pa.string()),
        pa.field("reason", pa.string()),
        pa.field(
            "shape",
            pa.large_list(pa.field("extent", pa.int64())),
            nullable=False,
        ),
        pa.field("bool_values", pa.large_list(pa.bool_())),
        pa.field("int64_values", pa.large_list(pa.int64())),
        pa.field("float64_values", pa.large_list(pa.float64())),
        pa.field("string_values", pa.large_list(pa.large_string())),
        pa.field("complex128_values", pa.large_list(_COMPLEX_TYPE)),
        pa.field("metadata_json", pa.large_binary(), nullable=False),
    ]
)
_VALUE_MAP_TYPE = pa.map_(pa.string(), _VALUE_TYPE)
_EVIDENCE_TYPE = pa.struct(
    [
        pa.field("command_id", pa.string(), nullable=False),
        pa.field("instrument_id", pa.string(), nullable=False),
        pa.field("interface_id", pa.string(), nullable=False),
        pa.field(
            "component_path",
            pa.large_list(pa.field("component", pa.string(), nullable=False)),
            nullable=False,
        ),
        pa.field("acquisition_id", pa.string(), nullable=False),
        pa.field("result_id", pa.string(), nullable=False),
        pa.field("started_at", pa.string(), nullable=False),
        pa.field("completed_at", pa.string(), nullable=False),
    ]
)
_EVIDENCE_MAP_TYPE = pa.map_(pa.string(), _EVIDENCE_TYPE)
_RECORD_SCHEMA = pa.schema(
    [
        pa.field("logical_point_id", pa.string()),
        pa.field("point_index", pa.int64(), nullable=False),
        pa.field("coordinates", _VALUE_MAP_TYPE, nullable=False),
        pa.field("observables", _VALUE_MAP_TYPE, nullable=False),
        pa.field("acquisition_evidence", _EVIDENCE_MAP_TYPE, nullable=False),
        pa.field("metadata_json", pa.large_binary(), nullable=False),
    ]
)


class MeasurementArrowCodecError(ValueError):
    """An Arrow measurement chunk does not match the current durable format."""


@dataclass(frozen=True, slots=True)
class _AppendIdentity:
    run_id: str
    header_content_hash: str
    start_index: int
    operation_id: str
    content_hash: str
    record_count: int


def encode_measurement_append(append: MeasurementDatasetAppend) -> bytes:
    """Encode one validated append as a single Arrow IPC record batch file."""

    try:
        metadata = {
            _FORMAT_KEY: MEASUREMENT_APPEND_ARROW_FORMAT.encode(),
            _RUN_ID_KEY: append.run_id.encode(),
            _HEADER_CONTENT_HASH_KEY: append.header_content_hash.encode(),
            _START_INDEX_KEY: str(append.start_index).encode(),
            _OPERATION_ID_KEY: append.operation_id.encode(),
            _CONTENT_HASH_KEY: append.content_hash.encode(),
            _RECORD_COUNT_KEY: str(len(append.records)).encode(),
        }
        rows = [_encode_record(record) for record in append.records]
        batch = pa.RecordBatch.from_pylist(
            rows,
            schema=_RECORD_SCHEMA.with_metadata(metadata),
        )
        sink = pa.BufferOutputStream()
        with pa.ipc.new_file(sink, batch.schema) as writer:
            writer.write_batch(batch)
        return sink.getvalue().to_pybytes()
    except MeasurementArrowCodecError:
        raise
    except (
        pa.ArrowException,
        OverflowError,
        TypeError,
        UnicodeError,
        ValueError,
    ) as error:
        raise MeasurementArrowCodecError(
            "measurement append cannot be encoded as Arrow IPC"
        ) from error


def decode_measurement_append(content: bytes) -> MeasurementDatasetAppend:
    """Decode a complete append and verify its embedded durable identity."""

    batch, identity = _read_batch(content)
    records = _decode_records(batch, run_id=identity.run_id)
    try:
        append = MeasurementDatasetAppend(
            run_id=identity.run_id,
            header_content_hash=identity.header_content_hash,
            start_index=identity.start_index,
            records=records,
        )
    except ValueError as error:
        raise MeasurementArrowCodecError(
            "measurement Arrow append identity is invalid"
        ) from error
    if append.operation_id != identity.operation_id:
        raise MeasurementArrowCodecError(
            "measurement Arrow operation identity does not match its records"
        )
    if append.content_hash != identity.content_hash:
        raise MeasurementArrowCodecError(
            "measurement Arrow content hash does not match its records"
        )
    return append


def decode_measurement_record_slice(
    content: bytes,
    *,
    offset: int,
    length: int,
) -> tuple[MeasurementRecord, ...]:
    """Decode a contiguous row slice without materializing other records."""

    batch, identity = _read_batch(content)
    if offset < 0 or length < 0 or offset + length > batch.num_rows:
        raise MeasurementArrowCodecError("measurement Arrow slice is out of bounds")
    records = _decode_records(
        batch.slice(offset, length),
        run_id=identity.run_id,
    )
    _validate_selected_point_indices(
        records,
        expected_indices=range(
            identity.start_index + offset,
            identity.start_index + offset + length,
        ),
    )
    return records


def decode_measurement_record_indices(
    content: bytes,
    indices: Sequence[int],
) -> tuple[MeasurementRecord, ...]:
    """Decode selected rows in caller order without materializing other records."""

    batch, identity = _read_batch(content)
    selected = tuple(indices)
    if any(index < 0 or index >= batch.num_rows for index in selected):
        raise MeasurementArrowCodecError(
            "measurement Arrow row selection is out of bounds"
        )
    if not selected:
        return ()
    taken = batch.take(pa.array(selected, type=pa.int64()))
    records = _decode_records(taken, run_id=identity.run_id)
    _validate_selected_point_indices(
        records,
        expected_indices=(identity.start_index + index for index in selected),
    )
    return records


def _read_batch(content: bytes) -> tuple[pa.RecordBatch, _AppendIdentity]:
    try:
        reader = pa.ipc.open_file(pa.BufferReader(content))
        if reader.num_record_batches != 1:
            raise MeasurementArrowCodecError(
                "measurement Arrow chunk must contain exactly one record batch"
            )
        schema = reader.schema
        if not schema.remove_metadata().equals(_RECORD_SCHEMA):
            raise MeasurementArrowCodecError(
                "measurement Arrow chunk has an unexpected record schema"
            )
        identity = _decode_identity(schema.metadata)
        batch = reader.get_batch(0)
    except MeasurementArrowCodecError:
        raise
    except (pa.ArrowException, UnicodeError, ValueError) as error:
        raise MeasurementArrowCodecError("invalid measurement Arrow chunk") from error
    if batch.num_rows != identity.record_count:
        raise MeasurementArrowCodecError(
            "measurement Arrow record count does not match its metadata"
        )
    if identity.record_count < 1:
        raise MeasurementArrowCodecError(
            "measurement Arrow chunk must contain at least one record"
        )
    return batch, identity


def _decode_identity(metadata: Mapping[bytes, bytes] | None) -> _AppendIdentity:
    if metadata is None:
        raise MeasurementArrowCodecError("measurement Arrow metadata is missing")
    try:
        format_version = metadata[_FORMAT_KEY].decode()
        identity = _AppendIdentity(
            run_id=metadata[_RUN_ID_KEY].decode(),
            header_content_hash=metadata[_HEADER_CONTENT_HASH_KEY].decode(),
            start_index=int(metadata[_START_INDEX_KEY]),
            operation_id=metadata[_OPERATION_ID_KEY].decode(),
            content_hash=metadata[_CONTENT_HASH_KEY].decode(),
            record_count=int(metadata[_RECORD_COUNT_KEY]),
        )
    except (KeyError, UnicodeError, ValueError) as error:
        raise MeasurementArrowCodecError(
            "measurement Arrow identity metadata is invalid"
        ) from error
    if format_version != MEASUREMENT_APPEND_ARROW_FORMAT:
        raise MeasurementArrowCodecError(
            f"unsupported measurement Arrow format: {format_version}"
        )
    if identity.start_index < 0 or identity.record_count < 0:
        raise MeasurementArrowCodecError(
            "measurement Arrow identity metadata cannot be negative"
        )
    return identity


def _encode_record(record: MeasurementRecord) -> dict[str, object]:
    return {
        "logical_point_id": record.logical_point_id,
        "point_index": record.point_index,
        "coordinates": {
            name: _encode_value(record.coordinates[name])
            for name in sorted(record.coordinates)
        },
        "observables": {
            name: _encode_value(record.observables[name])
            for name in sorted(record.observables)
        },
        "acquisition_evidence": {
            name: _encode_evidence(record.acquisition_evidence[name])
            for name in sorted(record.acquisition_evidence)
        },
        "metadata_json": _encode_json(record.metadata),
    }


def _encode_value(value: MeasurementValue) -> dict[str, object]:
    encoded: dict[str, object] = {
        "kind": value.kind,
        "dtype": value.dtype,
        "storage_dtype": None,
        "unit": value.unit,
        "reason": None,
        "shape": [],
        "bool_values": None,
        "int64_values": None,
        "float64_values": None,
        "string_values": None,
        "complex128_values": None,
        "metadata_json": _encode_json(value.metadata),
    }
    if isinstance(value, MeasurementUnavailable):
        encoded["reason"] = value.reason
        encoded["shape"] = list(value.shape)
        return encoded

    if isinstance(value, MeasurementScalar):
        values: Sequence[object] = (value.value,)
        storage_dtype = _scalar_storage_dtype(value.value)
    else:
        encoded["shape"] = list(value.shape)
        values = cast(
            "Sequence[object]",
            np.asarray(value.values).reshape(-1).tolist(),
        )
        storage_dtype = value.dtype
    encoded["storage_dtype"] = storage_dtype
    encoded[_value_column(storage_dtype)] = _encode_typed_values(
        values,
        dtype=storage_dtype,
    )
    return encoded


def _encode_typed_values(
    values: Sequence[object],
    *,
    dtype: MeasurementDType,
) -> list[object]:
    if dtype == "complex128":
        encoded: list[object] = []
        for item in values:
            selected = _as_complex(item)
            encoded.append({"real": selected.real, "imag": selected.imag})
        return encoded
    if dtype == "bool":
        return [bool(item) for item in values]
    if dtype == "int64":
        return [int(cast("int", item)) for item in values]
    if dtype == "float64":
        return [float(cast("float", item)) for item in values]
    return [str(item) for item in values]


def _as_complex(value: object) -> complex:
    if isinstance(value, ComplexComponents):
        return complex(value.real, value.imag)
    if isinstance(value, complex):
        return value
    if isinstance(value, Mapping):
        selected = cast("Mapping[str, object]", value)
        return complex(
            float(cast("float", selected["real"])),
            float(cast("float", selected["imag"])),
        )
    return complex(cast("float", value))


def _scalar_storage_dtype(value: object) -> MeasurementDType:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int64"
    if isinstance(value, float):
        return "float64"
    if isinstance(value, str):
        return "string"
    return "complex128"


def _value_column(dtype: MeasurementDType) -> str:
    return f"{dtype}_values"


def _encode_evidence(evidence: InstrumentAcquisitionEvidence) -> dict[str, object]:
    return {
        "command_id": evidence.command_id,
        "instrument_id": evidence.instrument_id,
        "interface_id": evidence.interface_id,
        "component_path": list(evidence.component_path),
        "acquisition_id": evidence.acquisition_id,
        "result_id": evidence.result_id,
        "started_at": evidence.started_at.isoformat(),
        "completed_at": evidence.completed_at.isoformat(),
    }


def _decode_records(
    batch: pa.RecordBatch,
    *,
    run_id: str,
) -> tuple[MeasurementRecord, ...]:
    try:
        return tuple(
            _decode_record(cast("dict[str, object]", row), run_id=run_id)
            for row in batch.to_pylist()
        )
    except MeasurementArrowCodecError:
        raise
    except (KeyError, TypeError, ValueError, pa.ArrowException) as error:
        raise MeasurementArrowCodecError(
            "measurement Arrow record payload is invalid"
        ) from error


def _validate_selected_point_indices(
    records: Sequence[MeasurementRecord],
    *,
    expected_indices: Iterable[int],
) -> None:
    if tuple(record.point_index for record in records) != tuple(expected_indices):
        raise MeasurementArrowCodecError(
            "measurement Arrow row position does not match its point index"
        )


def _decode_record(row: dict[str, object], *, run_id: str) -> MeasurementRecord:
    return MeasurementRecord(
        run_id=run_id,
        logical_point_id=cast("str | None", row["logical_point_id"]),
        point_index=cast("int", row["point_index"]),
        coordinates=_decode_value_map(row["coordinates"]),
        observables=_decode_value_map(row["observables"]),
        acquisition_evidence=_decode_evidence_map(row["acquisition_evidence"]),
        metadata=_decode_json(row["metadata_json"]),
    )


def _decode_value_map(value: object) -> dict[str, MeasurementValue]:
    entries = cast("list[tuple[str, dict[str, object]]]", value)
    return {name: _decode_value(encoded) for name, encoded in entries}


def _decode_value(encoded: dict[str, object]) -> MeasurementValue:
    kind = cast("str", encoded["kind"])
    dtype = cast("MeasurementDType", encoded["dtype"])
    unit = cast("str | None", encoded["unit"])
    shape = cast("list[int | None]", encoded["shape"])
    metadata = _decode_json(encoded["metadata_json"])
    if kind == "unavailable":
        return MeasurementUnavailable.create(
            reason=cast("MeasurementUnavailableReason", encoded["reason"]),
            dtype=dtype,
            unit=unit,
            shape=shape,
            metadata=metadata,
        )

    storage_dtype = cast("MeasurementDType", encoded["storage_dtype"])
    values = _decode_typed_values(
        encoded[_value_column(storage_dtype)],
        dtype=storage_dtype,
    )
    if kind == "scalar":
        if len(values) != 1:
            raise MeasurementArrowCodecError(
                "measurement Arrow scalar must contain exactly one value"
            )
        selected = values[0]
        scalar = (
            ComplexComponents(real=selected.real, imag=selected.imag)
            if isinstance(selected, complex)
            else cast("MeasurementScalarData", selected)
        )
        return MeasurementScalar.create(
            value=scalar,
            dtype=dtype,
            unit=unit,
            metadata=metadata,
        )
    if kind != "array" or any(extent is None for extent in shape):
        raise MeasurementArrowCodecError("measurement Arrow value kind is invalid")
    concrete_shape = tuple(cast("int", extent) for extent in shape)
    array = np.asarray(values, dtype=_numpy_dtype(dtype)).reshape(concrete_shape)
    return MeasurementArray.create(
        shape=concrete_shape,
        values=array,
        dtype=dtype,
        unit=unit,
        metadata=metadata,
    )


def _decode_typed_values(value: object, *, dtype: MeasurementDType) -> list[object]:
    if not isinstance(value, list):
        raise MeasurementArrowCodecError(
            "measurement Arrow available value payload is missing"
        )
    values = cast("list[object]", value)
    if dtype != "complex128":
        return values
    return [
        complex(
            cast("dict[str, float]", item)["real"],
            cast("dict[str, float]", item)["imag"],
        )
        for item in values
    ]


def _numpy_dtype(dtype: MeasurementDType) -> np.dtype[np.generic]:
    if dtype == "string":
        return np.dtype(np.str_)
    return np.dtype(dtype)


def _decode_evidence_map(value: object) -> dict[str, InstrumentAcquisitionEvidence]:
    entries = cast("list[tuple[str, dict[str, object]]]", value)
    return {
        name: InstrumentAcquisitionEvidence(
            command_id=cast("str", encoded["command_id"]),
            instrument_id=cast("str", encoded["instrument_id"]),
            interface_id=cast("str", encoded["interface_id"]),
            component_path=tuple(cast("list[str]", encoded["component_path"])),
            acquisition_id=cast("str", encoded["acquisition_id"]),
            result_id=cast("str", encoded["result_id"]),
            started_at=datetime.fromisoformat(cast("str", encoded["started_at"])),
            completed_at=datetime.fromisoformat(cast("str", encoded["completed_at"])),
        )
        for name, encoded in entries
    }


def _encode_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def _decode_json(value: object) -> JsonMetadata:
    if not isinstance(value, bytes):
        raise MeasurementArrowCodecError("measurement Arrow metadata is invalid")
    try:
        decoded = cast("object", json.loads(value))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise MeasurementArrowCodecError(
            "measurement Arrow metadata is invalid"
        ) from error
    try:
        return validate_json_metadata(decoded)
    except ValueError as error:
        raise MeasurementArrowCodecError(
            "measurement Arrow metadata must be an object"
        ) from error


__all__ = [
    "MEASUREMENT_APPEND_ARROW_FORMAT",
    "MeasurementArrowCodecError",
    "decode_measurement_append",
    "decode_measurement_record_indices",
    "decode_measurement_record_slice",
    "encode_measurement_append",
]
