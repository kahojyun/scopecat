from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from scopecat.compiler.bind import BoundPlan, _bind_program_facts
from scopecat.compiler.environment import ConfigEnvironment
from scopecat.compiler.relations.context import (
    ParameterRelationData,
)
from scopecat.compiler.relations.uses import RelationUse, relation_use
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.semantic.value_expressions import ScalarValueExpr
from scopecat.compiler.typed.point_domain import PointDomain
from scopecat.compiler.typed.program import (
    BoundProgramFacts,
    LogicalResourceRequirement,
    TypedDomainExecution,
    record_product,
    set_state_property,
)
from scopecat.compiler.typed.verification import (
    ProgramRelationConsumerKind,
    bound_relation_consumers,
)
from scopecat.config.environment import build_config_environment
from scopecat.domain.program import DomainProgramDef
from scopecat.execution.local.program import CollectOperation
from scopecat.graph.relations.model import (
    CellValue,
    ParameterLookupUse,
    ScalarExpr,
    input_ref,
    param,
    parameter_lookup,
)
from scopecat.graph.relations.point_domain import (
    PointAxis,
    point_axis_linear,
    point_axis_values,
)
from scopecat.kernel.entity import EntityRef
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ProblemPhase,
    model_location,
)
from scopecat.kernel.quantity import Quantity
from scopecat.kernel.resource_identity import logical_resource_port_id
from scopecat.kernel.value_types import (
    Entity,
    Float,
    Scalar,
    String,
)
from scopecat.kernel.value_types import Quantity as QuantityType
from scopecat.planning.point_materialization import materialize_bound_points
from scopecat.program.logical import AcquireEffect
from scopecat.records.config import (
    DomainTargetBinding,
    DomainTargetInstrumentMember,
    DomainTargetPrivateEndpoint,
    VirtualInstrumentConnection,
)
from tests.testkit.authoring import load_config
from tests.testkit.local_materialization import (
    materialize_local_execution,
    operations_of_type,
)
from tests.testkit.relation_plans import (
    scalar_value_expr,
)
from tests.testkit.typed_program import (
    instrument_acquisition,
    observable_product,
    verified_logical_program_for,
)

_FLOAT = Scalar(Float())
_FREQUENCY = Scalar(QuantityType(unit="GHz"))
_DRIVE_FREQUENCY = Scalar(QuantityType(unit="GHz", minimum=4.0, maximum=6.0))
_SPAN = Quantity(value=2.0, unit="GHz")


def bind_program_facts(
    bindings: BoundProgramFacts,
    environment: ConfigEnvironment,
) -> BoundPlan:
    return _bind_program_facts(
        verified_logical_program_for(bindings),
        bindings,
        environment,
    )


def _lookup_use(table_id: str) -> ParameterLookupUse:
    return ParameterLookupUse(
        table_id=table_id,
        key_input_types=(("key", Scalar(String())),),
        literal_key_columns=frozenset({"key"}),
        column_id="value",
        result_type=_FREQUENCY,
    )


def _values_axis(
    axis_id: str,
    value_type: Scalar,
    values: tuple[CellValue, ...],
) -> PointAxis[RelationUse[ScalarValueExpr]]:
    return cast(
        "PointAxis[RelationUse[ScalarValueExpr]]",
        point_axis_values(axis_id, value_type, values),
    )


def _linear_axis(
    axis_id: str,
    expression: ScalarExpr,
    *,
    bindings: RelationTypeBindings | None = None,
    count: int = 2,
) -> PointAxis[RelationUse[ScalarValueExpr]]:
    return point_axis_linear(
        axis_id,
        _FREQUENCY,
        relation_use(
            scalar_value_expr(
                expression,
                bindings=bindings,
                expected_type=_FREQUENCY,
            )
        ),
        _SPAN,
        count,
    )


def _entity_rows(
    values: tuple[CellValue, ...],
) -> PointAxis[RelationUse[ScalarValueExpr]]:
    return _values_axis(
        "subject",
        Scalar(Entity()),
        values,
    )


def _symbolic_program() -> BoundProgramFacts:
    axes = (
        _values_axis("a", _FLOAT, (1.0,)),
        _values_axis(
            "b",
            _FREQUENCY,
            (
                Quantity(value=5.0, unit="GHz"),
                Quantity(value=7.0, unit="GHz"),
            ),
        ),
        _linear_axis(
            "c",
            param("drive_frequency"),
            bindings=RelationTypeBindings(
                parameters={"drive_frequency": _DRIVE_FREQUENCY}
            ),
        ),
        _values_axis(
            "d",
            _FREQUENCY,
            (Quantity(value=8.0, unit="GHz"),),
        ),
    )
    selected_product = observable_product(
        "signal",
        metadata={"owner": "selected"},
    )
    available_product = observable_product(
        "available",
        metadata={"owner": "unselected"},
    )
    selected_use, selected_record = record_product(
        selected_product,
        metadata={"owner": "record"},
    )
    selected_acquisition = instrument_acquisition(
        selected_product,
        id="read-signal",
        interface="test.scalar_signal/v1",
        metadata={"owner": "selected-producer"},
    )
    return BoundProgramFacts(
        point_domain=PointDomain(axes=axes),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                interfaces=("test.scalar_signal/v1",),
            ),
        ),
        effects=(selected_acquisition,),
        product_defs=(selected_product, available_product),
        product_uses=(selected_use,),
        record_uses=(selected_record,),
    )


def _environment() -> ConfigEnvironment:
    return build_config_environment(load_config())


def test_link_specializes_config_values_and_retains_backend_neutral_domain() -> None:
    program = _symbolic_program()

    bound = bind_program_facts(program, _environment())

    assert bound.bindings != program
    assert bound.point_domain.axes != program.point_domain.axes
    assert bound.point_domain.cardinality == 4
    assert tuple(column.id for column in bound.point_domain.coordinate_columns) == (
        "a",
        "b",
        "c",
        "d",
    )
    assert tuple(
        consumer.location.path
        for consumer in bound_relation_consumers(
            bound.bindings,
            bound.point_domain,
        )
        if consumer.kind is ProgramRelationConsumerKind.POINT_AXIS_CENTER
    ) == (("axes", 2, "source", "center"),)


def test_link_retains_unit_domain() -> None:
    program = BoundProgramFacts(
        point_domain=PointDomain(axes=()),
    )

    bound = bind_program_facts(program, _environment())

    assert bound.point_domain.axes == ()
    assert bound.point_domain.cardinality == 1
    assert all(
        consumer.kind is not ProgramRelationConsumerKind.POINT_AXIS_CENTER
        for consumer in bound_relation_consumers(
            bound.bindings,
            bound.point_domain,
        )
    )
    assert bound.point_domain.coordinate_columns == ()
    assert bound.domain_target is None


def test_bind_selects_and_snapshots_the_complete_domain_target() -> None:
    config = load_config()
    configured_target = DomainTargetBinding(
        id="tests.selected-target",
        exclusivity_key="physical:selected-target",
        kind="tests.selected-kind",
        members=[
            DomainTargetInstrumentMember(
                role="readout",
                instrument_id="source-0",
            ),
            DomainTargetPrivateEndpoint(
                role="controller",
                connection=VirtualInstrumentConnection(
                    options={"address": "private-controller"}
                ),
            ),
        ],
    )
    config = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={"domain_target": configured_target}
            )
        }
    )
    program = BoundProgramFacts(
        point_domain=PointDomain(axes=()),
        effects=(
            TypedDomainExecution(
                id="domain",
                program=DomainProgramDef(
                    id="program",
                    dialect_id="tests.domain",
                    dialect_version="1",
                    body=(),
                ),
            ),
        ),
    )

    bound = bind_program_facts(program, build_config_environment(config))

    target = bound.domain_target
    assert target is not None
    assert (target.id, target.kind, target.exclusivity_key) == (
        "tests.selected-target",
        "tests.selected-kind",
        "physical:selected-target",
    )
    assert target.instrument_ids == ("source-0",)
    assert target.members == tuple(configured_target.members)
    assert all(
        selected is not configured
        for selected, configured in zip(
            target.members,
            configured_target.members,
            strict=True,
        )
    )


def test_bind_rejects_a_domain_program_without_a_configured_target() -> None:
    config = load_config()
    config = config.model_copy(
        update={
            "system": config.system.model_copy(update={"domain_target": None}),
        }
    )
    program = BoundProgramFacts(
        point_domain=PointDomain(axes=()),
        effects=(
            TypedDomainExecution(
                id="domain",
                program=DomainProgramDef(
                    id="program",
                    dialect_id="tests.domain",
                    dialect_version="1",
                    body=(),
                ),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        bind_program_facts(program, build_config_environment(config))

    [issue] = caught.value.problems
    assert issue.code == "domain_target_missing"
    assert issue.phase is ProblemPhase.PLANNING
    assert issue.location == model_location("config", "system", "domain_target")


def test_raw_link_retains_product_metadata_and_accepted_environment() -> None:
    program = _symbolic_program()
    environment = _environment()
    bound = bind_program_facts(program, environment)
    acquisition = next(
        effect for effect in program.effects if isinstance(effect, AcquireEffect)
    )

    assert bound.environment is environment

    for metadata in (
        program.product_defs[0].metadata,
        acquisition.results[0].metadata,
        program.record_uses[0].metadata,
    ):
        with pytest.raises(TypeError, match="frozen mapping is immutable"):
            cast("dict[str, object]", metadata)["mutated-source"] = True

    assert bound.bindings.product_defs[0].metadata == {"owner": "selected"}
    assert acquisition.results[0].metadata == {"owner": "selected-producer"}
    assert bound.bindings.record_uses[0].metadata == {"owner": "record"}


def test_unselected_product_definition_survives_link_without_collection() -> None:
    program = _symbolic_program()

    bound = bind_program_facts(program, _environment())
    plan = materialize_local_execution(bound)

    selected_id, unselected_id = (product.id for product in bound.bindings.product_defs)
    assert bound.bindings.product_defs == program.product_defs
    assert tuple(use.product_id for use in bound.bindings.product_uses) == (
        selected_id,
    )
    assert tuple(record.product_use_id for record in bound.bindings.record_uses) == (
        bound.bindings.product_uses[0].id,
    )
    assert {
        product_use_id
        for operation in operations_of_type(plan, CollectOperation)
        for binding in operation.result_bindings
        for product_use_id in binding.product_use_ids
    } == {bound.bindings.product_uses[0].id}
    assert unselected_id != selected_id


def test_config_problems_do_not_produce_an_environment() -> None:
    config = load_config()
    invalid = config.model_copy(
        update={
            "system": config.system.model_copy(
                update={"primary_entity_id": "missing-entity"},
            )
        }
    )

    with pytest.raises(CheckFailed) as caught:
        build_config_environment(invalid)

    assert tuple(problem.code for problem in caught.value.problems) == (
        "configuration.unknown_primary_entity",
    )


@pytest.mark.parametrize(
    ("expression", "bindings"),
    (
        (
            param("definitely_missing"),
            RelationTypeBindings(parameters={"definitely_missing": _FREQUENCY}),
        ),
        (
            parameter_lookup(
                _lookup_use("definitely_missing"),
                key={"key": "selected"},
            ),
            RelationTypeBindings(),
        ),
    ),
    ids=("scalar-center", "lookup-center"),
)
def test_link_closes_every_used_axis_center_parameter_import(
    expression: ScalarExpr,
    bindings: RelationTypeBindings,
) -> None:
    program = BoundProgramFacts(
        point_domain=PointDomain(
            axes=(_linear_axis("value", expression, bindings=bindings),)
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        bind_program_facts(program, _environment())

    assert tuple(problem.code for problem in caught.value.problems) == (
        "bound_parameter_missing",
    )
    assert caught.value.problems[0].phase is ProblemPhase.PLANNING
    assert caught.value.problems[0].details["consumer_kind"] == "point_axis_center"
    assert caught.value.problems[0].details["parameter_id"] == "definitely_missing"


def test_link_classifies_a_lookup_bound_to_the_wrong_parameter_shape() -> None:
    parameter_id = "lookup-bound-as-scalar"
    program = BoundProgramFacts(
        point_domain=PointDomain(
            axes=(
                _linear_axis(
                    "value",
                    parameter_lookup(
                        _lookup_use(parameter_id),
                        key={"key": "selected"},
                    ),
                    bindings=RelationTypeBindings(),
                ),
            ),
        ),
    )
    environment = replace(
        _environment(),
        parameters=ParameterRelationData(
            scalars={parameter_id: Quantity(value=1.0, unit="GHz")}
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        bind_program_facts(program, environment)

    assert tuple(problem.code for problem in caught.value.problems) == (
        "bound_parameter_contract_mismatch",
    )
    assert caught.value.problems[0].details["consumer_kind"] == "point_axis_center"
    assert "expected table parameter, got scalar" in caught.value.problems[0].message


def test_link_rejects_remaining_relation_input_imports() -> None:
    input_id = "unresolved"
    program = BoundProgramFacts(
        point_domain=PointDomain(axes=()),
        resource_requirements=(
            LogicalResourceRequirement(
                port_id=logical_resource_port_id("source"),
                interfaces=("test.set_frequency/v1",),
            ),
        ),
        effects=(
            set_state_property(
                resource_port_id=logical_resource_port_id("source"),
                interface_id="test.set_frequency/v1",
                property_id="value",
                value=scalar_value_expr(
                    input_ref(input_id),
                    bindings=RelationTypeBindings(inputs={input_id: _FLOAT}),
                    expected_type=_FLOAT,
                ),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        bind_program_facts(program, _environment())

    assert tuple(problem.code for problem in caught.value.problems) == (
        "bound_input_unresolved",
    )
    assert caught.value.problems[0].details == {
        "consumer_kind": "state_value",
        "input_id": input_id,
    }


def test_link_reports_every_missing_import_in_one_axis_center() -> None:
    missing_ids = ("missing-left", "missing-right")
    program = BoundProgramFacts(
        point_domain=PointDomain(
            axes=(
                _linear_axis(
                    "value",
                    param(missing_ids[0]) + param(missing_ids[1]),
                    bindings=RelationTypeBindings(
                        parameters=dict.fromkeys(missing_ids, _FREQUENCY)
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        bind_program_facts(program, _environment())

    assert tuple(problem.code for problem in caught.value.problems) == (
        "bound_parameter_missing",
        "bound_parameter_missing",
    )
    assert {
        problem.details["parameter_id"] for problem in caught.value.problems
    } == set(missing_ids)
    assert {problem.details["consumer_kind"] for problem in caught.value.problems} == {
        "point_axis_center"
    }


def test_bound_points_retain_exact_proofs_when_materialized() -> None:
    bound = bind_program_facts(_symbolic_program(), _environment())
    materialized = materialize_bound_points(bound)

    assert materialized.bound_plan is bound
    assert materialized.point_domain.id == bound.point_domain.id
    assert [point.logical_ordinal for point in materialized.point_domain.points] == [
        0,
        1,
        2,
        3,
    ]


def test_bound_points_normalize_entities_before_point_identity_is_sealed() -> None:
    program = BoundProgramFacts(
        point_domain=PointDomain(axes=(_entity_rows(("q0",)),)),
    )

    bound = bind_program_facts(program, _environment())
    assert bound.point_domain.entity_columns == ("subject",)
    materialized = materialize_bound_points(bound)

    assert materialized.point_domain.points[0].row["subject"] == EntityRef(
        id="q0",
        kind="logical_device",
    )


def test_bound_points_reject_unknown_entities_at_the_planning_boundary() -> None:
    program = BoundProgramFacts(
        point_domain=PointDomain(axes=(_entity_rows(("missing",)),)),
    )

    with pytest.raises(CheckFailed) as caught:
        materialize_bound_points(bind_program_facts(program, _environment()))

    assert len(caught.value.problems) == 1
    problem = caught.value.problems[0]
    assert problem.code == "unknown_authoring_entity"
    assert problem.phase is ProblemPhase.PLANNING
    assert problem.location == model_location("entity", "missing")
    assert dict(problem.details) == {}


def test_bound_points_preserve_entity_kind_mismatch_problem() -> None:
    program = BoundProgramFacts(
        point_domain=PointDomain(
            axes=(_entity_rows((EntityRef(id="q0", kind="logical_coupler"),)),),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        materialize_bound_points(bind_program_facts(program, _environment()))

    assert len(caught.value.problems) == 1
    problem = caught.value.problems[0]
    assert problem.code == "authoring_entity_kind_mismatch"
    assert problem.phase is ProblemPhase.PLANNING
    assert problem.location == model_location("entity", "q0")
    assert dict(problem.details) == {}
    assert problem.message == ("entity q0 has kind logical_device, not logical_coupler")


def test_bound_points_report_unknown_normalized_entities() -> None:
    program = BoundProgramFacts(
        point_domain=PointDomain(
            axes=(
                _entity_rows(
                    (
                        "q0",
                        EntityRef(id="q0", kind="logical_device"),
                        "missing",
                    ),
                ),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        materialize_bound_points(bind_program_facts(program, _environment()))

    assert [problem.code for problem in caught.value.problems] == [
        "unknown_authoring_entity"
    ]
