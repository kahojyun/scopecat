from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

import scopecat as sc
from scopecat.compiler.frontend.scan_lowering import (
    lower_scans_point_domain,
    project_axis_record,
)
from scopecat.kernel.quantity import Quantity
from scopecat.program.expressions import ParameterLookupUse
from scopecat.program.parameters import ParameterValueContract
from scopecat.program.point_domain import (
    PointAxis,
    PointAxisLinear,
    PointAxisRange,
    PointAxisValues,
    analyze_point_domain,
)
from scopecat.program.scans import (
    AxisSpec,
    axis_parameter_contracts,
)
from scopecat.program.values import input as program_input
from scopecat.records.run_request import (
    AxisAroundSourceRecord,
    AxisRangeSourceRecord,
    AxisRecord,
    AxisValuesSourceRecord,
    RunRequestParameterLookupValue,
)

_FREQUENCY = sc.ScalarType(sc.QuantityType(unit="GHz"))


def _point(axis_id: str):
    return sc.coordinate(axis_id, _FREQUENCY)


def _parameter_lookup(
    column: str = "frequency",
    value_type: sc.ScalarType = _FREQUENCY,
) -> sc.ValueRef:
    return sc.parameter_lookup(
        "device_parameters",
        key={"device": "q0"},
        column=column,
        value_type=value_type,
    )


def _axis(scan: sc.Axis) -> AxisSpec:
    return scan


def _lower_axis(scan: sc.Axis) -> PointAxis[sc.ValueRef]:
    [axis] = lower_scans_point_domain((_axis(scan),))
    return axis


def test_explicit_scan_lowers_to_a_structural_axis_with_normalized_values() -> None:
    axis = _lower_axis(sc.axis(_point("frequency"), [4.9, 5.1], unit="GHz"))

    assert axis.id == "frequency"
    assert axis.value_type == _FREQUENCY
    assert axis.source == PointAxisValues(
        (
            Quantity(value=4.9, unit="GHz"),
            Quantity(value=5.1, unit="GHz"),
        )
    )
    assert analyze_point_domain((axis,)).cardinality == 2
    assert (
        axis_parameter_contracts(
            _axis(sc.axis(_point("frequency"), [4.9, 5.1], unit="GHz"))
        )
        == ()
    )


def test_explicit_empty_values_define_an_empty_axis() -> None:
    axis = _lower_axis(sc.axis(_point("frequency"), ()))

    assert axis.source == PointAxisValues(())
    assert analyze_point_domain((axis,)).cardinality == 0


def test_explicit_unit_refines_a_generic_quantity_axis_type() -> None:
    generic = sc.ScalarType(sc.QuantityType(dimension="frequency"))
    axis = _lower_axis(
        sc.axis(sc.coordinate("frequency", generic), [4.9, 5.1], unit="GHz")
    )

    assert axis.value_type == sc.ScalarType(
        sc.QuantityType(dimension="frequency", unit="GHz")
    )


def test_around_scan_accepts_numeric_coordinates_with_a_unit() -> None:
    scan = _axis(
        sc.axis(
            _point("frequency"),
            unit="GHz",
            center=5.0,
            span=0.2,
            points=3,
        )
    )

    axis = _lower_axis(scan)
    assert isinstance(axis.source, PointAxisLinear)
    assert axis.source.span == Quantity(value=0.2, unit="GHz")
    record = project_axis_record(scan)
    assert isinstance(record.source, AxisAroundSourceRecord)
    assert record.source.center == Quantity(value=5.0, unit="GHz")


def test_dbm_range_remains_a_first_class_coordinate_source() -> None:
    power_type = sc.ScalarType(sc.QuantityType(unit="dBm"))
    scan = _axis(
        sc.axis(
            sc.coordinate("power", power_type),
            start=-30.0,
            stop=0.0,
            unit="dBm",
            points=7,
        )
    )

    axis = _lower_axis(scan)
    assert axis.value_type == power_type
    assert axis.source == PointAxisRange(
        start=Quantity(-30.0, "dBm"),
        stop=Quantity(0.0, "dBm"),
        count=7,
    )
    assert analyze_point_domain((axis,)).cardinality == 7
    record = project_axis_record(scan)
    assert record == AxisRecord(
        axis_id="power",
        source=AxisRangeSourceRecord(
            start=Quantity(-30.0, "dBm"),
            stop=Quantity(0.0, "dBm"),
            points=7,
        ),
    )


def test_quantity_range_refines_a_dimension_only_axis() -> None:
    generic = sc.ScalarType(sc.QuantityType(dimension="power"))
    axis = _lower_axis(
        sc.axis(
            sc.coordinate("power", generic),
            start=Quantity(-30.0, "dBm"),
            stop=Quantity(0.0, "dBm"),
            points=7,
        )
    )

    assert axis.value_type == sc.ScalarType(
        sc.QuantityType(dimension="power", unit="dBm")
    )


def test_around_scan_keeps_only_its_typed_center_as_authoring_data() -> None:
    center = program_input("center", _FREQUENCY)

    axis = _lower_axis(
        sc.axis(
            _point("frequency"),
            center=center,
            span="2 GHz",
            points=5,
        )
    )

    assert isinstance(axis.source, PointAxisLinear)
    assert axis.source.center.value_type == _FREQUENCY
    assert axis.source.span == Quantity(value=2.0, unit="GHz")
    assert axis.source.count == 5


def test_overlay_around_axis_uses_the_selected_cell_as_its_center() -> None:
    scan = sc.axis(
        _point("frequency"),
        overlay=_parameter_lookup(),
        span="200 MHz",
        points=5,
    )
    axis = _lower_axis(scan)
    assert isinstance(axis.source, PointAxisLinear)
    assert axis.source.center.value_type == _FREQUENCY
    assert axis.source.span == Quantity(value=200.0, unit="MHz")
    assert axis.source.count == 5
    [lookup] = tuple(
        contract
        for contract in axis_parameter_contracts(_axis(scan))
        if isinstance(contract, ParameterLookupUse)
    )
    assert lookup.table_id == "device_parameters"
    assert lookup.column_id == "frequency"
    assert lookup.result_type == _FREQUENCY
    record = project_axis_record(scan)
    assert isinstance(record.source, AxisAroundSourceRecord)
    assert record.source.center == RunRequestParameterLookupValue(
        table_id="device_parameters",
        key={"device": "q0"},
        column="frequency",
    )
    assert record.overlay == record.source.center


def test_overlay_range_axis_preserves_its_locator_and_range() -> None:
    scan = _axis(
        sc.axis(
            _point("frequency"),
            overlay=_parameter_lookup(),
            start=4.9,
            stop=5.1,
            unit="GHz",
            points=5,
        )
    )

    axis = _lower_axis(scan)
    assert axis.source == PointAxisRange(
        start=Quantity(4.9, "GHz"),
        stop=Quantity(5.1, "GHz"),
        count=5,
    )
    record = project_axis_record(scan)
    assert record.overlay == RunRequestParameterLookupValue(
        table_id="device_parameters",
        key={"device": "q0"},
        column="frequency",
    )
    assert isinstance(record.source, AxisRangeSourceRecord)
    assert record.source.start == Quantity(4.9, "GHz")
    assert record.source.stop == Quantity(5.1, "GHz")
    assert record.source.points == 5


def test_overlay_values_axis_keeps_source_and_parameter_target_orthogonal() -> None:
    record = project_axis_record(
        _axis(
            sc.axis(
                _point("frequency"),
                [4.9, 5.1],
                overlay=_parameter_lookup(),
                unit="GHz",
            )
        )
    )

    assert record.source == AxisValuesSourceRecord(
        values=[Quantity(4.9, "GHz"), Quantity(5.1, "GHz")]
    )
    assert record.overlay == RunRequestParameterLookupValue(
        table_id="device_parameters",
        key={"device": "q0"},
        column="frequency",
    )


def test_axis_overlay_forms_are_mutually_exclusive_and_complete() -> None:
    target = _point("frequency")
    lookup = _parameter_lookup()
    unchecked_axis = cast("Callable[..., sc.Axis]", sc.axis)

    with pytest.raises(ValueError, match="exactly one"):
        unchecked_axis(
            target,
            [4.9, 5.1],
            overlay=lookup,
            unit="GHz",
            span="200 MHz",
            points=3,
        )
    with pytest.raises(ValueError, match="requires a center or overlay"):
        unchecked_axis(target, overlay=lookup, span="200 MHz")
    with pytest.raises(ValueError, match="requires a center or overlay"):
        unchecked_axis(target, overlay=lookup)


def test_axis_overlay_requires_one_direct_matching_parameter_cell() -> None:
    target = _point("frequency")

    with pytest.raises(TypeError, match=r"direct scopecat\.parameter_lookup"):
        sc.axis(
            target,
            [4.9, 5.1],
            overlay=sc.parameter("frequency", _FREQUENCY),
            unit="GHz",
        )
    with pytest.raises(TypeError, match="same value type"):
        sc.axis(
            target,
            [4.9, 5.1],
            overlay=_parameter_lookup("gain", sc.ScalarType(sc.FloatType())),
            unit="GHz",
        )
    with pytest.raises(ValueError, match="supplies the center"):
        sc.axis(
            target,
            overlay=_parameter_lookup(),
            center=5.0,
            span=0.2,
            unit="GHz",
            points=3,
        )


def test_overlay_around_axis_requires_a_quantity_point() -> None:
    with pytest.raises(TypeError, match="typed quantity point"):
        sc.axis(
            sc.coordinate("gain", sc.ScalarType(sc.FloatType())),
            overlay=_parameter_lookup("gain", sc.ScalarType(sc.FloatType())),
            span="0.2 ratio",
            points=3,
        )


def test_flat_scans_lower_to_a_cartesian_product() -> None:
    scans = (
        _axis(sc.axis(_point("source"), [4.9, 5.1], unit="GHz")),
        _axis(sc.axis(_point("target"), [5.0, 5.2], unit="GHz")),
    )

    domain = lower_scans_point_domain(scans)

    assert tuple(axis.id for axis in domain) == ("source", "target")


def test_linear_center_is_the_only_point_domain_parameter_contract_source() -> None:
    explicit = _axis(sc.axis(_point("explicit"), [4.9, 5.1], unit="GHz"))
    linear = _axis(
        sc.axis(
            _point("linear"),
            center=sc.parameter("frequency_center", _FREQUENCY),
            span="2 GHz",
            points=3,
        )
    )

    assert axis_parameter_contracts(explicit) == ()
    assert axis_parameter_contracts(linear) == (
        ParameterValueContract("frequency_center", _FREQUENCY),
    )
