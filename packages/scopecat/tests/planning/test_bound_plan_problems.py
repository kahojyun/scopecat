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
    product_axis,
    record_product,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemCategory, model_location
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar, String, ValueType
from scopecat.kernel.value_types import Table as TableType
from scopecat.records.parameter import Quantity
from tests.testkit.bound_plan import (
    bound_dataset_dimensions,
    bound_plan_result,
    bound_primary_observables,
    state_literal,
)
from tests.testkit.parameter_fixtures import PARAMETER_TYPES, parameters
from tests.testkit.relation_plans import (
    point_domain as verified_point_domain,
)
from tests.testkit.relation_plans import (
    state_field as set_state_field,
)
from tests.testkit.typed_program import (
    instrument_product_producer,
    observable_product,
    overlay_parameter_cell,
    typed_program,
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


def test_bound_plan_rejects_record_output_shape_problems() -> None:
    shaped_product = observable_product(
        "signal-shaped",
        unit="ratio",
        axes=[
            product_axis("shot", size=3),
            product_axis("shot", size=3),
        ],
    )
    plain_product = observable_product("signal-plain", unit="ratio")
    producers = tuple(
        instrument_product_producer(product)
        for product in (shaped_product, plain_product)
    )
    shaped_use, shaped_record = record_product(shaped_product, record_id="signal")
    plain_use, plain_record = record_product(plain_product, record_id="signal")
    spec = typed_program(
        id="bad-record-shape",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        product_defs=[shaped_product, plain_product],
        instrument_product_producers=producers,
        product_uses=[shaped_use, plain_use],
        record_uses=[shaped_record, plain_record],
    )

    with pytest.raises(CheckFailed) as failure:
        bound_plan_result(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "product_axis_duplicate",
        "experiment_record_duplicate",
    ]


def test_bound_plan_rejects_record_schema_problems_without_model_errors() -> None:
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
    producers = tuple(instrument_product_producer(product) for product in products)
    spec = typed_program(
        id="invalid-record-schema",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        product_defs=products,
        instrument_product_producers=producers,
        product_uses=[item[0] for item in uses_and_records],
        record_uses=[item[1] for item in uses_and_records],
    )

    with pytest.raises(CheckFailed) as failure:
        bound_plan_result(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "product_unit_unsupported",
        "product_axis_unit_unsupported",
        "product_axis_reserved",
    ]


def test_bound_plan_rejects_coordinate_and_record_id_collision() -> None:
    product = observable_product("signal", unit="ratio")
    producer = instrument_product_producer(product)
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="coordinate-record-collision",
        kind="problem",
        point_domain=_point_domain(grid(signal=[1.0])),
        product_defs=[product],
        instrument_product_producers=[producer],
        product_uses=[product_use],
        record_uses=[record_use],
    )

    with pytest.raises(CheckFailed) as failure:
        bound_plan_result(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "experiment_record_coordinate_collision"
    ]


def test_bound_plan_rejects_duplicate_collection_provider_keys() -> None:
    products = (
        observable_product("raw_i", unit="ratio"),
        observable_product("demod_i", unit="ratio"),
    )
    producers = tuple(
        instrument_product_producer(product, provider_key="i") for product in products
    )
    uses_and_records = tuple(record_product(product) for product in products)
    spec = typed_program(
        id="bad-record-products",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        product_defs=products,
        instrument_product_producers=producers,
        product_uses=[item[0] for item in uses_and_records],
        record_uses=[item[1] for item in uses_and_records],
    )

    preview, problems = bound_plan_result(spec, parameters())

    assert [problem.code for problem in problems] == [
        "collection_provider_key_duplicate"
    ]
    assert bound_dataset_dimensions(preview) == {"point": 1}
    assert bound_primary_observables(preview) == ("raw_i", "demod_i")


def test_bound_plan_reports_demanded_product_without_a_local_producer() -> None:
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

    preview, problems = bound_plan_result(spec, parameters())

    assert [problem.code for problem in problems] == ["product_local_producer_missing"]
    assert preview.expected_dataset_schema is None


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
def test_bound_plan_rejects_conflicting_shared_record_axes(
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
    producers = tuple(instrument_product_producer(product) for product in products)
    uses_and_records = tuple(record_product(product) for product in products)
    spec = typed_program(
        id="conflicting-record-axis",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        product_defs=products,
        instrument_product_producers=producers,
        product_uses=[item[0] for item in uses_and_records],
        record_uses=[item[1] for item in uses_and_records],
    )

    with pytest.raises(CheckFailed) as failure:
        bound_plan_result(spec, parameters())

    problems = failure.value.problems
    assert [problem.code for problem in problems] == ["experiment_record_axis_conflict"]
    assert problems[0].category is ProblemCategory.CONFLICT
    assert problems[0].related_locations == (
        model_location("records", "i", "axes", "shot"),
    )


def test_bound_plan_rejects_missing_point_parameters_before_evaluation() -> None:
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
        bound_plan_result(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "linked_parameter_missing"
    ]


def test_bound_plan_reports_parameter_overlay_problems() -> None:
    points = _point_domain(grid(device_id=["r0"]))
    bindings = _point_bindings(points)
    spec = typed_program(
        id="bad-overlay",
        kind="problem",
        point_domain=points,
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
                "source-0",
                capability_id="set_frequency",
                field_path="frequency",
                value=Quantity(value=5.9, unit="GHz"),
            )
        ],
    )

    preview, problems = bound_plan_result(spec, parameters())

    assert [problem.code for problem in problems] == [
        "experiment_parameter_overlay_row_not_found"
    ]
    assert preview.state_changes == ()


def test_bound_plan_reports_unknown_parameter_table_problems() -> None:
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

    preview, problems = bound_plan_result(spec, parameters())

    assert [problem.code for problem in problems] == [
        "experiment_parameter_overlay_table_missing"
    ]
    assert preview.state_changes == ()


def test_bound_plan_reports_state_evaluation_and_conflict_problems() -> None:
    with pytest.raises(
        TypeError,
        match="physical state resource expressions must have string scalar type",
    ):
        set_state_field(
            1,
            capability_id="pulse",
            field_path="frequency",
            value=Quantity(value=5.9, unit="GHz"),
        )

    conflict = typed_program(
        id="conflict-state",
        kind="problem",
        point_domain=_point_domain(grid(index=[0])),
        state=[
            set_state_field(
                "source-0",
                capability_id="set_frequency",
                field_path="frequency",
                value=Quantity(value=5.9, unit="GHz"),
            ),
            set_state_field(
                "source-0",
                capability_id="set_frequency",
                field_path="frequency",
                value=Quantity(value=6.0, unit="GHz"),
            ),
        ],
    )

    conflict_preview, conflict_problems = bound_plan_result(conflict, parameters())

    assert [problem.code for problem in conflict_problems] == [
        "experiment_conflicting_desired_state"
    ]
    assert [
        state_literal(change.after) for change in conflict_preview.state_changes
    ] == [
        Quantity(value=5.9, unit="GHz"),
    ]
