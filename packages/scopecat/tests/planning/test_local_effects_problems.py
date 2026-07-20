from collections.abc import Mapping

import pytest

from scopecat.compiler.relations.model import (
    RelationExpr,
    grid,
    point_col,
    table,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import ProductAxisDef
from scopecat.compiler.typed.program import (
    LogicalResourceRequirement,
    product_axis,
    record_product,
)
from scopecat.execution.local.program import CollectOperation
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemCategory, model_location
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar, String, ValueType
from scopecat.kernel.value_types import Table as TableType
from scopecat.records.parameter import Quantity
from tests.testkit.local_materialization import operations_of_type
from tests.testkit.materialized_effects import materialized_effects_contract
from tests.testkit.parameter_fixtures import PARAMETER_TYPES, parameters
from tests.testkit.relation_plans import (
    point_domain as verified_point_domain,
)
from tests.testkit.relation_plans import (
    state_field as set_state_field,
)
from tests.testkit.typed_program import (
    instrument_acquisition,
    instrument_acquisitions,
    observable_product,
    overlay_parameter_cell,
    typed_program,
)

_SOURCE_REQUIREMENTS = (
    LogicalResourceRequirement(
        port_id=logical_resource_port_id("source"),
        capabilities=("scalar_signal",),
    ),
)


def _point_domain(
    expr: RelationExpr,
    *,
    parameter_types: Mapping[str, ValueType] | None = None,
) -> PointDomain:
    return verified_point_domain(
        expr,
        bindings=RelationTypeBindings(
            parameters=parameter_types or PARAMETER_TYPES,
        ),
    )


def _point_bindings(points: PointDomain) -> RelationTypeBindings:
    return RelationTypeBindings(
        parameters=PARAMETER_TYPES,
        point_row=RowType.from_table(points.value_type),
    )


def test_materialized_effects_rejects_record_output_shape_problems() -> None:
    shaped_product = observable_product(
        "signal-shaped",
        unit="ratio",
        axes=[
            product_axis("shot", size=3),
            product_axis("shot", size=3),
        ],
    )
    plain_product = observable_product("signal-plain", unit="ratio")
    acquisitions = instrument_acquisitions(
        shaped_product,
        plain_product,
        capability="scalar_signal",
    )
    shaped_use, shaped_record = record_product(shaped_product, record_id="signal")
    plain_use, plain_record = record_product(plain_product, record_id="signal")
    spec = typed_program(
        id="bad-record-shape",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        resource_requirements=_SOURCE_REQUIREMENTS,
        product_defs=[shaped_product, plain_product],
        instrument_acquisitions=acquisitions,
        product_uses=[shaped_use, plain_use],
        record_uses=[shaped_record, plain_record],
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "product_axis_duplicate",
        "experiment_record_duplicate",
    ]


def test_materialized_effects_rejects_record_schema_problems_without_model_errors() -> (
    None
):
    products = (
        observable_product("bad-unit", unit="not-a-unit"),
        observable_product(
            "bad-axis-unit",
            axes=[product_axis("sample", size=2, unit="not-a-unit")],
        ),
        observable_product(
            "reserved-axis",
            axes=[product_axis("point", size=2)],
        ),
    )
    uses_and_records = tuple(record_product(product) for product in products)
    acquisitions = instrument_acquisitions(*products, capability="scalar_signal")
    spec = typed_program(
        id="invalid-record-schema",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        resource_requirements=_SOURCE_REQUIREMENTS,
        product_defs=products,
        instrument_acquisitions=acquisitions,
        product_uses=[item[0] for item in uses_and_records],
        record_uses=[item[1] for item in uses_and_records],
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "product_unit_unsupported",
        "product_axis_unit_unsupported",
        "product_axis_reserved",
    ]


def test_materialized_effects_rejects_coordinate_and_record_id_collision() -> None:
    product = observable_product("signal", unit="ratio")
    acquisition = instrument_acquisition(product, capability="scalar_signal")
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="coordinate-record-collision",
        kind="problem",
        point_domain=_point_domain(grid(signal=[1.0])),
        resource_requirements=_SOURCE_REQUIREMENTS,
        product_defs=[product],
        instrument_acquisitions=[acquisition],
        product_uses=[product_use],
        record_uses=[record_use],
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "experiment_record_coordinate_collision"
    ]


def test_materialized_effects_allows_provider_key_reuse_across_acquisitions() -> None:
    products = (
        observable_product("raw_i", unit="ratio"),
        observable_product("demod_i", unit="ratio"),
    )
    acquisitions = tuple(
        instrument_acquisition(
            product,
            capability="scalar_signal",
            provider_key="i",
        )
        for product in products
    )
    uses_and_records = tuple(record_product(product) for product in products)
    spec = typed_program(
        id="bad-record-products",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        resource_requirements=_SOURCE_REQUIREMENTS,
        product_defs=products,
        instrument_acquisitions=acquisitions,
        product_uses=[item[0] for item in uses_and_records],
        record_uses=[item[1] for item in uses_and_records],
    )

    preview = materialized_effects_contract(spec, parameters())

    assert [
        operation.command.requests[0].id
        for operation in operations_of_type(preview, CollectOperation)
    ] == ["i", "i"]


def test_materialized_effects_reports_demanded_product_without_a_local_producer() -> (
    None
):
    product = observable_product("signal", unit="ratio")
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="unsupported-record-source",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        product_defs=[product],
        product_uses=[product_use],
        record_uses=[record_use],
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "product_acquire_missing"
    ]


@pytest.mark.parametrize(
    "second_axis",
    [
        product_axis(
            "shot",
            size=3,
            kind="shot",
            unit="count",
            metadata={"mode": "raw"},
        ),
        product_axis(
            "shot",
            size=2,
            kind="sample",
            unit="count",
            metadata={"mode": "raw"},
        ),
        product_axis(
            "shot",
            size=2,
            kind="shot",
            unit=None,
            metadata={"mode": "raw"},
        ),
        product_axis(
            "shot",
            size=2,
            kind="shot",
            unit="count",
            metadata={"mode": "averaged"},
        ),
    ],
)
def test_materialized_effects_rejects_conflicting_shared_record_axes(
    second_axis: ProductAxisDef,
) -> None:
    first_axis = product_axis(
        "shot",
        size=2,
        kind="shot",
        unit="count",
        metadata={"mode": "raw"},
    )
    products = (
        observable_product("i", axes=[first_axis]),
        observable_product("q", axes=[second_axis]),
    )
    acquisitions = instrument_acquisitions(*products, capability="scalar_signal")
    uses_and_records = tuple(record_product(product) for product in products)
    spec = typed_program(
        id="conflicting-record-axis",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        resource_requirements=_SOURCE_REQUIREMENTS,
        product_defs=products,
        instrument_acquisitions=acquisitions,
        product_uses=[item[0] for item in uses_and_records],
        record_uses=[item[1] for item in uses_and_records],
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(spec, parameters())

    problems = failure.value.problems
    assert [problem.code for problem in problems] == ["experiment_record_axis_conflict"]
    assert problems[0].category is ProblemCategory.CONFLICT
    assert problems[0].related_locations == (
        model_location("records", "i", "axes", "shot"),
    )


def test_materialized_effects_rejects_missing_point_parameters_before_evaluation() -> (
    None
):
    spec = typed_program(
        id="missing-points",
        kind="problem",
        point_domain=_point_domain(
            table("missing_table"),
            parameter_types={
                **PARAMETER_TYPES,
                "missing_table": TableType(
                    columns=(),
                    allow_extra_columns=True,
                ),
            },
        ),
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "linked_parameter_missing"
    ]


def test_materialized_effects_reports_parameter_overlay_problems() -> None:
    points = _point_domain(grid(device_id=["r0"]))
    bindings = _point_bindings(points)
    spec = typed_program(
        id="bad-overlay",
        kind="problem",
        point_domain=points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                capabilities=("set_frequency",),
            ),
        ),
        parameter_overlays=[
            overlay_parameter_cell(
                "readout_devices",
                key={"device_id": point_col("device_id")},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=Quantity(value=5.9, unit="GHz"),
                value_type=Scalar(QuantityType(unit="GHz")),
                bindings=bindings,
            ),
            overlay_parameter_cell(
                "readout_devices",
                key={"device_id": "missing"},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=Quantity(value=5.9, unit="GHz"),
                value_type=Scalar(QuantityType(unit="GHz")),
                bindings=bindings,
            ),
        ],
        state=[
            set_state_field(
                "source",
                capability_id="set_frequency",
                field_path="frequency",
                value=Quantity(value=5.9, unit="GHz"),
            )
        ],
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "experiment_parameter_overlay_row_not_found"
    ]


def test_materialized_effects_reports_unknown_parameter_table_problems() -> None:
    points = _point_domain(grid(device_id=["r0"]))
    bindings = _point_bindings(points)
    spec = typed_program(
        id="missing-overlay-table",
        kind="problem",
        point_domain=points,
        parameter_overlays=[
            overlay_parameter_cell(
                "missing_table",
                key={"device_id": point_col("device_id")},
                key_types={"device_id": Scalar(String())},
                column_id="frequency",
                value=Quantity(value=5.9, unit="GHz"),
                value_type=Scalar(QuantityType(unit="GHz")),
                bindings=bindings,
            )
        ],
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "experiment_parameter_overlay_table_missing"
    ]


def test_materialized_effects_reports_state_evaluation_and_conflict_problems() -> None:
    conflict = typed_program(
        id="conflict-state",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                capabilities=("set_frequency",),
            ),
        ),
        state=[
            set_state_field(
                "source",
                capability_id="set_frequency",
                field_path="frequency",
                value=Quantity(value=5.9, unit="GHz"),
            ),
            set_state_field(
                "source",
                capability_id="set_frequency",
                field_path="frequency",
                value=Quantity(value=6.0, unit="GHz"),
            ),
        ],
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(conflict, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "experiment_conflicting_desired_state"
    ]
