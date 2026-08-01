from __future__ import annotations

from typing import assert_type

import pytest

import scopecat as sc
from scopecat.compiler.frontend.parameter_contract_validation import (
    validate_parameter_contracts,
)
from scopecat.program.value_refs import (
    internal_value_ref_parameter_contracts,
    internal_value_ref_parameter_lookup,
    internal_value_ref_point_id,
)
from scopecat.records.parameter import ParameterCatalog, ParameterDefinition

_FREQUENCY_TYPE = sc.ScalarType(sc.QuantityType(unit="GHz"))
_LABEL_TYPE = sc.ScalarType(sc.StringType())
_DEVICE_TYPE = sc.ScalarType(sc.EntityType(entity_kind="logical_device"))


class DeviceParameters(sc.ParameterRow):
    frequency = sc.parameter_column(_FREQUENCY_TYPE)
    label = sc.parameter_column(_LABEL_TYPE, id="display_label")


DEVICES = sc.ParameterTable(
    "device_parameters",
    key=sc.entity_key("device", kind="logical_device"),
    row=DeviceParameters,
)


def _lookup_key(value: sc.ValueRef) -> sc.EntityRef | sc.ValueRef:
    lookup = internal_value_ref_parameter_lookup(value)
    assert lookup is not None
    _use, key = lookup
    assert len(key) == 1
    name, entity = key[0]
    assert name == "device"
    assert isinstance(entity, sc.EntityRef | sc.ValueRef)
    return entity


def test_parameter_table_carries_catalog_schema_and_named_row_columns() -> None:
    assert DEVICES.value_type == sc.TableType(
        primary_key=("device",),
        columns=(
            sc.TableColumn("device", _DEVICE_TYPE),
            sc.TableColumn("frequency", _FREQUENCY_TYPE),
            sc.TableColumn("display_label", _LABEL_TYPE),
        ),
    )
    assert DeviceParameters.frequency.value_type == _FREQUENCY_TYPE
    assert DeviceParameters.label.id == "display_label"


def test_same_parameter_table_schema_validates_its_generated_lookup_contract() -> None:
    frequency = DEVICES[sc.one("q0")].frequency
    catalog = ParameterCatalog(
        id="test.entity-parameters",
        definitions=(
            ParameterDefinition(id=DEVICES.id, value_type=DEVICES.value_type),
        ),
    )

    validate_parameter_contracts(
        catalog,
        internal_value_ref_parameter_contracts(frequency),
    )


def test_one_entity_lookup_returns_one_typed_symbolic_value() -> None:
    frequency = assert_type(
        DEVICES[sc.one("q0")].frequency,
        sc.ValueRef,
    )

    assert frequency.value_type == _FREQUENCY_TYPE
    assert _lookup_key(frequency) == sc.EntityRef(
        id="q0",
        kind="logical_device",
    )


def test_one_accepts_a_symbolic_entity_without_losing_its_lookup_edge() -> None:
    subject = sc.coordinate("subject", _DEVICE_TYPE)

    frequency = assert_type(DEVICES[sc.one(subject)].frequency, sc.ValueRef)
    lookup_subject = _lookup_key(frequency)

    assert isinstance(lookup_subject, sc.ValueRef)
    assert internal_value_ref_point_id(lookup_subject) == "subject"


def test_one_rejects_non_entity_symbolic_values() -> None:
    frequency = sc.coordinate("frequency", _FREQUENCY_TYPE)

    with pytest.raises(TypeError, match="entity scalar ValueRef"):
        sc.one(frequency)


def test_each_lookup_returns_identity_keyed_values_in_declaration_order() -> None:
    rows = assert_type(
        DEVICES[sc.each("q1", "q0")],
        sc.PerEntity[DeviceParameters],
    )
    frequencies = assert_type(
        rows.map(lambda row: row.frequency),
        sc.PerEntity[sc.ValueRef],
    )
    q1 = sc.EntityRef(id="q1", kind="logical_device")
    q0 = sc.EntityRef(id="q0", kind="logical_device")

    assert tuple(rows) == (q1, q0)
    assert tuple(frequencies) == (q1, q0)
    assert _lookup_key(frequencies[q1]) == q1
    assert _lookup_key(frequencies[q0]) == q0
    described_q1 = sc.EntityRef(
        id="q1",
        kind="logical_device",
        metadata={"description": "metadata is not identity"},
    )
    assert rows[described_q1] is rows[q1]
    assert frequencies[described_q1] is frequencies[q1]


def test_each_rejects_duplicate_durable_entity_identity() -> None:
    first = sc.EntityRef(
        id="q0",
        kind="logical_device",
        metadata={"label": "first"},
    )
    second = first.model_copy(update={"metadata": {"label": "second"}})

    with pytest.raises(ValueError, match=r"distinct identities.*logical_device:q0"):
        sc.each(first, second)


def test_each_rejects_same_routing_id_across_entity_kinds() -> None:
    qubit = sc.EntityRef(id="shared", kind="logical_device")
    resonator = sc.EntityRef(id="shared", kind="resonator")

    with pytest.raises(ValueError, match=r"globally unique.*shared"):
        sc.each(qubit, resonator)


def test_per_entity_rejects_duplicate_identity_instead_of_position() -> None:
    first = sc.EntityRef(id="q0", kind="logical_device")
    second = first.model_copy(update={"metadata": {"label": "duplicate"}})

    with pytest.raises(ValueError, match="distinct identities"):
        sc.PerEntity(((first, 1), (second, 2)))


def test_each_aligns_broadcast_and_per_entity_values_by_identity() -> None:
    q0 = sc.EntityRef(id="q0", kind="logical_device")
    q1 = sc.EntityRef(id="q1", kind="logical_device")
    selection = sc.each(q0, q1)

    broadcast = assert_type(selection.align(3), sc.PerEntity[int])
    selected = sc.PerEntity[int](((q1, 7), (q0, 5)))
    aligned = assert_type(
        selection.align(selected),
        sc.PerEntity[int],
    )

    assert tuple(broadcast.items()) == ((q0, 3), (q1, 3))
    assert tuple(aligned.items()) == ((q0, 5), (q1, 7))


def test_each_align_requires_an_exact_entity_identity_join() -> None:
    q0 = sc.EntityRef(id="q0", kind="logical_device")
    q1 = sc.EntityRef(id="q1", kind="logical_device")
    wrong_q1 = sc.EntityRef(id="q1", kind="logical_coupler")

    with pytest.raises(
        ValueError,
        match=(
            r"exactly match.*missing logical_device:q1; "
            r"extra logical_coupler:q1"
        ),
    ):
        sc.each(q0, q1).align(sc.PerEntity(((q0, 1), (wrong_q1, 2))))


def test_table_rejects_wrong_entity_kind_before_building_lookup() -> None:
    coupler = sc.EntityRef(id="c0", kind="logical_coupler")

    with pytest.raises(ValueError, match=r"logical_coupler.*logical_device"):
        _ = DEVICES[sc.one(coupler)].frequency


def test_parameter_table_rejects_duplicate_or_key_colliding_column_ids() -> None:
    class DuplicateColumns(sc.ParameterRow):
        first = sc.parameter_column(_LABEL_TYPE, id="same")
        second = sc.parameter_column(_LABEL_TYPE, id="same")

    with pytest.raises(ValueError, match="column ids must be unique"):
        sc.ParameterTable(
            "duplicates",
            key=sc.entity_key("device"),
            row=DuplicateColumns,
        )

    class KeyCollision(sc.ParameterRow):
        device = sc.parameter_column(_LABEL_TYPE)

    with pytest.raises(ValueError, match="conflicts with its entity key"):
        sc.ParameterTable(
            "key_collision",
            key=sc.entity_key("device"),
            row=KeyCollision,
        )


def test_parameter_row_columns_are_read_only() -> None:
    row = assert_type(DEVICES[sc.one("q0")], DeviceParameters)
    assert_type(row.frequency, sc.ValueRef)

    with pytest.raises(AttributeError, match="read-only"):
        row.frequency = DeviceParameters.frequency


@pytest.mark.parametrize("coordinate_role", [False, True])
def test_experiment_record_expands_per_entity_products_in_declaration_order(
    *,
    coordinate_role: bool,
) -> None:
    context = sc.ExperimentContext()
    q1 = sc.EntityRef(id="q1", kind="logical_device")
    q0 = sc.EntityRef(id="q0", kind="logical_device")
    first = context.product("first")
    second = context.product("second")
    products = sc.PerEntity(((q1, first), (q0, second)))

    if coordinate_role:
        context.record_coordinate(products)
    else:
        context.record(products)

    definition = context.close_definition_internal(
        id="test.per-entity-record",
        kind="test",
        metadata=None,
        input_defaults={},
        required_inputs=(),
    )
    assert [
        selection.product_id.qualified_name
        for selection in definition.record_selections
    ] == ["first", "second"]
    assert [selection.role for selection in definition.record_selections] == [
        "coordinate" if coordinate_role else "observable",
        "coordinate" if coordinate_role else "observable",
    ]


@pytest.mark.parametrize("coordinate_role", [False, True])
def test_per_entity_record_id_still_requires_one_expanded_product(
    *,
    coordinate_role: bool,
) -> None:
    context = sc.ExperimentContext()
    q0 = sc.EntityRef(id="q0", kind="logical_device")
    q1 = sc.EntityRef(id="q1", kind="logical_device")
    products = sc.PerEntity(
        ((q0, context.product("first")), (q1, context.product("second")))
    )

    with pytest.raises(ValueError, match="record_id can only be used with one product"):
        if coordinate_role:
            context.record_coordinate(products, record_id="combined")
        else:
            context.record(products, record_id="combined")


def test_per_entity_record_rejects_an_explicit_empty_record_id() -> None:
    context = sc.ExperimentContext()
    q0 = sc.EntityRef(id="q0", kind="logical_device")
    products = sc.PerEntity(((q0, context.product("signal")),))

    with pytest.raises(ValueError, match="record id must be non-empty"):
        context.record(products, record_id="")
