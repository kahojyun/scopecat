from __future__ import annotations

from typing import assert_type

import pytest

import scopecat as sc
from scopecat.program.products import RecordSelection
from scopecat.program.value_refs import internal_value_ref_point_id

_DEVICE_TYPE = sc.ScalarType(sc.EntityType(entity_kind="logical_device"))


def test_one_selects_one_concrete_entity_and_applies_kind() -> None:
    selection = assert_type(
        sc.one("q0", kind="logical_device"),
        sc.OneEntity,
    )

    assert selection.entity == sc.EntityRef(id="q0", kind="logical_device")


def test_one_accepts_a_symbolic_entity_without_losing_its_point_edge() -> None:
    subject = sc.coordinate("subject", _DEVICE_TYPE)

    selection = sc.one(subject, kind="logical_device")
    selected = selection.entity

    assert isinstance(selected, sc.ValueRef)
    assert selected is subject
    assert internal_value_ref_point_id(selected) == "subject"


def test_one_rejects_non_entity_symbolic_values() -> None:
    frequency = sc.coordinate(
        "frequency",
        sc.ScalarType(sc.QuantityType(unit="GHz")),
    )

    with pytest.raises(TypeError, match="entity scalar ValueRef"):
        sc.one(frequency)


def test_one_rejects_an_incompatible_symbolic_entity_kind() -> None:
    coupler = sc.coordinate(
        "coupler",
        sc.ScalarType(sc.EntityType(entity_kind="logical_coupler")),
    )

    with pytest.raises(TypeError, match="not constrained to kind 'logical_device'"):
        sc.one(coupler, kind="logical_device")


def test_one_constrains_an_untyped_concrete_entity_kind() -> None:
    selection = sc.one(sc.EntityRef(id="q0"), kind="logical_device")

    assert selection.entity == sc.EntityRef(id="q0", kind="logical_device")


def test_one_rejects_a_conflicting_concrete_entity_kind() -> None:
    coupler = sc.EntityRef(id="c0", kind="logical_coupler")

    with pytest.raises(ValueError, match=r"logical_coupler.*logical_device"):
        sc.one(coupler, kind="logical_device")


def test_each_preserves_concrete_entity_order_and_kind() -> None:
    selection = assert_type(
        sc.each("q1", "q0", kind="logical_device"),
        sc.EachEntity,
    )
    q1 = sc.EntityRef(id="q1", kind="logical_device")
    q0 = sc.EntityRef(id="q0", kind="logical_device")

    assert selection.entities == (q1, q0)
    assert tuple(selection) == (q1, q0)
    assert len(selection) == 2


def test_each_requires_at_least_one_entity() -> None:
    with pytest.raises(ValueError, match="at least one entity"):
        sc.each()


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


def test_per_entity_is_identity_keyed_and_preserves_declaration_order() -> None:
    q1 = sc.EntityRef(id="q1", kind="logical_device")
    q0 = sc.EntityRef(id="q0", kind="logical_device")
    values = sc.PerEntity(((q1, 7), (q0, 5)))
    described_q1 = q1.model_copy(
        update={"metadata": {"description": "metadata is not identity"}}
    )

    assert tuple(values) == (q1, q0)
    assert values[described_q1] == 7
    assert tuple(values.map(str).items()) == ((q1, "7"), (q0, "5"))


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
    aligned = assert_type(selection.align(selected), sc.PerEntity[int])

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


def test_experiment_record_expands_per_entity_products_in_declaration_order() -> None:
    context = sc.ExperimentContext()
    q1 = sc.EntityRef(id="q1", kind="logical_device")
    q0 = sc.EntityRef(id="q0", kind="logical_device")
    first = context._product("first")
    second = context._product("second")
    products = sc.PerEntity(((q1, first), (q0, second)))

    context.record(products)

    definition = context.close_definition_internal(
        id="test.per-entity-record",
        kind="test",
        metadata=None,
        input_defaults={},
        required_inputs=(),
    )
    selections = tuple(
        selection
        for selection in definition.record_selections
        if isinstance(selection, RecordSelection)
    )
    assert len(selections) == len(definition.record_selections)
    assert [selection.product_id.qualified_name for selection in selections] == [
        "first",
        "second",
    ]
    assert [selection.role for selection in selections] == ["observable", "observable"]


def test_record_namespace_is_non_empty_and_exclusive_with_record_id() -> None:
    context = sc.ExperimentContext()
    product = context._product("signal", scope=("readout",))

    with pytest.raises(ValueError, match="record namespace must be non-empty"):
        context.record(product, namespace="")
    with pytest.raises(
        ValueError,
        match="record_id and namespace cannot be used together",
    ):
        context.record(product, record_id="signal", namespace="calibration")

    context.record(product, namespace="calibration/first")
    definition = context.close_definition_internal(
        id="test.record-namespace",
        kind="test",
        metadata=None,
        input_defaults={},
        required_inputs=(),
    )
    [selection] = definition.record_selections
    assert isinstance(selection, RecordSelection)
    assert selection.record_id == "calibration/first/readout/signal"
