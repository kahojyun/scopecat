from dataclasses import replace

import pytest
from scopecat_testkit.bound_program import (
    instrument_acquisition,
    instrument_acquisitions,
    observable_product,
    program_fixture,
)
from scopecat_testkit.expressions import (
    state_property as set_state_property,
)
from scopecat_testkit.expressions import (
    verified_scalar_expr,
)
from scopecat_testkit.local_materialization import operations_of_type
from scopecat_testkit.materialized_effects import materialized_effects_contract
from scopecat_testkit.parameter_fixtures import parameters

from scopecat.compiler.bound_facts import (
    LogicalResourceRequirement,
    product_axis,
    record_product,
)
from scopecat.compiler.point_domain import PointDomain
from scopecat.compiler.relations.verification import ExpressionTypeBindings
from scopecat.execution.local.program import CollectOperation
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.instrument_members import InterfaceRef
from scopecat.kernel.problems import model_location
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_data import CellValue
from scopecat.kernel.value_types import Int, Scalar
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.measurements.products import ProductAxisDef
from scopecat.measurements.records import EntityRecordUse, EntityRecordUseMember
from scopecat.program.expressions import (
    param,
)
from scopecat.program.logical import AcquireResult
from scopecat.program.measurement_types import EntityAcquisitionSemantics
from scopecat.program.point_domain import (
    point_axis_linear,
    point_axis_values,
)
from scopecat.program.products import EntityAxisDef

_SOURCE_REQUIREMENTS = (
    LogicalResourceRequirement(
        port_id=logical_resource_port_id("source"),
        capabilities=(InterfaceRef("test.scalar_signal/v1"),),
    ),
)


def _point_domain(
    column_id: str,
    value_type: Scalar,
    values: tuple[CellValue, ...],
) -> PointDomain:
    return PointDomain(
        axes=(point_axis_values(column_id, value_type, values),),
    )


def test_materialized_effects_allows_result_id_reuse_across_acquisitions() -> None:
    products = (
        observable_product("raw_i", unit="ratio"),
        observable_product("demod_i", unit="ratio"),
    )
    acquisitions = tuple(
        instrument_acquisition(
            product,
            interface="test.scalar_signal/v1",
            result_id="i",
        )
        for product in products
    )
    uses_and_records = tuple(record_product(product) for product in products)
    spec = program_fixture(
        point_domain=_point_domain("index", Scalar(Int()), (0,)),
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


def test_entity_acquisition_cohort_requires_one_collect_command() -> None:
    products = (
        observable_product("signal_q0", unit="ratio"),
        observable_product("signal_q1", unit="ratio"),
    )
    uses = tuple(record_product(product)[0] for product in products)
    record = EntityRecordUse(
        id="signal",
        axis=EntityAxisDef(
            id="qubit",
            values=(
                EntityRef(id="q0", kind="qubit"),
                EntityRef(id="q1", kind="qubit"),
            ),
        ),
        members=tuple(
            EntityRecordUseMember(entity=entity, product_use_id=use.id)
            for entity, use in zip(
                (
                    EntityRef(id="q0", kind="qubit"),
                    EntityRef(id="q1", kind="qubit"),
                ),
                uses,
                strict=True,
            )
        ),
        acquisition=EntityAcquisitionSemantics(
            policy="best_effort",
            cohort_id="readout",
        ),
    )
    acquisitions = instrument_acquisitions(
        *products,
        interface="test.scalar_signal/v1",
    )
    spec = program_fixture(
        point_domain=_point_domain("index", Scalar(Int()), (0,)),
        resource_requirements=_SOURCE_REQUIREMENTS,
        product_defs=products,
        instrument_acquisitions=acquisitions,
        product_uses=uses,
        record_uses=(record,),
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "entity_acquisition_cohort_not_atomic"
    ]

    shared = replace(
        acquisitions[0],
        results=(
            *acquisitions[0].results,
            AcquireResult(product_id=products[1].id, result_id="signal_q1"),
        ),
    )
    shared_spec = replace(
        spec,
        logical=replace(
            spec.logical,
            program=replace(spec.logical.program, effects=(shared,)),
        ),
    )

    preview = materialized_effects_contract(shared_spec, parameters())

    [collect] = operations_of_type(preview, CollectOperation)
    assert len(collect.result_bindings) == 2


def test_materialized_effects_reports_demanded_product_without_a_local_producer() -> (
    None
):
    product = observable_product("signal", unit="ratio")
    product_use, record_use = record_product(product)
    spec = program_fixture(
        point_domain=_point_domain("index", Scalar(Int()), (0,)),
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
            dimension_id="shared/shot",
            dimension_label="shot",
            size=3,
            kind="shot",
            unit="count",
            metadata={"mode": "raw"},
        ),
        pytest.param(
            product_axis(
                "shot",
                dimension_id="shared/shot",
                dimension_label="shot",
                size=None,
                kind="shot",
                unit="count",
                metadata={"mode": "raw"},
            ),
            id="fixed-versus-ragged",
        ),
        product_axis(
            "shot",
            dimension_id="shared/shot",
            dimension_label="shot",
            size=2,
            kind="sample",
            unit="count",
            metadata={"mode": "raw"},
        ),
        product_axis(
            "shot",
            dimension_id="shared/shot",
            dimension_label="shot",
            size=2,
            kind="shot",
            unit=None,
            metadata={"mode": "raw"},
        ),
        product_axis(
            "shot",
            dimension_id="shared/shot",
            dimension_label="shot",
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
        dimension_id="shared/shot",
        dimension_label="shot",
        size=2,
        kind="shot",
        unit="count",
        metadata={"mode": "raw"},
    )
    products = (
        observable_product("i", axes=[first_axis]),
        observable_product("q", axes=[second_axis]),
    )
    acquisitions = instrument_acquisitions(*products, interface="test.scalar_signal/v1")
    uses_and_records = tuple(record_product(product) for product in products)
    spec = program_fixture(
        point_domain=_point_domain("index", Scalar(Int()), (0,)),
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
    assert problems[0].related_locations == (
        model_location("records", "i", "axes", "shot"),
    )


def test_materialized_effects_rejects_missing_point_parameters_before_evaluation() -> (
    None
):
    center_type = Scalar(QuantityType(unit="GHz"))
    center = verified_scalar_expr(
        param("missing_center", center_type),
        bindings=ExpressionTypeBindings(parameters={"missing_center": center_type}),
        expected_type=center_type,
    )
    spec = program_fixture(
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
        materialized_effects_contract(spec, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "bound_parameter_missing"
    ]


def test_materialized_effects_reports_state_evaluation_and_conflict_problems() -> None:
    conflict = program_fixture(
        point_domain=_point_domain("index", Scalar(Int()), (0,)),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                capabilities=(InterfaceRef("test.set_frequency/v1"),),
            ),
        ),
        state=[
            set_state_property(
                "source",
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=Quantity(value=5.9, unit="GHz"),
            ),
            set_state_property(
                "source",
                interface_id="test.set_frequency/v1",
                property_id="frequency",
                value=Quantity(value=6.0, unit="GHz"),
            ),
        ],
    )

    with pytest.raises(CheckFailed) as failure:
        materialized_effects_contract(conflict, parameters())

    assert [problem.code for problem in failure.value.problems] == [
        "experiment_conflicting_desired_state"
    ]
