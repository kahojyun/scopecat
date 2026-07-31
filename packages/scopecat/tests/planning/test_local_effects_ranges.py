import pytest

from scopecat.compiler.relations.uses import relation_use
from scopecat.compiler.relations.verification import (
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    BoundProgramFacts,
    LogicalResourceRequirement,
    record_product,
)
from scopecat.config.documents import load_config_snapshot_document
from scopecat.config.environment import build_config_environment
from scopecat.graph.relations.model import (
    param,
    point_col,
)
from scopecat.graph.relations.point_domain import (
    point_axis_linear,
    point_axis_values,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar
from scopecat.records.config import ConfigProfileSnapshot
from tests.testkit.materialized_effects import (
    materialized_effects_contract,
    materialized_state_properties,
)
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.relation_plans import (
    scalar_value_expr,
    state_property,
)
from tests.testkit.typed_program import (
    instrument_acquisition,
    observable_product,
    typed_program,
)
from tests.testkit.workflow_fixtures import load_experiment


def _materialized_effects_spec(spec: BoundProgramFacts, config: ConfigProfileSnapshot):
    return materialized_effects_contract(
        spec, build_config_environment(config).parameters, config=config
    )


def _point_domain(
    values: tuple[Quantity, ...],
) -> PointDomain:
    return PointDomain(
        axes=(
            point_axis_values(
                "drive_frequency",
                Scalar(QuantityType(unit="GHz")),
                values,
            ),
        )
    )


def test_materialized_effects_experiment_builds_expected_plan() -> None:
    config = load_config_snapshot_document(EXAMPLE_DIR / "config-snapshot.json")
    spec = load_experiment()

    preview = _materialized_effects_spec(spec, config)

    assert len(preview.points) == 3
    _, state, target = materialized_state_properties(preview)[0]
    assert state.instrument_id == "source-0"
    assert target.interface_id == "test.set_frequency/v1"
    assert target.property_id == "frequency"
    assert target.value.root == Quantity(value=4.9, unit="GHz")


def test_materialized_effects_materializes_explicit_float_points() -> None:
    config = load_config_snapshot_document(EXAMPLE_DIR / "config-snapshot.json")
    points = _point_domain(
        tuple(
            Quantity(value=value, unit="GHz")
            for value in (5.9, 5.925, 5.95, 5.975, 6.0)
        )
    )
    bindings = RelationTypeBindings(point_row=RowType.from_table(points.value_type))
    product = observable_product(
        "signal",
        unit="ratio",
    )
    acquisition = instrument_acquisition(
        product,
        resource_port_id="source",
        interface="test.set_frequency/v1",
    )
    product_use, record_use = record_product(product)
    spec = typed_program(
        point_domain=points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                interfaces=("test.set_frequency/v1",),
            ),
        ),
        state=[
            state_property(
                "source",
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=point_col("drive_frequency"),
                bindings=bindings,
            )
        ],
        product_defs=[product],
        instrument_acquisitions=[acquisition],
        product_uses=[product_use],
        record_uses=[record_use],
    )

    preview = _materialized_effects_spec(spec, config)

    values = [record.coordinates["drive_frequency"] for record in preview.points]

    assert all(isinstance(value, Quantity) for value in values)
    assert [value.value for value in values if isinstance(value, Quantity)] == [
        5.9,
        5.925,
        5.95,
        5.975,
        6.0,
    ]


def test_duplicate_coordinate_rows_have_distinct_point_uids() -> None:
    config = load_config_snapshot_document(EXAMPLE_DIR / "config-snapshot.json")
    value = Quantity(value=5.0, unit="GHz")
    spec = typed_program(
        point_domain=_point_domain((value, value)),
    )

    preview = _materialized_effects_spec(spec, config)

    assert len({point.logical_id.value for point in preview.points}) == 2


def test_materialized_effects_rejects_bind_problems_without_duplicates() -> None:
    config = load_config_snapshot_document(EXAMPLE_DIR / "config-snapshot.json")
    center_type = Scalar(QuantityType(unit="GHz"))
    center = relation_use(
        scalar_value_expr(
            param("missing_center"),
            bindings=RelationTypeBindings(parameters={"missing_center": center_type}),
            expected_type=center_type,
        )
    )
    spec = typed_program(
        point_domain=PointDomain(
            axes=(
                point_axis_linear(
                    "frequency",
                    center_type,
                    center,
                    Quantity(value=0.2, unit="GHz"),
                    2,
                ),
            )
        ),
    )

    with pytest.raises(CheckFailed) as failure:
        _materialized_effects_spec(spec, config)

    assert [
        problem.code
        for problem in failure.value.problems
        if problem.code == "bound_parameter_missing"
    ] == ["bound_parameter_missing"]
