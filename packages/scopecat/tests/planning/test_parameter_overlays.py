from dataclasses import replace

import pytest

from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.relations.evaluation import EvalContext
from scopecat.compiler.relations.model import (
    CellValue,
    parameter_lookup,
    point_col,
)
from scopecat.compiler.relations.point_domain import point_literal_rows
from scopecat.compiler.relations.specialization import (
    ResidualScalar,
    specialize_scalar,
)
from scopecat.compiler.relations.verification import (
    RelationPlanVerificationError,
    RelationTypeBindings,
    RowType,
)
from scopecat.compiler.typed.parameter_overlays import (
    resolve_parameter_cell_bindings,
)
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import LogicalResourceRequirement
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.kernel.value_types import Scalar, String, TableColumn
from scopecat.records.parameter import Quantity
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import materialize_local_execution
from tests.testkit.materialized_effects import (
    config_with_physical_resources,
    materialized_state_fields,
)
from tests.testkit.parameter_fixtures import (
    PARAMETER_TYPES,
    READOUT_FREQUENCY_LOOKUP,
    parameters,
)
from tests.testkit.relation_plans import state_field
from tests.testkit.typed_program import (
    link_program,
    overlay_parameter_cell,
    typed_program,
)

_PARAMETER_TYPES = PARAMETER_TYPES
_DEVICE_ID = Scalar(String())
_FREQUENCY = Scalar(QuantityType(dimension="frequency"))


def _point_domain(
    columns: tuple[TableColumn, ...],
    rows: tuple[tuple[CellValue, ...], ...],
) -> PointDomain:
    return PointDomain(root=point_literal_rows(columns, rows))


def _point_bindings(points: PointDomain) -> RelationTypeBindings:
    return RelationTypeBindings(
        parameters=_PARAMETER_TYPES,
        point_row=RowType.from_table(points.value_type),
    )


def _environment():
    return replace(
        validate_config_environment(load_config()),
        parameters=parameters(),
    )


def _frequency_overlay(
    *,
    key: object,
    value: object,
    bindings: RelationTypeBindings,
):
    return overlay_parameter_cell(
        "readout_devices",
        key={"device_id": key},
        key_types={"device_id": Scalar(String())},
        column_id="frequency",
        value=value,
        value_type=Scalar(QuantityType(unit="GHz")),
        bindings=bindings,
    )


def test_point_parameter_overlay_replaces_only_one_existing_cell() -> None:
    points = _point_domain(
        (
            TableColumn("device_id", _DEVICE_ID),
            TableColumn("frequency", _FREQUENCY),
        ),
        (
            ("r0", Quantity(value=5_900, unit="MHz")),
            ("r1", Quantity(value=6_200, unit="MHz")),
        ),
    )
    point_bindings = _point_bindings(points)
    spec = typed_program(
        id="readout-frequency-overlay",
        kind="readout.frequency_scan",
        point_domain=points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("readout"),
                capabilities=("readout",),
            ),
        ),
        parameter_overlays=[
            _frequency_overlay(
                key=point_col("device_id"),
                value=point_col("frequency"),
                bindings=point_bindings,
            )
        ],
        state=[
            state_field(
                "readout",
                capability_id="readout",
                field_path="frequency",
                value=parameter_lookup(
                    READOUT_FREQUENCY_LOOKUP,
                    key={"device_id": point_col("device_id")},
                ),
                bindings=point_bindings,
            )
        ],
    )

    environment = replace(
        validate_config_environment(
            config_with_physical_resources({"readout-a": ("readout",)})
        ),
        parameters=parameters(),
    )
    base_frequencies = [
        row["frequency"] for row in environment.parameters.table_rows("readout_devices")
    ]
    plan = materialize_local_execution(link_program(spec, environment))
    without_overlay = materialize_local_execution(
        link_program(replace(spec, parameter_overlays=()), environment)
    )

    assert [field.value.root for _, _, field in materialized_state_fields(plan)] == [
        Quantity(value=5.9, unit="GHz"),
        Quantity(value=6.2, unit="GHz"),
    ]
    assert [point.logical_id for point in plan.points] == [
        point.logical_id for point in without_overlay.points
    ]
    assert [
        row["frequency"] for row in environment.parameters.table_rows("readout_devices")
    ] == base_frequencies


def test_point_parameter_overlay_residualizes_parameter_lookup() -> None:
    points = _point_domain(
        (TableColumn("frequency", _FREQUENCY),),
        ((Quantity(value=5.9, unit="GHz"),),),
    )
    bindings = _point_bindings(points)
    overlay = _frequency_overlay(
        key="r0",
        value=point_col("frequency"),
        bindings=bindings,
    )
    parameters_for_run = parameters()
    cells = resolve_parameter_cell_bindings(
        (overlay,),
        known=EvalContext(params=parameters_for_run),
    )

    result = specialize_scalar(
        parameter_lookup(
            READOUT_FREQUENCY_LOOKUP,
            key={"device_id": "r0"},
        ),
        known=EvalContext(params=parameters_for_run),
        parameter_cells=cells,
    )

    assert isinstance(result, ResidualScalar)
    assert result.expression == point_col("frequency")


def test_point_parameter_overlay_reports_missing_row_without_partial_plan() -> None:
    points = _point_domain(
        (TableColumn("device_id", _DEVICE_ID),),
        (("missing",),),
    )
    bindings = _point_bindings(points)
    spec = typed_program(
        id="missing-overlay-row",
        kind="problem",
        point_domain=points,
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                capabilities=("set_frequency",),
            ),
        ),
        parameter_overlays=[
            _frequency_overlay(
                key=point_col("device_id"),
                value=Quantity(value=5.9, unit="GHz"),
                bindings=bindings,
            )
        ],
        state=[
            state_field(
                "source",
                capability_id="set_frequency",
                field_path="frequency",
                value=point_col("device_id"),
                bindings=bindings,
            )
        ],
    )

    with pytest.raises(CheckFailed) as failure:
        materialize_local_execution(link_program(spec, _environment()))

    assert [problem.code for problem in failure.value.problems] == [
        "experiment_parameter_overlay_row_not_found"
    ]


def test_point_parameter_overlay_validates_value_against_catalog_type() -> None:
    points = _point_domain(
        (
            TableColumn("device_id", _DEVICE_ID),
            TableColumn("frequency", Scalar(String())),
        ),
        (("r0", "not-a-frequency"),),
    )

    with pytest.raises(RelationPlanVerificationError) as error:
        _frequency_overlay(
            key=point_col("device_id"),
            value=point_col("frequency"),
            bindings=_point_bindings(points),
        )

    assert error.value.code == "incompatible_result_type"


def test_point_parameter_overlay_reports_missing_table() -> None:
    points = _point_domain(
        (TableColumn("device_id", _DEVICE_ID),),
        (("r0",),),
    )
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
        materialize_local_execution(link_program(spec, _environment()))

    assert [problem.code for problem in failure.value.problems] == [
        "experiment_parameter_overlay_table_missing"
    ]
