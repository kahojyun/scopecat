import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.relations.model import (
    RelationExpr,
    grid,
    point_col,
    range_values,
    table,
)
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import TypedProgram, record_product
from scopecat.config.profiles import load_config_profile
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.value_types import Table as TableType
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.parameter import Quantity
from tests.testkit.bound_plan import (
    bound_plan_result,
    bound_state_fields,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.relation_plans import (
    point_domain as verified_point_domain,
)
from tests.testkit.relation_plans import (
    state_field,
)
from tests.testkit.typed_program import (
    instrument_product_producer,
    observable_product,
    typed_program,
)
from tests.testkit.workflow_fixtures import load_experiment


def _bound_plan_spec(spec: TypedProgram, config: ConfigProfileSnapshot):
    return bound_plan_result(
        spec, validate_config_environment(config).parameters, config=config
    )


def _point_domain(
    expr: RelationExpr,
    *,
    bindings: RelationTypeBindings | None = None,
) -> PointDomain:
    return verified_point_domain(expr, bindings=bindings)


def test_bound_plan_experiment_builds_expected_plan() -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    spec = load_experiment()

    preview, problems = _bound_plan_spec(spec, config)

    assert preview.experiment_id == spec.id
    assert preview.point_count == 3
    _, state, field = bound_state_fields(preview)[0]
    assert state.resource_id.value == "source-0"
    assert state.capability_id == "set_frequency"
    assert field.field_path == "frequency"
    assert field.value.root == Quantity(value=4.9, unit="GHz")
    assert problems == ()


def test_bound_plan_experiment_includes_float_step_stop_point() -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    points = _point_domain(
        grid(
            drive_frequency=range_values(
                5.9,
                6.0,
                0.025,
                unit="GHz",
                include_stop=True,
            )
        )
    )
    bindings = RelationTypeBindings(point_row=RowType.from_table(points.value_type))
    product = observable_product(
        "signal",
        unit="ratio",
    )
    producer = instrument_product_producer(
        product,
        physical_resource_id="source-0",
    )
    product_use, record_use = record_product(product)
    spec = typed_program(
        id="float-range-scan",
        kind="simple_scan",
        point_domain=points,
        state=[
            state_field(
                "source-0",
                capability_id="set_frequency",
                field_path="frequency",
                value=point_col("drive_frequency"),
                bindings=bindings,
            )
        ],
        product_defs=[product],
        instrument_product_producers=[producer],
        product_uses=[product_use],
        record_uses=[record_use],
    )

    preview, problems = _bound_plan_spec(spec, config)

    values = [record.coordinates["drive_frequency"] for record in preview.points]

    assert problems == ()
    assert all(isinstance(value, Quantity) for value in values)
    assert [value.value for value in values if isinstance(value, Quantity)] == [
        5.9,
        5.925,
        5.95,
        5.975,
        6.0,
    ]


def test_duplicate_coordinate_rows_have_distinct_point_uids() -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    value = Quantity(value=5.0, unit="GHz")
    spec = typed_program(
        id="duplicate-coordinate-scan",
        kind="simple_scan",
        point_domain=_point_domain(grid(drive_frequency=[value, value])),
    )

    preview, problems = _bound_plan_spec(spec, config)

    assert problems == ()
    assert len({point.logical_id.value for point in preview.points}) == 2


def test_bound_plan_rejects_link_problems_without_duplicates() -> None:
    config = load_config_profile(EXAMPLE_DIR / "config-profile.json")
    spec = typed_program(
        id="bad-preview-points",
        kind="problem",
        point_domain=_point_domain(
            table("missing_table"),
            bindings=RelationTypeBindings(
                parameters={
                    "missing_table": TableType(
                        columns=(),
                        allow_extra_columns=True,
                    )
                }
            ),
        ),
    )

    with pytest.raises(CheckFailed) as failure:
        _bound_plan_spec(spec, config)

    assert [
        problem.code
        for problem in failure.value.problems
        if problem.code == "linked_parameter_missing"
    ] == ["linked_parameter_missing"]
