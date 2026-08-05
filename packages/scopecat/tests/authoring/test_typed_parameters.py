# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import TYPE_CHECKING, assert_type

import pytest

import scopecat as sc
from scopecat.program.value_refs import internal_value_ref_parameter_lookup

_DEVICE = sc.parameter_field(
    "device",
    sc.EntityType(entity_kind="logical_device"),
)
_FREQUENCY = sc.parameter_field(
    "frequency",
    sc.QuantityType(unit="GHz"),
)
_ENABLED = sc.parameter_field("enabled", sc.BoolType())
_DEVICES = sc.parameter_schema(
    "device_parameters",
    fields=(_DEVICE, _FREQUENCY, _ENABLED),
    primary_key=(_DEVICE,),
    description="Typed device calibration values.",
)
_Q0 = _DEVICES.row(
    _DEVICE.key("q0"),
)


def test_parameter_schema_owns_catalog_table_and_stable_refs() -> None:
    frequency = assert_type(
        _Q0[_FREQUENCY],
        sc.ParameterCell[sc.Quantity],
    )
    assert_type(frequency.ref, sc.ValueRef[sc.Quantity])
    assert_type(_DEVICES.ref, sc.ValueRef[list[dict[str, object]]])

    assert _DEVICES.ref is _DEVICES.ref
    assert _Q0[_FREQUENCY] is frequency
    assert _Q0[_FREQUENCY].ref is frequency.ref
    assert _DEVICES.value_type == sc.TableType(
        columns=(
            sc.TableColumn(
                "device",
                sc.ScalarType(sc.EntityType(entity_kind="logical_device")),
            ),
            sc.TableColumn(
                "frequency",
                sc.ScalarType(sc.QuantityType(unit="GHz")),
            ),
            sc.TableColumn("enabled", sc.ScalarType(sc.BoolType())),
        ),
        primary_key=("device",),
    )
    catalog = sc.parameter_catalog("test-parameters", _DEVICES)
    assert catalog.get(_DEVICES.id) == _DEVICES.definition

    lookup = internal_value_ref_parameter_lookup(frequency.ref)
    assert lookup is not None
    lookup_use, _key = lookup
    assert lookup_use.table_id == _DEVICES.id
    assert lookup_use.column_id == _FREQUENCY.id

    if TYPE_CHECKING:
        frequency.update("invalid")  # pyright: ignore[reportCallIssue, reportArgumentType]
        _DEVICE.key(3)  # pyright: ignore[reportArgumentType]


def test_parameter_row_builds_complete_values_and_typed_updates() -> None:
    row = _Q0.values(
        _FREQUENCY.value(5.0),
        _ENABLED.value(True),
    )
    assert row == {
        "device": sc.EntityRef(id="q0", kind="logical_device"),
        "frequency": sc.Quantity(5.0, "GHz"),
        "enabled": True,
    }

    update = _Q0[_FREQUENCY].update(5.1)
    assert update.parameter_id == _DEVICES.id
    assert update.key == {"device": sc.EntityRef(id="q0", kind="logical_device")}
    assert update.values == {"frequency": sc.Quantity(5.1, "GHz")}


def test_parameter_rows_reject_incomplete_keys_and_foreign_fields() -> None:
    other = sc.parameter_field("frequency", sc.QuantityType(unit="GHz"))
    other_key = sc.parameter_field(
        "device",
        sc.EntityType(entity_kind="logical_device"),
    )
    with pytest.raises(ValueError, match="must match schema primary key"):
        _DEVICES.row()
    with pytest.raises(ValueError, match="another schema"):
        _DEVICES.row(other_key.key("q0"))
    with pytest.raises(ValueError, match="another schema"):
        _Q0[other]
    with pytest.raises(ValueError, match="cover every field"):
        _Q0.values(_FREQUENCY.value(sc.Quantity(5.0, "GHz")))
    with pytest.raises(ValueError, match="cannot replace key"):
        _Q0.update(_DEVICE.value("q1"))


def test_parameter_fields_normalize_schema_constrained_values() -> None:
    normalized_key = _DEVICE.key("q1")
    assert normalized_key.value == sc.EntityRef(id="q1", kind="logical_device")
    assert _FREQUENCY.value(sc.Quantity(5_000, "MHz")).value == sc.Quantity(
        5.0,
        "GHz",
    )
    with pytest.raises(ValueError, match="quantity must use dimension"):
        _FREQUENCY.value(sc.Quantity(5.0, "ns"))
