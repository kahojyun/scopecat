# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownParameterType=false, reportUnknownVariableType=false
"""Shared schema-driven Arrow IPC codec for measurement recording batches."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import cast

import numpy as np
import pyarrow as pa

from scopecat.kernel.content_identity import model_wire_content_hash
from scopecat.kernel.frozen import thaw_json_value
from scopecat.measurements.arrow_values import (
    measurement_arrow_value_type,
    measurement_values_to_arrow_array,
)
from scopecat.program.measurement_types import MeasurementDType
from scopecat.records.measurement import (
    MeasurementAcquisitionEvidenceCatalog,
    MeasurementArray,
    MeasurementArrayAvailability,
    MeasurementArrayUnavailableGroup,
    MeasurementDatasetSchema,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementScalarData,
    MeasurementSegmentedArray,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
    MeasurementValue,
    MeasurementVariable,
)
from scopecat.records.measurement_recording import MeasurementDatasetAppend
from scopecat.records.metadata import JsonMetadata, validate_json_metadata

MEASUREMENT_APPEND_ARROW_FORMAT = "scopecat.measurement_append.arrow.v9"

_FORMAT_KEY = b"scopecat.format"
_RUN_ID_KEY = b"scopecat.run_id"
_HEADER_CONTENT_HASH_KEY = b"scopecat.header_content_hash"
_DATASET_SCHEMA_HASH_KEY = b"scopecat.dataset_schema_hash"
_START_INDEX_KEY = b"scopecat.start_index"
_OPERATION_ID_KEY = b"scopecat.operation_id"
_CONTENT_HASH_KEY = b"scopecat.content_hash"
_RECORD_COUNT_KEY = b"scopecat.record_count"
_VARIABLE_ROLE_KEY = b"scopecat.variable_role"
_VARIABLE_DTYPE_KEY = b"scopecat.variable_dtype"
_VARIABLE_KIND_KEY = b"scopecat.variable_kind"
_VARIABLE_UNIT_KEY = b"scopecat.variable_unit"

_LOGICAL_POINT_ID_COLUMN = "__scopecat.logical_point_id"
_POINT_INDEX_COLUMN = "__scopecat.point_index"
_RECORD_METADATA_COLUMN = "__scopecat.record_metadata"
_RECORD_EVIDENCE_COLUMN = "__scopecat.acquisition_evidence"

_SHAPE_TYPE = pa.large_binary()
_EVIDENCE_TYPE = pa.large_binary()


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


def encode_measurement_append(
    append: MeasurementDatasetAppend,
    dataset_schema: MeasurementDatasetSchema,
    *,
    dataset_schema_hash: str | None = None,
) -> bytes:
    """Encode one append using columns derived from its registered schema."""

    try:
        metadata = {
            _FORMAT_KEY: MEASUREMENT_APPEND_ARROW_FORMAT.encode(),
            _RUN_ID_KEY: append.run_id.encode(),
            _HEADER_CONTENT_HASH_KEY: append.header_content_hash.encode(),
            _DATASET_SCHEMA_HASH_KEY: (
                dataset_schema_hash or measurement_dataset_schema_hash(dataset_schema)
            ).encode(),
            _START_INDEX_KEY: str(append.start_index).encode(),
            _OPERATION_ID_KEY: append.operation_id.encode(),
            _CONTENT_HASH_KEY: append.content_hash.encode(),
            _RECORD_COUNT_KEY: str(len(append.records)).encode(),
        }
        record_schema = _record_schema(dataset_schema).with_metadata(metadata)
        columns = _encode_columns(append.records, dataset_schema=dataset_schema)
        batch = pa.RecordBatch.from_arrays(columns, schema=record_schema)
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


def decode_measurement_append(
    content: bytes,
    dataset_schema: MeasurementDatasetSchema,
    *,
    dataset_schema_hash: str | None = None,
) -> MeasurementDatasetAppend:
    """Decode a complete append and verify its embedded durable identity."""

    batch, identity = _read_batch(
        content,
        dataset_schema=dataset_schema,
        dataset_schema_hash=dataset_schema_hash,
    )
    records = _decode_records(
        batch,
        run_id=identity.run_id,
        dataset_schema=dataset_schema,
    )
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
    dataset_schema: MeasurementDatasetSchema,
    *,
    offset: int,
    length: int,
    variable_ids: Sequence[str] | None = None,
    dataset_schema_hash: str | None = None,
) -> tuple[MeasurementRecord, ...]:
    """Decode a contiguous row and variable projection from one chunk."""

    batch, identity = _read_batch(
        content,
        dataset_schema=dataset_schema,
        dataset_schema_hash=dataset_schema_hash,
    )
    if offset < 0 or length < 0 or offset + length > batch.num_rows:
        raise MeasurementArrowCodecError("measurement Arrow slice is out of bounds")
    records = _decode_records(
        batch.slice(offset, length),
        run_id=identity.run_id,
        dataset_schema=dataset_schema,
        variable_ids=variable_ids,
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
    dataset_schema: MeasurementDatasetSchema,
    indices: Sequence[int],
    *,
    variable_ids: Sequence[str] | None = None,
    dataset_schema_hash: str | None = None,
) -> tuple[MeasurementRecord, ...]:
    """Decode selected rows and variables in caller order from one chunk."""

    batch, identity = _read_batch(
        content,
        dataset_schema=dataset_schema,
        dataset_schema_hash=dataset_schema_hash,
    )
    selected = tuple(indices)
    if any(index < 0 or index >= batch.num_rows for index in selected):
        raise MeasurementArrowCodecError(
            "measurement Arrow row selection is out of bounds"
        )
    if not selected:
        _selected_variables(dataset_schema, variable_ids)
        return ()
    taken = batch.take(pa.array(selected, type=pa.int64()))
    records = _decode_records(
        taken,
        run_id=identity.run_id,
        dataset_schema=dataset_schema,
        variable_ids=variable_ids,
    )
    _validate_selected_point_indices(
        records,
        expected_indices=(identity.start_index + index for index in selected),
    )
    return records


def _record_schema(dataset_schema: MeasurementDatasetSchema) -> pa.Schema:
    fields = [
        pa.field(_LOGICAL_POINT_ID_COLUMN, pa.string()),
        pa.field(_POINT_INDEX_COLUMN, pa.int64(), nullable=False),
        pa.field(_RECORD_METADATA_COLUMN, pa.large_binary(), nullable=False),
        pa.field(_RECORD_EVIDENCE_COLUMN, _EVIDENCE_TYPE, nullable=False),
    ]
    dimension_sizes = {
        dimension.id: dimension.size for dimension in dataset_schema.dimensions
    }
    for variable in dataset_schema.variables:
        fields.extend(
            [
                pa.field(
                    _value_column(variable.id),
                    measurement_arrow_value_type(
                        variable.dtype,
                        _variable_shape(
                            variable,
                            dimension_sizes=dimension_sizes,
                        ),
                        item_nullable=True,
                    ),
                    metadata=_variable_field_metadata(variable),
                ),
                pa.field(_reason_column(variable.id), pa.string()),
                pa.field(_shape_column(variable.id), _SHAPE_TYPE),
                pa.field(
                    _availability_column(variable.id),
                    pa.large_binary(),
                    nullable=False,
                ),
                pa.field(
                    _metadata_column(variable.id),
                    pa.large_binary(),
                    nullable=False,
                ),
            ]
        )
    return pa.schema(fields)


def _variable_field_metadata(
    variable: MeasurementVariable,
) -> Mapping[bytes, bytes]:
    metadata = {
        _VARIABLE_ROLE_KEY: variable.role.encode(),
        _VARIABLE_DTYPE_KEY: variable.dtype.encode(),
        _VARIABLE_KIND_KEY: (b"scalar" if len(variable.dims) == 1 else b"array"),
    }
    if variable.unit is not None:
        metadata[_VARIABLE_UNIT_KEY] = variable.unit.encode()
    return metadata


def _variable_shape(
    variable: MeasurementVariable,
    *,
    dimension_sizes: Mapping[str, int | None],
) -> tuple[int | None, ...]:
    return tuple(dimension_sizes[dimension_id] for dimension_id in variable.dims[1:])


def _encode_columns(
    records: Sequence[MeasurementRecord],
    *,
    dataset_schema: MeasurementDatasetSchema,
) -> list[pa.Array]:
    _validate_record_variable_sets(records, dataset_schema=dataset_schema)
    columns: list[pa.Array] = [
        pa.array(
            [record.logical_point_id for record in records],
            type=pa.string(),
        ),
        pa.array(
            np.fromiter(
                (record.point_index for record in records),
                dtype=np.int64,
                count=len(records),
            ),
            type=pa.int64(),
        ),
        pa.array(
            [_encode_json(record.metadata) for record in records],
            type=pa.large_binary(),
        ),
        pa.array(
            [
                _encode_json(record.acquisition_evidence.model_dump(mode="json"))
                for record in records
            ],
            type=_EVIDENCE_TYPE,
        ),
    ]
    dimension_sizes = {
        dimension.id: dimension.size for dimension in dataset_schema.dimensions
    }
    for variable in dataset_schema.variables:
        values = [_record_value(record, variable=variable) for record in records]
        for value in values:
            _validate_value_contract(
                value,
                variable=variable,
                dimension_sizes=dimension_sizes,
            )
        columns.extend(
            [
                measurement_values_to_arrow_array(
                    values,
                    dtype=variable.dtype,
                    shape=_variable_shape(
                        variable,
                        dimension_sizes=dimension_sizes,
                    ),
                    item_nullable=True,
                ),
                pa.array(
                    [
                        value.reason
                        if isinstance(value, MeasurementUnavailable)
                        else None
                        for value in values
                    ],
                    type=pa.string(),
                ),
                pa.array(
                    [
                        _encoded_shape(
                            value,
                            variable=variable,
                            dimension_sizes=dimension_sizes,
                        )
                        for value in values
                    ],
                    type=_SHAPE_TYPE,
                ),
                pa.array(
                    [_encode_availability(value) for value in values],
                    type=pa.large_binary(),
                ),
                pa.array(
                    [_encode_json(value.metadata) for value in values],
                    type=pa.large_binary(),
                ),
            ]
        )
    return columns


def _validate_record_variable_sets(
    records: Sequence[MeasurementRecord],
    *,
    dataset_schema: MeasurementDatasetSchema,
) -> None:
    expected_coordinates = {
        variable.id
        for variable in dataset_schema.variables
        if variable.role == "coordinate"
    }
    expected_observables = {
        variable.id
        for variable in dataset_schema.variables
        if variable.role == "observable"
    }
    for record in records:
        if set(record.coordinates) != expected_coordinates:
            raise MeasurementArrowCodecError(
                "measurement record coordinates do not match its registered schema"
            )
        if set(record.observables) != expected_observables:
            raise MeasurementArrowCodecError(
                "measurement record observables do not match its registered schema"
            )


def _record_value(
    record: MeasurementRecord,
    *,
    variable: MeasurementVariable,
) -> MeasurementValue:
    values = record.coordinates if variable.role == "coordinate" else record.observables
    return values[variable.id]


def _validate_value_contract(
    value: MeasurementValue,
    *,
    variable: MeasurementVariable,
    dimension_sizes: Mapping[str, int | None],
) -> None:
    expected_shape = _variable_shape(
        variable,
        dimension_sizes=dimension_sizes,
    )
    actual_shape: tuple[int | None, ...]
    if isinstance(
        value,
        MeasurementArray | MeasurementSegmentedArray | MeasurementUnavailable,
    ):
        actual_shape = tuple(value.shape)
    else:
        actual_shape = ()
    shape_matches = len(actual_shape) == len(expected_shape) and all(
        expected is None or expected == actual
        for expected, actual in zip(expected_shape, actual_shape, strict=True)
    )
    if (
        value.dtype != variable.dtype
        or value.unit != variable.unit
        or not shape_matches
    ):
        raise MeasurementArrowCodecError(
            f"measurement variable {variable.id} does not match its registered "
            f"schema: dtype {value.dtype!r}/{variable.dtype!r}, unit "
            f"{value.unit!r}/{variable.unit!r}, shape "
            f"{actual_shape!r}/{expected_shape!r}"
        )


def _encoded_shape(
    value: MeasurementValue,
    *,
    variable: MeasurementVariable,
    dimension_sizes: Mapping[str, int | None],
) -> bytes | None:
    if isinstance(value, MeasurementUnavailable):
        return _encode_json({"shape": value.shape})
    if isinstance(value, MeasurementSegmentedArray):
        return _encode_json(
            {
                "segments": tuple(
                    (
                        {"shape": segment.shape}
                        if isinstance(segment, MeasurementUnavailable)
                        or 0 in segment.shape
                        else None
                    )
                    for segment in value.segments
                )
            }
        )
    if isinstance(value, MeasurementArray) and any(
        dimension_sizes[dimension_id] is None for dimension_id in variable.dims[1:]
    ):
        return _encode_json({"shape": value.shape})
    return None


def _encode_availability(value: MeasurementValue) -> bytes:
    if isinstance(value, MeasurementSegmentedArray):
        return _encode_json(
            {
                "segments": tuple(
                    (
                        {
                            "kind": "unavailable",
                            "reason": segment.reason,
                            "metadata": segment.metadata,
                        }
                        if isinstance(segment, MeasurementUnavailable)
                        else {
                            "kind": "array",
                            "metadata": segment.metadata,
                            "unavailable": tuple(
                                group.model_dump(mode="json")
                                for group in (
                                    ()
                                    if segment.availability is None
                                    else segment.availability.unavailable
                                )
                            ),
                        }
                    )
                    for segment in value.segments
                )
            }
        )
    if not isinstance(value, MeasurementArray) or value.availability is None:
        return _encode_json({})
    return _encode_json(
        {
            "unavailable": [
                group.model_dump(mode="json")
                for group in value.availability.unavailable
            ]
        }
    )


def _read_batch(
    content: bytes,
    *,
    dataset_schema: MeasurementDatasetSchema,
    dataset_schema_hash: str | None,
) -> tuple[pa.RecordBatch, _AppendIdentity]:
    try:
        reader = pa.ipc.open_file(pa.BufferReader(content))
        if reader.num_record_batches != 1:
            raise MeasurementArrowCodecError(
                "measurement Arrow chunk must contain exactly one record batch"
            )
        schema = reader.schema
        if not schema.remove_metadata().equals(_record_schema(dataset_schema)):
            raise MeasurementArrowCodecError(
                "measurement Arrow chunk has an unexpected record schema"
            )
        identity = _decode_identity(
            schema.metadata,
            dataset_schema=dataset_schema,
            dataset_schema_hash=dataset_schema_hash,
        )
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


def _decode_identity(
    metadata: Mapping[bytes, bytes] | None,
    *,
    dataset_schema: MeasurementDatasetSchema,
    dataset_schema_hash: str | None,
) -> _AppendIdentity:
    if metadata is None:
        raise MeasurementArrowCodecError("measurement Arrow metadata is missing")
    try:
        format_version = metadata[_FORMAT_KEY].decode()
        schema_hash = metadata[_DATASET_SCHEMA_HASH_KEY].decode()
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
    expected_schema_hash = dataset_schema_hash or measurement_dataset_schema_hash(
        dataset_schema
    )
    if schema_hash != expected_schema_hash:
        raise MeasurementArrowCodecError(
            "measurement Arrow chunk does not match its registered dataset schema"
        )
    if identity.start_index < 0 or identity.record_count < 0:
        raise MeasurementArrowCodecError(
            "measurement Arrow identity metadata cannot be negative"
        )
    return identity


def measurement_dataset_schema_hash(
    dataset_schema: MeasurementDatasetSchema,
) -> str:
    return model_wire_content_hash(dataset_schema)


def _decode_records(
    batch: pa.RecordBatch,
    *,
    run_id: str,
    dataset_schema: MeasurementDatasetSchema,
    variable_ids: Sequence[str] | None = None,
) -> tuple[MeasurementRecord, ...]:
    variables = _selected_variables(dataset_schema, variable_ids)
    try:
        logical_point_ids = batch.column(_LOGICAL_POINT_ID_COLUMN)
        point_indices = batch.column(_POINT_INDEX_COLUMN)
        record_metadata = batch.column(_RECORD_METADATA_COLUMN)
        evidence_catalogs = tuple(
            MeasurementAcquisitionEvidenceCatalog.model_validate(
                _decode_json(value.as_py())
            ).select([variable.id for variable in variables])
            for value in batch.column(_RECORD_EVIDENCE_COLUMN)
        )
        variable_columns = {
            variable.id: (
                batch.column(_value_column(variable.id)),
                batch.column(_reason_column(variable.id)),
                batch.column(_shape_column(variable.id)),
                batch.column(_availability_column(variable.id)),
                batch.column(_metadata_column(variable.id)),
            )
            for variable in variables
        }
        records: list[MeasurementRecord] = []
        for row_index in range(batch.num_rows):
            coordinates: dict[str, MeasurementValue] = {}
            observables: dict[str, MeasurementValue] = {}
            for variable in variables:
                (
                    value_column,
                    reason_column,
                    shape_column,
                    availability_column,
                    metadata_column,
                ) = variable_columns[variable.id]
                value = _decode_value(
                    value_column[row_index],
                    reason=reason_column[row_index].as_py(),
                    encoded_shape=shape_column[row_index].as_py(),
                    encoded_availability=availability_column[row_index].as_py(),
                    encoded_metadata=metadata_column[row_index].as_py(),
                    variable=variable,
                    dataset_schema=dataset_schema,
                )
                target = coordinates if variable.role == "coordinate" else observables
                target[variable.id] = value
            records.append(
                MeasurementRecord(
                    run_id=run_id,
                    logical_point_id=logical_point_ids[row_index].as_py(),
                    point_index=point_indices[row_index].as_py(),
                    coordinates=coordinates,
                    observables=observables,
                    acquisition_evidence=evidence_catalogs[row_index],
                    metadata=_decode_json(record_metadata[row_index].as_py()),
                )
            )
        return tuple(records)
    except MeasurementArrowCodecError:
        raise
    except (KeyError, TypeError, ValueError, pa.ArrowException) as error:
        raise MeasurementArrowCodecError(
            "measurement Arrow record payload is invalid"
        ) from error


def _selected_variables(
    dataset_schema: MeasurementDatasetSchema,
    variable_ids: Sequence[str] | None,
) -> tuple[MeasurementVariable, ...]:
    if variable_ids is None:
        return tuple(dataset_schema.variables)
    selected = set(variable_ids)
    available = {variable.id for variable in dataset_schema.variables}
    unknown = selected - available
    if unknown:
        raise MeasurementArrowCodecError(
            "unknown measurement Arrow variables: " + ", ".join(sorted(unknown))
        )
    return tuple(
        variable for variable in dataset_schema.variables if variable.id in selected
    )


def _decode_value(
    encoded_value: pa.Scalar,
    *,
    reason: object,
    encoded_shape: object,
    encoded_availability: object,
    encoded_metadata: object,
    variable: MeasurementVariable,
    dataset_schema: MeasurementDatasetSchema,
) -> MeasurementValue:
    metadata = _decode_json(encoded_metadata)
    availability_groups = _decode_availability(encoded_availability)
    if reason is not None:
        if (
            encoded_value.is_valid
            or not isinstance(encoded_shape, bytes)
            or availability_groups
        ):
            raise MeasurementArrowCodecError(
                "measurement Arrow unavailable sidecars are inconsistent"
            )
        decoded_shape = _decode_json(encoded_shape).get("shape")
        if not isinstance(decoded_shape, list) or any(
            extent is not None and not isinstance(extent, int)
            for extent in decoded_shape
        ):
            raise MeasurementArrowCodecError(
                "measurement Arrow unavailable shape sidecar is invalid"
            )
        return MeasurementUnavailable.create(
            reason=cast("MeasurementUnavailableReason", reason),
            dtype=variable.dtype,
            unit=variable.unit,
            shape=cast("list[int | None]", decoded_shape),
            metadata=metadata,
        )
    if not encoded_value.is_valid:
        raise MeasurementArrowCodecError(
            "measurement Arrow available value payload is missing"
        )
    if len(variable.dims) == 1:
        if encoded_shape is not None or availability_groups:
            raise MeasurementArrowCodecError(
                "measurement Arrow scalar has an unexpected shape sidecar"
            )
        return MeasurementScalar.create(
            value=cast(
                "MeasurementScalarData",
                _decode_arrow_scalar(encoded_value.as_py(), dtype=variable.dtype),
            ),
            dtype=variable.dtype,
            unit=variable.unit,
            metadata=metadata,
        )
    segment_shape_specs = _decode_segment_shape_specs(encoded_shape)
    if segment_shape_specs is not None:
        if availability_groups:
            raise MeasurementArrowCodecError(
                "measurement Arrow segmented diagnostics are inconsistent"
            )
        return _decode_segmented_array(
            encoded_value,
            shape_specs=segment_shape_specs,
            encoded_availability=encoded_availability,
            variable=variable,
            metadata=metadata,
        )
    shape = _decoded_array_shape(
        encoded_shape,
        variable=variable,
        dataset_schema=dataset_schema,
    )
    array, valid = _decode_array_values(encoded_value, dtype=variable.dtype)
    array = array.reshape(shape)
    valid = valid.reshape(shape)
    if availability_groups:
        availability = MeasurementArrayAvailability(
            valid=valid,
            unavailable=availability_groups,
        )
    else:
        if not bool(np.all(valid)):
            raise MeasurementArrowCodecError(
                "measurement Arrow partial value diagnostics are missing"
            )
        availability = None
    return MeasurementArray.create(
        values=array,
        dtype=variable.dtype,
        unit=variable.unit,
        availability=availability,
        metadata=metadata,
    )


def _decode_availability(
    value: object,
) -> tuple[MeasurementArrayUnavailableGroup, ...]:
    decoded = _decode_json(value)
    raw_groups = decoded.get("unavailable", ())
    if not isinstance(raw_groups, list | tuple):
        raise MeasurementArrowCodecError(
            "measurement Arrow array availability is invalid"
        )
    return tuple(
        MeasurementArrayUnavailableGroup.model_validate(group) for group in raw_groups
    )


def _decode_segment_shape_specs(
    encoded_shape: object,
) -> tuple[tuple[int | None, ...] | None, ...] | None:
    if not isinstance(encoded_shape, bytes):
        return None
    decoded = _decode_json(encoded_shape)
    raw_segments = decoded.get("segments")
    if raw_segments is None:
        return None
    if not isinstance(raw_segments, list) or not raw_segments:
        raise MeasurementArrowCodecError(
            "measurement Arrow segmented shape sidecar is invalid"
        )
    selected: list[tuple[int | None, ...] | None] = []
    for raw_segment in raw_segments:
        if raw_segment is None:
            selected.append(None)
            continue
        if not isinstance(raw_segment, dict):
            raise MeasurementArrowCodecError(
                "measurement Arrow segmented shape sidecar is invalid"
            )
        raw_shape = raw_segment.get("shape")
        if not isinstance(raw_shape, list) or any(
            extent is not None and not isinstance(extent, int) for extent in raw_shape
        ):
            raise MeasurementArrowCodecError(
                "measurement Arrow segmented shape sidecar is invalid"
            )
        selected.append(tuple(cast("list[int | None]", raw_shape)))
    return tuple(selected)


def _decode_segmented_array(
    encoded_value: pa.Scalar,
    *,
    shape_specs: Sequence[tuple[int | None, ...] | None],
    encoded_availability: object,
    variable: MeasurementVariable,
    metadata: Mapping[str, object],
) -> MeasurementSegmentedArray:
    decoded = _decode_json(encoded_availability)
    raw_diagnostics = decoded.get("segments")
    if not isinstance(raw_diagnostics, list) or len(raw_diagnostics) != len(
        shape_specs
    ):
        raise MeasurementArrowCodecError(
            "measurement Arrow segmented diagnostics are invalid"
        )
    encoded_segments = cast(
        "pa.ListScalar | pa.FixedSizeListScalar", encoded_value
    ).values
    if len(encoded_segments) != len(shape_specs):
        raise MeasurementArrowCodecError(
            "measurement Arrow segmented cardinality is invalid"
        )
    local_rank = len(variable.dims) - 2
    segments: list[MeasurementArray | MeasurementUnavailable] = []
    for index, (shape_spec, raw_diagnostic) in enumerate(
        zip(shape_specs, raw_diagnostics, strict=True)
    ):
        if not isinstance(raw_diagnostic, dict):
            raise MeasurementArrowCodecError(
                "measurement Arrow segmented diagnostics are invalid"
            )
        segment_value = encoded_segments[index]
        kind = raw_diagnostic.get("kind")
        segment_metadata = raw_diagnostic.get("metadata")
        if not isinstance(segment_metadata, dict):
            raise MeasurementArrowCodecError(
                "measurement Arrow segmented metadata is invalid"
            )
        if kind == "unavailable":
            reason = raw_diagnostic.get("reason")
            if (
                segment_value.is_valid
                or shape_spec is None
                or not isinstance(reason, str)
            ):
                raise MeasurementArrowCodecError(
                    "measurement Arrow unavailable segment is inconsistent"
                )
            segments.append(
                MeasurementUnavailable.create(
                    reason=cast("MeasurementUnavailableReason", reason),
                    dtype=variable.dtype,
                    unit=variable.unit,
                    shape=shape_spec,
                    metadata=segment_metadata,
                )
            )
            continue
        if kind != "array" or not segment_value.is_valid:
            raise MeasurementArrowCodecError(
                "measurement Arrow available segment is inconsistent"
            )
        shape = (
            _nested_array_shape(segment_value.as_py(), rank=local_rank)
            if shape_spec is None
            else shape_spec
        )
        if any(extent is None for extent in shape):
            raise MeasurementArrowCodecError(
                "measurement Arrow available segment shape is not concrete"
            )
        concrete_shape = cast("tuple[int, ...]", shape)
        array, valid = _decode_array_values(segment_value, dtype=variable.dtype)
        try:
            array = array.reshape(concrete_shape)
            valid = valid.reshape(concrete_shape)
        except ValueError as error:
            raise MeasurementArrowCodecError(
                "measurement Arrow available segment shape is invalid"
            ) from error
        raw_groups = raw_diagnostic.get("unavailable")
        if not isinstance(raw_groups, list):
            raise MeasurementArrowCodecError(
                "measurement Arrow segmented diagnostics are invalid"
            )
        groups = tuple(
            MeasurementArrayUnavailableGroup.model_validate(group)
            for group in raw_groups
        )
        if groups:
            availability = MeasurementArrayAvailability(
                valid=valid,
                unavailable=groups,
            )
        else:
            if not bool(np.all(valid)):
                raise MeasurementArrowCodecError(
                    "measurement Arrow partial segment diagnostics are missing"
                )
            availability = None
        segments.append(
            MeasurementArray.create(
                values=array,
                dtype=variable.dtype,
                unit=variable.unit,
                availability=availability,
                metadata=segment_metadata,
            )
        )
    return MeasurementSegmentedArray.create(
        segments=segments,
        dtype=variable.dtype,
        unit=variable.unit,
        metadata=metadata,
    )


def _nested_array_shape(value: object, *, rank: int) -> tuple[int, ...]:
    if rank <= 0 or not isinstance(value, list):
        raise MeasurementArrowCodecError(
            "measurement Arrow segmented value has invalid local rank"
        )
    selected = cast("list[object]", value)
    if rank == 1:
        return (len(selected),)
    if not selected:
        raise MeasurementArrowCodecError(
            "measurement Arrow empty segment requires an explicit shape"
        )
    child_shapes = {_nested_array_shape(child, rank=rank - 1) for child in selected}
    if len(child_shapes) != 1:
        raise MeasurementArrowCodecError(
            "measurement Arrow segmented value is not rectangular"
        )
    return (len(selected), *next(iter(child_shapes)))


def _decoded_array_shape(
    encoded_shape: object,
    *,
    variable: MeasurementVariable,
    dataset_schema: MeasurementDatasetSchema,
) -> tuple[int, ...]:
    dimension_sizes = {
        dimension.id: dimension.size for dimension in dataset_schema.dimensions
    }
    expected = tuple(
        dimension_sizes[dimension_id] for dimension_id in variable.dims[1:]
    )
    if any(extent is None for extent in expected):
        if not isinstance(encoded_shape, bytes):
            raise MeasurementArrowCodecError(
                "measurement Arrow ragged value shape sidecar is missing"
            )
        decoded = _decode_json(encoded_shape)
        shape = decoded.get("shape")
        if not isinstance(shape, list) or any(
            not isinstance(extent, int) for extent in shape
        ):
            raise MeasurementArrowCodecError(
                "measurement Arrow ragged value shape sidecar is invalid"
            )
        return tuple(cast("list[int]", shape))
    if encoded_shape is not None:
        raise MeasurementArrowCodecError(
            "measurement Arrow fixed value has an unexpected shape sidecar"
        )
    return tuple(cast("int", extent) for extent in expected)


def _decode_arrow_scalar(value: object, *, dtype: MeasurementDType) -> object:
    if dtype != "complex128":
        return value
    encoded = cast("Mapping[str, object]", value)
    return complex(
        cast("float", encoded["real"]),
        cast("float", encoded["imag"]),
    )


def _decode_array_values(
    value: pa.Scalar,
    *,
    dtype: MeasurementDType,
) -> tuple[
    np.ndarray[tuple[int], np.dtype[np.generic]],
    np.ndarray[tuple[int], np.dtype[np.bool_]],
]:
    selected = cast("pa.ListScalar | pa.FixedSizeListScalar", value).values
    while (
        pa.types.is_list(selected.type)
        or pa.types.is_large_list(selected.type)
        or pa.types.is_fixed_size_list(selected.type)
    ):
        selected = cast(
            "pa.ListArray | pa.LargeListArray | pa.FixedSizeListArray",
            selected,
        ).flatten()
    if dtype == "complex128":
        complex_values = cast("pa.StructArray", selected)
        real = complex_values.field("real").to_numpy(zero_copy_only=False)
        imag = complex_values.field("imag").to_numpy(zero_copy_only=False)
        values = np.asarray(real + 1j * imag, dtype=np.complex128)
    else:
        fill_value: str | bool | int
        if dtype == "string":
            fill_value = ""
        elif dtype == "bool":
            fill_value = False
        else:
            fill_value = 0
        values = np.asarray(
            selected.fill_null(fill_value).to_numpy(zero_copy_only=False),
            dtype=_numpy_dtype(dtype),
        )
    valid = np.asarray(
        selected.is_valid().to_numpy(zero_copy_only=False),
        dtype=np.bool_,
    )
    if not bool(np.all(valid)):
        values = values.copy()
        values[~valid] = 0 if dtype != "string" else ""
    return (
        values,
        valid,
    )


def _validate_selected_point_indices(
    records: Sequence[MeasurementRecord],
    *,
    expected_indices: Iterable[int],
) -> None:
    if tuple(record.point_index for record in records) != tuple(expected_indices):
        raise MeasurementArrowCodecError(
            "measurement Arrow row position does not match its point index"
        )


def _value_column(variable_id: str) -> str:
    return f"value:{variable_id}"


def _reason_column(variable_id: str) -> str:
    return f"unavailable_reason:{variable_id}"


def _shape_column(variable_id: str) -> str:
    return f"value_shape:{variable_id}"


def _availability_column(variable_id: str) -> str:
    return f"availability:{variable_id}"


def _metadata_column(variable_id: str) -> str:
    return f"metadata:{variable_id}"


def _numpy_dtype(dtype: MeasurementDType) -> np.dtype[np.generic]:
    if dtype == "string":
        return np.dtype(np.str_)
    return np.dtype(dtype)


def _encode_json(value: object) -> bytes:
    return json.dumps(
        thaw_json_value(value),
        allow_nan=False,
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
    "measurement_dataset_schema_hash",
]
