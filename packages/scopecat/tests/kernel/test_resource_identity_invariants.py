from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.compiler.frontend.graph_validation import verify_assembly_graph
from scopecat.compiler.relations.model import (
    lit,
)
from scopecat.compiler.relations.point_domain import POINT_UNIT
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.products import ProductDef
from scopecat.compiler.typed.program import (
    AcquireSpec,
    CoreEffect,
    CoreProgram,
    LogicalResourceRequirement,
    product_output,
    record_product,
    set_state_field,
)
from scopecat.compiler.typed.verification import seal_typed_program
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ProblemPhase, model_location
from scopecat.kernel.resource_identity import (
    logical_resource_port_id,
)
from scopecat.kernel.value_types import Float, Scalar
from tests.testkit.relation_plans import scalar_value_expr
from tests.testkit.typed_program import instrument_acquisition


def _number(value: float) -> ScalarValueExpr:
    return scalar_value_expr(lit(value), expected_type=Scalar(Float()))


def _unit_program(
    *,
    products: tuple[ProductDef, ...] = (),
    acquisitions: tuple[AcquireSpec, ...] | None = None,
    **updates: object,
) -> CoreProgram:
    uses_and_records = tuple(record_product(product) for product in products)
    selected_acquisitions = (
        tuple(
            instrument_acquisition(product, capability="scalar_signal")
            for product in products
        )
        if acquisitions is None
        else acquisitions
    )
    selected_updates = dict(updates)
    supplied_effects = cast(
        "tuple[CoreEffect, ...]",
        selected_updates.pop("effects", ()),
    )
    return replace(
        CoreProgram(
            id="resource-identity-invariants",
            kind="compiler_test",
            point_domain=PointDomain(root=POINT_UNIT),
            product_defs=products,
            product_uses=tuple(item[0] for item in uses_and_records),
            record_uses=tuple(item[1] for item in uses_and_records),
            effects=(*supplied_effects, *selected_acquisitions),
        ),
        **selected_updates,
    )


def test_seal_closes_logical_state_and_acquire_resources_and_capabilities() -> None:
    drive = logical_resource_port_id("drive")
    missing_record = product_output("missing-record")
    unsupported_record = product_output("unsupported-record")
    program = _unit_program(
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=drive,
                capabilities=("set.frequency",),
            ),
        ),
        effects=(
            set_state_field(
                resource_port_id=logical_resource_port_id("missing-state"),
                capability_id="set.frequency",
                field_path="value",
                value=_number(1.0),
            ),
            set_state_field(
                resource_port_id=drive,
                capability_id="set.power",
                field_path="value",
                value=_number(2.0),
            ),
        ),
        products=(missing_record, unsupported_record),
        acquisitions=(
            instrument_acquisition(
                missing_record,
                resource_port_id="missing-record-port",
                capability="set.frequency",
            ),
            instrument_acquisition(
                unsupported_record,
                resource_port_id=drive,
                capability="measure.signal",
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        seal_typed_program(program)

    assert {problem.code for problem in caught.value.problems} == {
        "state_resource_port_missing",
        "state_resource_port_capability_missing",
        "acquire_resource_port_missing",
        "acquire_resource_port_capability_missing",
    }
    assert {problem.code: problem.location for problem in caught.value.problems} == {
        "state_resource_port_missing": model_location("state", 0, "resource_port_id"),
        "state_resource_port_capability_missing": model_location(
            "state", 1, "resource_port_id"
        ),
        "acquire_resource_port_missing": model_location(
            "acquisitions", 0, "resource_port_id"
        ),
        "acquire_resource_port_capability_missing": model_location(
            "acquisitions", 1, "resource_port_id"
        ),
    }
    assert all(
        problem.phase is ProblemPhase.AUTHORING for problem in caught.value.problems
    )


def test_capability_less_authored_port_rejects_state_and_acquire_at_assembly() -> None:
    module = (
        sc.module_body(id="test.resource-identity.capability-less")
        .resource("drive")
        .bind_field(
            "drive",
            capability="set.frequency",
            field="value",
            value=1.0,
        )
        .product(
            "signal",
        )
        .acquire(
            "read-signal",
            "signal",
            resource="drive",
            capability="measure.signal",
        )
        .build()
    )

    with pytest.raises(CheckFailed) as caught:
        verify_assembly_graph(elaborate_module(module))

    assert [problem.code for problem in caught.value.problems] == [
        "module_resource_port_capability_missing",
        "module_resource_port_capability_missing",
    ]
    assert all(
        problem.phase is ProblemPhase.AUTHORING for problem in caught.value.problems
    )
