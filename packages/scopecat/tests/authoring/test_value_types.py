from __future__ import annotations

from dataclasses import dataclass

import pytest

from scopecat.authoring.value_types import (
    Bool,
    Entity,
    Float,
    Int,
    Payload,
    Quantity,
    Record,
    RecordField,
    Scalar,
    Series,
    String,
    Table,
    TableColumn,
    ValueValidationError,
    coerce_literal,
    validate_literal,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.payloads import PayloadValue
from scopecat.kernel.quantity import Quantity as QuantityValue


def test_scalar_types_coerce_literals_and_apply_constraints() -> None:
    integer = Scalar(Int(minimum=1, maximum=3))
    floating = Scalar(Float(minimum=0.0, maximum=2.0))

    assert coerce_literal(integer, 2) == 2
    assert coerce_literal(floating, 1) == 1.0
    validate_literal(Scalar(Bool()), True)

    with pytest.raises(ValueValidationError, match="value must be at least 1"):
        coerce_literal(integer, 0)
    with pytest.raises(ValueValidationError, match="expected int"):
        coerce_literal(integer, True)
    with pytest.raises(ValueValidationError, match="expected a finite float"):
        coerce_literal(floating, float("inf"))


def test_nullable_is_a_scalar_property() -> None:
    assert coerce_literal(Scalar(String(), nullable=True), None) is None

    with pytest.raises(ValueValidationError, match="must not be null"):
        coerce_literal(Scalar(String()), None)
    with pytest.raises(ValueValidationError, match="must not be null"):
        coerce_literal(Series(Scalar(Int())), None)
    with pytest.raises(ValueValidationError, match="must not be null"):
        coerce_literal(Table(columns=()), None)


def test_string_constraints_are_structural_not_named_kinds() -> None:
    gate_label = Scalar(
        String(
            min_length=2,
            pattern=r"[A-Z][A-Z0-9]+",
            choices=("CZ", "CX"),
        )
    )

    assert coerce_literal(gate_label, "CZ") == "CZ"

    with pytest.raises(ValueValidationError, match="does not match pattern"):
        coerce_literal(gate_label, "cz")
    with pytest.raises(ValueValidationError, match="must be one of"):
        coerce_literal(gate_label, "ZZ")


def test_quantity_coercion_normalizes_units_and_validates_dimension() -> None:
    frequency = Scalar(
        Quantity(
            dimension="frequency",
            unit="GHz",
            minimum=4.0,
            maximum=6.0,
        )
    )

    assert coerce_literal(frequency, 5) == QuantityValue(value=5.0, unit="GHz")
    assert coerce_literal(
        frequency,
        QuantityValue(value=5000.0, unit="MHz"),
    ) == QuantityValue(value=5.0, unit="GHz")
    assert coerce_literal(frequency, {"value": 5.2, "unit": "GHz"}) == (
        QuantityValue(value=5.2, unit="GHz")
    )

    with pytest.raises(ValueValidationError, match="dimension 'frequency'"):
        coerce_literal(frequency, QuantityValue(value=5.0, unit="ns"))


def test_entity_coercion_applies_domain_kind_constraint() -> None:
    qubit = Scalar(Entity(entity_kind="logical_qubit"))

    assert coerce_literal(qubit, "q0") == EntityRef(
        id="q0",
        kind="logical_qubit",
    )
    assert coerce_literal(qubit, {"id": "q1"}) == EntityRef(
        id="q1",
        kind="logical_qubit",
    )

    with pytest.raises(ValueValidationError, match="must have kind 'logical_qubit'"):
        coerce_literal(qubit, EntityRef(id="c0", kind="logical_coupler"))


def test_record_and_series_types_coerce_recursively() -> None:
    batch = Scalar(
        Record(
            fields=(
                RecordField("label", Scalar(String(min_length=1))),
                RecordField(
                    "values",
                    Series(Scalar(Float()), min_length=1),
                ),
                RecordField(
                    "note",
                    Scalar(String(), nullable=True),
                    required=False,
                ),
            )
        )
    )

    assert coerce_literal(batch, {"label": "scan", "values": [1, 2.5]}) == {
        "label": "scan",
        "values": (1.0, 2.5),
    }

    with pytest.raises(ValueValidationError, match="record contains unknown fields"):
        coerce_literal(
            batch,
            {"label": "scan", "values": [1.0], "unexpected": True},
        )
    with pytest.raises(ValueValidationError, match=r"value\.values\[0\]"):
        coerce_literal(batch, {"label": "scan", "values": ["bad"]})


def test_table_type_coerces_rows_and_enforces_primary_key() -> None:
    calibration_table = Table(
        columns=(
            TableColumn("qubit_id", Scalar(String(min_length=1))),
            TableColumn("frequency", Scalar(Quantity(unit="GHz"))),
            TableColumn("enabled", Scalar(Bool()), required=False),
        ),
        primary_key=("qubit_id",),
        min_rows=1,
    )

    assert coerce_literal(
        calibration_table,
        [
            {"qubit_id": "q0", "frequency": 5.0, "enabled": True},
            {
                "qubit_id": "q1",
                "frequency": QuantityValue(value=5100.0, unit="MHz"),
            },
        ],
    ) == (
        {
            "qubit_id": "q0",
            "frequency": QuantityValue(value=5.0, unit="GHz"),
            "enabled": True,
        },
        {
            "qubit_id": "q1",
            "frequency": QuantityValue(value=5.1, unit="GHz"),
        },
    )

    with pytest.raises(ValueValidationError, match="duplicates row 0"):
        coerce_literal(
            calibration_table,
            [
                {"qubit_id": "q0", "frequency": 5.0},
                {"qubit_id": "q0", "frequency": 5.1},
            ],
        )
    with pytest.raises(ValueValidationError, match="unknown columns: extra"):
        coerce_literal(
            calibration_table,
            [{"qubit_id": "q0", "frequency": 5.0, "extra": 1}],
        )


def test_table_primary_keys_use_entity_and_quantity_semantic_identity() -> None:
    entity_table = Table(
        columns=(TableColumn("entity", Scalar(Entity())),),
        primary_key=("entity",),
    )
    with pytest.raises(ValueValidationError, match="duplicates row 0"):
        coerce_literal(
            entity_table,
            [
                {
                    "entity": EntityRef(
                        id="q0",
                        kind="qubit",
                        metadata={"source": "first"},
                    )
                },
                {
                    "entity": EntityRef(
                        id="q0",
                        kind="qubit",
                        metadata={"source": "second"},
                    )
                },
            ],
        )

    quantity_table = Table(
        columns=(
            TableColumn(
                "frequency",
                Scalar(Quantity(dimension="frequency")),
            ),
        ),
        primary_key=("frequency",),
    )
    with pytest.raises(ValueValidationError, match="duplicates row 0"):
        coerce_literal(
            quantity_table,
            [
                {"frequency": QuantityValue(1e-13, "GHz")},
                {"frequency": QuantityValue(1e-4, "Hz")},
            ],
        )


@dataclass(frozen=True)
class _PulseProgram:
    samples: tuple[float, ...]


def test_payload_is_an_opaque_atom_with_a_schema_constraint() -> None:
    payload = Scalar(Payload("pulse_program", python_type=_PulseProgram))
    program = _PulseProgram(samples=(0.0, 1.0))

    assert coerce_literal(payload, program) == PayloadValue(
        schema_id="pulse_program",
        payload=program,
    )

    with pytest.raises(ValueValidationError, match="payload 'pulse_program' expects"):
        coerce_literal(payload, {"samples": [0.0, 1.0]})


def test_invalid_type_definitions_fail_at_construction() -> None:
    with pytest.raises(ValueError, match="minimum must not exceed maximum"):
        Int(minimum=2, maximum=1)
    with pytest.raises(ValueError, match="bounds must be finite"):
        Float(minimum=float("nan"))
    with pytest.raises(ValueError, match="table columns must be unique"):
        Table(
            columns=(
                TableColumn("id", Scalar(String())),
                TableColumn("id", Scalar(String())),
            )
        )
    with pytest.raises(ValueError, match="references unknown columns"):
        Table(columns=(), primary_key=("id",))
    with pytest.raises(ValueError, match="required and non-null"):
        Table(
            columns=(TableColumn("id", Scalar(String(), nullable=True)),),
            primary_key=("id",),
        )
    with pytest.raises(ValueError, match="guarantee finite"):
        Table(
            columns=(TableColumn("id", Scalar(Float(finite=False))),),
            primary_key=("id",),
        )
