from __future__ import annotations

from dataclasses import replace

import pytest

from scopecat.compiler.relations.model import literal_rows, point_col
from scopecat.compiler.relations.point_domain import point_rows
from scopecat.compiler.relations.specialization import BindingTime
from scopecat.compiler.relations.verification import RelationTypeBindings, RowType
from scopecat.compiler.semantic.value_expressions import verify_scalar_value_expr
from scopecat.compiler.typed.point_domain import PointDomain, verify_point_domain
from scopecat.kernel.value_types import Int, Scalar
from scopecat.measurements.semantics import (
    MeasurementTransformPortability,
    MeasurementTransformSemanticContract,
)
from scopecat.sdk.domain.compiler import (
    DomainBoundPoint,
    DomainCompilation,
    DomainCompiledJob,
    DomainCompileRequest,
    DomainResidualInput,
    compiled_jobs,
    validate_domain_compilation,
)
from scopecat.sdk.domain.view import (
    DomainCallView,
    DomainInputPortView,
    DomainMeasurementTransform,
    DomainProductContractView,
    DomainProductUseRef,
    DomainProgramView,
    DomainResultBindingView,
    DomainTransformInputPort,
    DomainTransformOutputPort,
)
from tests.testkit.relation_plans import table_value_expr


def _request() -> DomainCompileRequest:
    value_type = Scalar(Int())
    rows = table_value_expr(literal_rows([{"x": 1}, {"x": 2}, {"x": 3}]))
    point_space = verify_point_domain(
        PointDomain(root=point_rows(rows)),
        program_id="test.domain-compiler",
    )
    program = DomainProgramView(
        id="program",
        dialect_id="tests",
        dialect_version="1",
        body=object(),
        inputs=(DomainInputPortView("x", value_type),),
    )
    return DomainCompileRequest(
        call=DomainCallView(id="call", program=program, results=()),
        point_space=point_space,
        inputs=(
            DomainResidualInput(
                id="x",
                value_type=value_type,
                expression=verify_scalar_value_expr(
                    point_col("x"),
                    bindings=RelationTypeBindings(
                        point_row=RowType.from_table(rows.value_type),
                    ),
                    expected_type=value_type,
                ),
                binding_time=BindingTime.POINT,
            ),
        ),
        barrier_regions=((0, 1), (2,)),
        _bound_points=tuple(
            DomainBoundPoint(ordinal, (("x", value),))
            for ordinal, value in enumerate((1, 2, 3))
        ),
    )


def _request_with_transform(
    *,
    portability: MeasurementTransformPortability = "portable",
) -> DomainCompileRequest:
    request = _request()
    product = DomainProductContractView(
        id="signal",
        kind="observable",
        unit="ratio",
        dtype="float64",
    )
    source = DomainProductUseRef("source", product, native=object())
    derived = DomainProductUseRef("derived", product, native=object())
    transform = DomainMeasurementTransform(
        id="normalize",
        semantic=MeasurementTransformSemanticContract(
            id="tests.normalize",
            version="1",
            portability=portability,
        ),
        inputs=(DomainTransformInputPort("source", source, product),),
        outputs=(DomainTransformOutputPort("result", product, (derived,)),),
    )
    return replace(
        request,
        call=replace(
            request.call,
            results=(DomainResultBindingView("signal", product, (source,)),),
            measurement_transforms=(transform,),
        ),
    )


def test_compiler_controls_partition_within_barrier_regions() -> None:
    request = _request()

    compilation = compiled_jobs(
        request,
        compiler_id="tests.compiler",
        target_id="tests.target",
        max_points=2,
    )

    assert [job.point_ordinals for job in compilation.jobs] == [(0, 1), (2,)]


def test_domain_compiler_binds_only_selected_points_under_budget() -> None:
    request = _request()

    points = request.bind_points((1, 2), max_points=2)

    assert tuple(point.input("x") for point in points) == (2, 3)
    with pytest.raises(ValueError, match="exceeds"):
        request.bind_points((0, 1), max_points=1)


def test_compiler_can_push_dependency_closed_portable_transforms() -> None:
    request = _request_with_transform()

    compilation = compiled_jobs(
        request,
        compiler_id="tests.compiler",
        target_id="tests.target",
        max_points=2,
        pushed_transform_ids=("normalize",),
    )

    assert compilation.pushed_transform_ids == ("normalize",)


def test_compiler_cannot_push_host_only_transforms() -> None:
    request = _request_with_transform(portability="host_only")

    with pytest.raises(ValueError, match="host-only"):
        compiled_jobs(
            request,
            compiler_id="tests.compiler",
            target_id="tests.target",
            max_points=2,
            pushed_transform_ids=("normalize",),
        )


def test_compilation_rejects_job_crossing_effect_region() -> None:
    request = _request()
    compilation = DomainCompilation(
        compiler_id="tests.compiler",
        target_id="tests.target",
        jobs=(DomainCompiledJob("job-0", (0, 1, 2), artifact=object()),),
    )

    with pytest.raises(ValueError, match="crosses a barrier region"):
        validate_domain_compilation(request, compilation)


def test_compilation_rejects_missing_logical_point() -> None:
    request = _request()
    compilation = DomainCompilation(
        compiler_id="tests.compiler",
        target_id="tests.target",
        jobs=(DomainCompiledJob("job-0", (0, 1), artifact=object()),),
    )

    with pytest.raises(ValueError, match="cover every logical point exactly once"):
        validate_domain_compilation(request, compilation)
