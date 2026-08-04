# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pyarrow as pa
import pytest

from scopecat.adapters.sqlite.measurement_arrow import (
    MEASUREMENT_APPEND_ARROW_FORMAT,
    MeasurementArrowCodecError,
    decode_measurement_append,
    decode_measurement_record_indices,
    decode_measurement_record_slice,
    encode_measurement_append,
)
from scopecat.records.measurement import (
    ComplexComponents,
    InstrumentAcquisitionEvidence,
    MeasurementArray,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
)
from scopecat.records.measurement_recording import MeasurementDatasetAppend


def _append() -> MeasurementDatasetAppend:
    run_id = "run-arrow"
    evidence = InstrumentAcquisitionEvidence(
        command_id="collect-signal",
        instrument_id="scope",
        interface_id="test.waveform/v1",
        component_path=("channel", "1"),
        acquisition_id="acquisition-0",
        result_id="signal",
        started_at=datetime(
            2026,
            8,
            4,
            9,
            tzinfo=timezone(timedelta(hours=8)),
        ),
        completed_at=datetime(
            2026,
            8,
            4,
            9,
            0,
            1,
            tzinfo=timezone(timedelta(hours=8)),
        ),
    )
    record = MeasurementRecord(
        run_id=run_id,
        logical_point_id="point-0",
        point_index=0,
        coordinates={
            "shot": MeasurementScalar.create(dtype="int64", value=2),
        },
        observables={
            # The scalar union retains the input Python type independently of
            # the declared measurement dtype; the durable codec must do so too.
            "estimate": MeasurementScalar.create(dtype="float64", value=1),
            "iq": MeasurementScalar.create(
                dtype="complex128",
                value=ComplexComponents(real=0.25, imag=-0.5),
            ),
            "trace": MeasurementArray.create(
                dtype="float64",
                unit="V",
                shape=(2, 2),
                values=np.array([[1.0, 2.0], [3.0, 4.0]]),
                metadata={"calibrated": True},
            ),
            "counts": MeasurementArray.create(
                dtype="int64",
                shape=(2,),
                values=[3, 5],
            ),
            "mask": MeasurementArray.create(
                dtype="bool",
                shape=(2,),
                values=[True, False],
            ),
            "labels": MeasurementArray.create(
                dtype="string",
                shape=(2,),
                values=["准备", "done"],
            ),
            "complex_trace": MeasurementArray.create(
                dtype="complex128",
                unit="ratio",
                shape=(2,),
                values=np.array([1 + 2j, 3 - 4j]),
            ),
            "missing": MeasurementUnavailable.create(
                reason="overload",
                dtype="float64",
                unit="V",
                shape=(None,),
                metadata={"status_register": 4},
            ),
        },
        acquisition_evidence={"trace": evidence},
        metadata={"note": "Arrow IPC", "nested": {"revision": 1}},
    )
    return MeasurementDatasetAppend(
        run_id=run_id,
        header_content_hash="header-hash",
        start_index=0,
        records=(record,),
    )


def test_measurement_append_round_trips_as_typed_arrow_ipc() -> None:
    append = _append()

    content = encode_measurement_append(append)
    restored = decode_measurement_append(content)

    assert content.startswith(b"ARROW1")
    assert encode_measurement_append(append) == content
    assert restored == append
    assert restored.operation_id == append.operation_id
    assert restored.content_hash == append.content_hash
    trace = restored.records[0].observables["trace"]
    assert isinstance(trace, MeasurementArray)
    assert trace.values.dtype == np.dtype(np.float64)
    assert trace.values.flags.c_contiguous
    assert not trace.values.flags.writeable
    complex_trace = restored.records[0].observables["complex_trace"]
    assert isinstance(complex_trace, MeasurementArray)
    np.testing.assert_array_equal(
        complex_trace.values,
        np.array([1 + 2j, 3 - 4j], dtype=np.complex128),
    )

    reader = pa.ipc.open_file(pa.BufferReader(content))
    assert reader.num_record_batches == 1
    assert reader.schema.metadata[b"scopecat.format"] == (
        MEASUREMENT_APPEND_ARROW_FORMAT.encode()
    )
    assert reader.schema.metadata[b"scopecat.content_hash"] == (
        append.content_hash.encode()
    )
    assert reader.schema.field("observables").type.item_type.field(
        "complex128_values"
    ).type.value_type == pa.struct(
        [
            pa.field("real", pa.float64(), nullable=False),
            pa.field("imag", pa.float64(), nullable=False),
        ]
    )


def test_measurement_arrow_selection_decodes_only_requested_rows() -> None:
    first = _append()
    template = first.records[0]
    append = first.model_copy(
        update={
            "records": tuple(
                template.model_copy(
                    update={
                        "logical_point_id": f"point-{index}",
                        "point_index": index,
                    }
                )
                for index in range(3)
            )
        }
    )
    content = encode_measurement_append(append)

    page = decode_measurement_record_slice(content, offset=1, length=2)
    selected = decode_measurement_record_indices(content, (2, 0))

    assert [record.point_index for record in page] == [1, 2]
    assert [record.point_index for record in selected] == [2, 0]


def test_measurement_arrow_encoding_is_independent_of_mapping_insertion_order() -> None:
    append = _append()
    record = append.records[0]
    reordered = record.model_copy(
        update={
            "observables": dict(reversed(tuple(record.observables.items()))),
        }
    )
    reordered_append = append.model_copy(update={"records": (reordered,)})

    assert reordered_append.content_hash == append.content_hash
    assert encode_measurement_append(reordered_append) == encode_measurement_append(
        append
    )


def test_measurement_arrow_rejects_non_ipc_payloads() -> None:
    with pytest.raises(MeasurementArrowCodecError, match="invalid measurement Arrow"):
        decode_measurement_append(b'{"records": []}')
