from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Literal, cast

import numpy as np
import pytest
from pydantic import ValidationError
from scopecat_testkit.measurement_models import signal_point_schema, signal_record
from scopecat_testkit.records import assert_model_round_trip

from scopecat.kernel.entity import EntityRef
from scopecat.records.measurement import (
    InstrumentAcquisitionEvidence,
    MeasurementAcquisitionEvidenceCatalog,
    MeasurementArray,
    MeasurementArrayAvailability,
    MeasurementArrayUnavailableGroup,
    MeasurementDataset,
    MeasurementDimension,
    MeasurementEntityIndex,
    MeasurementRecord,
    MeasurementScalar,
    MeasurementUnavailable,
    MeasurementUnavailableReason,
    MeasurementVariable,
)


def test_measurement_values_round_trip_through_one_record() -> None:
    evidence = InstrumentAcquisitionEvidence(
        command_id="collect-signal",
        instrument_id="readout",
        interface_id="test.scalar_signal/v1",
        acquisition_id="sample",
        result_id="signal",
        started_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 29, 10, 0, 1, tzinfo=UTC),
    )
    measurement = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={
            "shot": MeasurementScalar.create(dtype="int64", unit=None, value=0),
        },
        observables={
            "signal": MeasurementScalar.create(
                dtype="float64",
                unit="ratio",
                value=0.5,
            ),
            "raw_iq": MeasurementScalar.create(
                dtype="complex128",
                unit="ratio",
                value=complex(0.3, -0.4),
            ),
            "enabled": MeasurementScalar.create(dtype="bool", unit=None, value=True),
            "label": MeasurementScalar.create(dtype="string", unit=None, value="ready"),
            "samples": MeasurementArray.create(
                dtype="float64",
                unit="ratio",
                values=[0.1, 0.2, 0.3],
            ),
            "iq": MeasurementArray.create(
                dtype="complex128",
                unit="ratio",
                values=[[complex(0.1, -0.2), complex(0.3, -0.4)]],
            ),
            "probability": MeasurementArray.create(
                dtype="float64",
                unit="ratio",
                values=[0.25, 0.75],
            ),
        },
        acquisition_evidence=MeasurementAcquisitionEvidenceCatalog.create(
            {"signal": evidence}
        ),
    )

    restored = assert_model_round_trip(measurement)

    assert restored == measurement
    assert isinstance(restored.coordinates["shot"], MeasurementScalar)
    assert isinstance(restored.observables["signal"], MeasurementScalar)
    assert isinstance(restored.observables["raw_iq"], MeasurementScalar)
    assert type(restored.observables["raw_iq"].value) is complex
    assert restored.observables["raw_iq"].value == complex(0.3, -0.4)
    assert isinstance(restored.observables["samples"], MeasurementArray)
    assert isinstance(restored.observables["iq"], MeasurementArray)
    assert isinstance(restored.observables["probability"], MeasurementArray)
    assert restored.acquisition_evidence.for_variable("signal") == evidence


def test_measurement_array_owns_a_contiguous_read_only_numpy_copy() -> None:
    source = np.arange(6, dtype=np.float64).reshape(3, 2).T

    value = MeasurementArray.create(values=source)
    source[0, 0] = 99.0

    assert value.shape == (2, 3)
    assert value.values.dtype == np.dtype(np.float64)
    assert value.values.flags.c_contiguous
    assert not value.values.flags.writeable
    assert value.values[0, 0] == 0.0
    with pytest.raises(ValueError, match="read-only"):
        value.values[0, 0] = 1.0
    with pytest.raises(ValueError, match="WRITEABLE"):
        value.values.flags.writeable = True
    assert deepcopy(value) is value


def test_measurement_array_reuses_an_immutable_bytes_backed_array() -> None:
    content = np.arange(6, dtype=np.float64).tobytes()
    source = np.frombuffer(content, dtype=np.float64).reshape(2, 3)

    value = MeasurementArray.create(values=source)

    assert value.values is source
    assert not value.values.flags.writeable


def test_measurement_array_retains_sparse_partial_availability() -> None:
    availability = MeasurementArrayAvailability(
        valid=np.asarray([[True, False], [False, True]], dtype=np.bool_),
        unavailable=(
            MeasurementArrayUnavailableGroup(
                reason="missing",
                flat_indices=(1,),
                metadata={"channel": "q1"},
            ),
            MeasurementArrayUnavailableGroup(
                reason="invalid",
                flat_indices=(2,),
                metadata={"channel": "q0"},
            ),
        ),
    )
    value = MeasurementArray.create(
        dtype="complex128",
        unit="ratio",
        values=[[1 + 2j, 0j], [0j, 3 + 4j]],
        availability=availability,
    )

    restored = assert_model_round_trip(value)

    assert restored == value
    assert restored.availability is not None
    assert restored.availability.valid.tolist() == [[True, False], [False, True]]
    assert not restored.availability.valid.flags.writeable
    assert [group.reason for group in restored.availability.unavailable] == [
        "missing",
        "invalid",
    ]


def test_measurement_array_availability_requires_an_exact_incomplete_partition() -> (
    None
):
    with pytest.raises(ValueError, match="fully available"):
        MeasurementArrayAvailability.create(valid=[True, True])
    fully_unavailable = MeasurementArrayAvailability.create(valid=[False, False])
    assert fully_unavailable.valid.tolist() == [False, False]
    assert fully_unavailable.unavailable[0].flat_indices == (0, 1)
    with pytest.raises(ValidationError, match="exactly partition"):
        MeasurementArrayAvailability(
            valid=np.asarray([True, False, False], dtype=np.bool_),
            unavailable=(
                MeasurementArrayUnavailableGroup(
                    reason="missing",
                    flat_indices=(1,),
                ),
            ),
        )
    with pytest.raises(ValidationError, match="availability shape"):
        MeasurementArray.create(
            values=[1.0, 0.0],
            availability=MeasurementArrayAvailability.create(
                valid=[[True, False]],
            ),
        )


def test_measurement_snapshots_are_recursively_immutable() -> None:
    source_metadata = {"context": [{"operator": "alice"}]}
    record = MeasurementRecord(
        run_id="run-immutable",
        point_index=0,
        coordinates={},
        observables={
            "signal": MeasurementScalar.create(
                value=0.5,
                metadata=source_metadata,
            )
        },
        metadata=source_metadata,
    )
    source_metadata["context"][0]["operator"] = "changed"

    assert record.metadata == {"context": ({"operator": "alice"},)}
    with pytest.raises(TypeError, match="frozen mapping is immutable"):
        cast("dict[str, object]", record.observables)["other"] = (
            MeasurementScalar.create(value=1.0)
        )
    with pytest.raises(TypeError, match="frozen mapping is immutable"):
        nested = cast("tuple[object, ...]", record.metadata["context"])[0]
        cast("dict[str, object]", nested)["operator"] = "changed"

    renumbered = record.model_copy(update={"point_index": 1})
    assert renumbered.metadata == record.metadata
    updated = record.model_copy(update={"metadata": {"context": [{"operator": "bob"}]}})
    with pytest.raises(TypeError, match="frozen mapping is immutable"):
        cast("dict[str, object]", updated.metadata)["changed"] = True


def test_measurement_array_explicit_shape_remains_a_wire_contract() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        MeasurementArray.model_validate(
            {
                "kind": "array",
                "dtype": "float64",
                "values": [[1.0, 2.0]],
            }
        )
    with pytest.raises(ValidationError, match="does not match"):
        MeasurementArray.model_validate(
            {
                "kind": "array",
                "dtype": "float64",
                "shape": [3],
                "values": [1.0, 2.0],
            }
        )


def test_measurement_array_schema_exposes_recursive_typed_json_values() -> None:
    schema = MeasurementArray.model_json_schema(mode="serialization")

    assert schema["properties"]["values"] == {"$ref": "#/$defs/MeasurementArrayJson"}
    assert schema["$defs"]["MeasurementArrayJson"] == {
        "items": {"$ref": "#/$defs/MeasurementArrayJsonItem"},
        "type": "array",
    }
    item_options = schema["$defs"]["MeasurementArrayJsonItem"]["anyOf"]
    assert {option.get("type") for option in item_options} == {None, "array"}
    leaf_options = schema["$defs"]["MeasurementArrayJsonLeaf"]["anyOf"]
    assert {option.get("type") for option in leaf_options} == {
        None,
        "boolean",
        "integer",
        "number",
        "string",
    }
    assert schema["$defs"]["MeasurementComplexJson"] == {
        "additionalProperties": False,
        "properties": {
            "real": {"type": "number"},
            "imag": {"type": "number"},
        },
        "required": ["real", "imag"],
        "type": "object",
    }


def test_instrument_acquisition_evidence_requires_an_aware_ordered_interval() -> None:
    with pytest.raises(ValidationError, match="timezone info"):
        InstrumentAcquisitionEvidence(
            command_id="collect-signal",
            instrument_id="readout",
            interface_id="test.scalar_signal/v1",
            acquisition_id="sample",
            result_id="signal",
            started_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC).replace(tzinfo=None),
            completed_at=datetime(2026, 7, 29, 10, 0, 1, tzinfo=UTC),
        )
    with pytest.raises(ValidationError, match="must not precede"):
        InstrumentAcquisitionEvidence(
            command_id="collect-signal",
            instrument_id="readout",
            interface_id="test.scalar_signal/v1",
            acquisition_id="sample",
            result_id="signal",
            started_at=datetime(2026, 7, 29, 10, 0, 1, tzinfo=UTC),
            completed_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        )


def test_measurement_record_rejects_acquisition_evidence_for_unknown_variable() -> None:
    evidence = InstrumentAcquisitionEvidence(
        command_id="collect-signal",
        instrument_id="readout",
        interface_id="test.scalar_signal/v1",
        acquisition_id="sample",
        result_id="signal",
        started_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 29, 10, 0, 1, tzinfo=UTC),
    )
    with pytest.raises(ValidationError, match="unknown variables: signal"):
        MeasurementRecord(
            run_id="run-test",
            point_index=0,
            coordinates={},
            observables={},
            acquisition_evidence=MeasurementAcquisitionEvidenceCatalog.create(
                {"signal": evidence}
            ),
        )


def test_acquisition_catalog_factors_events_and_keeps_stable_content_refs() -> None:
    first = InstrumentAcquisitionEvidence(
        command_id="collect-iq",
        instrument_id="readout",
        interface_id="test.scalar_signal/v1",
        acquisition_id="sample",
        result_id="i",
        started_at=datetime(2026, 7, 29, 10, 0, tzinfo=UTC),
        completed_at=datetime(2026, 7, 29, 10, 0, 1, tzinfo=UTC),
    )
    second = first.model_copy(update={"result_id": "q"})

    catalog = MeasurementAcquisitionEvidenceCatalog.create({"i": first, "q": second})
    selected = catalog.select(("q",))

    assert len(catalog.events) == 1
    assert len(catalog.entries) == 2
    assert catalog.variable_refs["q"] == selected.variable_refs["q"]
    assert selected.events == catalog.events
    assert selected.for_variable("q") == second


def test_measurement_record_discriminator_restores_value_models() -> None:
    record = MeasurementRecord.model_validate(
        {
            "run_id": "run-test",
            "point_index": 0,
            "coordinates": {
                "label": {
                    "kind": "scalar",
                    "dtype": "string",
                    "unit": None,
                    "value": "first",
                }
            },
            "observables": {
                "iq": {
                    "kind": "array",
                    "dtype": "complex128",
                    "unit": "ratio",
                    "shape": [1],
                    "values": [{"real": 0.25, "imag": -0.5}],
                },
                "temperature": {
                    "kind": "unavailable",
                    "reason": "invalid",
                    "dtype": "float64",
                    "unit": "K",
                    "shape": [],
                    "metadata": {"status": "sensor fault"},
                },
            },
        }
    )

    assert isinstance(record.coordinates["label"], MeasurementScalar)
    iq = record.observables["iq"]
    assert isinstance(iq, MeasurementArray)
    assert iq.values.dtype == np.dtype(np.complex128)
    assert iq.values.tolist() == [complex(0.25, -0.5)]
    assert not iq.values.flags.writeable
    assert isinstance(record.observables["temperature"], MeasurementUnavailable)


def test_measurement_record_wire_requires_value_discriminators() -> None:
    schema = MeasurementRecord.model_json_schema()

    assert "kind" in schema["$defs"]["MeasurementScalar"]["required"]
    assert "kind" in schema["$defs"]["MeasurementArray"]["required"]
    assert set(schema["$defs"]["MeasurementUnavailable"]["required"]) == {
        "kind",
        "reason",
        "dtype",
        "unit",
        "shape",
        "metadata",
    }
    assert MeasurementScalar.create(value=1.0).kind == "scalar"
    assert MeasurementArray.create(values=[1.0]).kind == "array"
    assert (
        MeasurementUnavailable.create(
            reason="missing",
            dtype="float64",
            unit=None,
            shape=(),
            metadata={},
        ).kind
        == "unavailable"
    )
    with pytest.raises(ValidationError, match="Field required"):
        MeasurementScalar.model_validate({"value": 1.0})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MeasurementScalar.model_validate(
            {"kind": "scalar", "value": 1.0, "unexpected": True}
        )
    with pytest.raises(ValidationError, match="union_tag_not_found"):
        MeasurementRecord.model_validate(
            {
                "run_id": "run-test",
                "point_index": 0,
                "coordinates": {},
                "observables": {
                    "signal": {
                        "dtype": "float64",
                        "unit": "ratio",
                        "value": 0.5,
                    }
                },
            }
        )


@pytest.mark.parametrize(
    ("reason", "shape"),
    (
        ("missing", ()),
        ("invalid", (3,)),
        ("overload", (2, 4)),
        ("missing", (None,)),
        ("invalid", (2, None)),
    ),
)
def test_unavailable_measurements_round_trip_with_complete_contract(
    reason: MeasurementUnavailableReason,
    shape: tuple[int | None, ...],
) -> None:
    value = MeasurementUnavailable.create(
        reason=reason,
        dtype="float64",
        unit="V",
        shape=shape,
        metadata={"instrument_status": reason},
    )
    record = MeasurementRecord(
        run_id="run-test",
        point_index=0,
        coordinates={},
        observables={"signal": value},
    )

    restored = assert_model_round_trip(record).observables["signal"]

    assert restored == value
    assert isinstance(restored, MeasurementUnavailable)
    assert restored.shape == shape


def test_unavailable_measurement_schema_exposes_nullable_shape_extents() -> None:
    schema = MeasurementUnavailable.model_json_schema()
    extent_schema = schema["properties"]["shape"]["items"]

    assert {option["type"] for option in extent_schema["anyOf"]} == {
        "integer",
        "null",
    }
    [integer_schema] = [
        option for option in extent_schema["anyOf"] if option["type"] == "integer"
    ]
    assert integer_schema["minimum"] == 0


def test_unavailable_measurement_shape_extents_are_non_negative() -> None:
    with pytest.raises(ValidationError, match="greater than or equal to 0"):
        MeasurementUnavailable.create(
            reason="invalid",
            dtype="float64",
            unit=None,
            shape=(2, -1),
            metadata={},
        )


@pytest.mark.parametrize("dtype", ["bool", "string"])
@pytest.mark.parametrize("kind", ["scalar", "array", "unavailable"])
def test_bool_and_string_measurements_reject_units(
    dtype: Literal["bool", "string"],
    kind: Literal["scalar", "array", "unavailable"],
) -> None:
    with pytest.raises(ValidationError, match="cannot have a unit"):
        if kind == "scalar":
            MeasurementScalar.create(
                dtype=dtype,
                unit="ratio",
                value=True if dtype == "bool" else "ready",
            )
        elif kind == "array":
            MeasurementArray.create(
                dtype=dtype,
                unit="ratio",
                values=[True if dtype == "bool" else "ready"],
            )
        else:
            MeasurementUnavailable.create(
                reason="missing",
                dtype=dtype,
                unit="ratio",
                shape=(),
                metadata={},
            )


@pytest.mark.parametrize("dtype", ["bool", "string"])
def test_bool_and_string_variable_schemas_reject_units(
    dtype: Literal["bool", "string"],
) -> None:
    with pytest.raises(ValidationError, match="cannot have a unit"):
        MeasurementVariable(
            id="invalid",
            role="observable",
            dtype=dtype,
            unit="ratio",
            dims=["point"],
        )


def test_measurement_variable_rejects_an_empty_recording_group_id() -> None:
    with pytest.raises(ValidationError, match="at least 1 character"):
        MeasurementVariable(
            id="signal",
            role="observable",
            dtype="float64",
            dims=["point"],
            recording_group_id="",
        )


def test_measurement_dimensions_require_concrete_size() -> None:
    with pytest.raises(ValidationError, match="Field required"):
        MeasurementDimension.model_validate({"id": "point", "kind": "point"})
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        MeasurementDimension.model_validate(
            {"id": "point", "kind": "point", "size": 1, "unit": "count"}
        )


def test_measurement_entity_index_is_labeled_and_cardinality_checked() -> None:
    q0 = EntityRef(id="q0", kind="logical_qubit")
    q1 = EntityRef(id="q1", kind="logical_qubit")
    dimension = MeasurementDimension(
        id="qubit",
        kind="entity",
        size=2,
        index=MeasurementEntityIndex(
            entity_kind="logical_qubit",
            values=(q0, q1),
        ),
    )

    assert assert_model_round_trip(dimension) == dimension
    assert dimension.index is not None
    assert dimension.index.values == (q0, q1)

    with pytest.raises(ValidationError, match="cardinality"):
        dimension.model_copy(update={"size": 1})
    with pytest.raises(ValidationError, match="must be unique"):
        MeasurementEntityIndex(values=(q0, q0))
    with pytest.raises(ValidationError, match="declared entity kind"):
        MeasurementEntityIndex(entity_kind="coupler", values=(q0,))


def test_measurement_dataset_and_schema_round_trip() -> None:
    record = signal_record()
    schema = signal_point_schema(size=3)
    dataset = MeasurementDataset(
        dataset_schema=schema,
        records=[record],
    )
    restored = assert_model_round_trip(dataset)

    assert restored.dataset_schema.dataset_id == "raw-measurements"
    assert restored.dataset_schema.primary_coordinates == ("drive_frequency",)
    assert restored.dataset_schema.primary_observables == ("signal",)
    assert restored.records == (record,)
    assert restored == dataset
