from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from scopecat.compiler.relations.model import ScalarExpr, lit, point_col
from scopecat.kernel.value_types import Int, Scalar
from scopecat.measurements.semantics import (
    MeasurementTransformPortability,
    MeasurementTransformSemanticContract,
)
from scopecat.sdk.domain._bridge import _domain_input_normal_form
from scopecat.sdk.domain.compiler import (
    DomainCompilation,
    DomainCompiledJob,
    DomainCompileRequest,
    DomainInput,
    DomainIterationLayout,
    DomainIterationLeaf,
    DomainIterationProduct,
    DomainLiteral,
    DomainPointAffine,
    DomainPointAxis,
    DomainResolvedInputs,
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


def _request() -> DomainCompileRequest:
    value_type = Scalar(Int())
    program = DomainProgramView(
        id="program",
        dialect_id="tests",
        dialect_version="1",
        body=object(),
        inputs=(DomainInputPortView("x", value_type),),
    )
    return DomainCompileRequest(
        call=DomainCallView(id="call", program=program, results=()),
        inputs=(
            DomainInput(
                id="x",
                normal_form=DomainPointAffine("x", 1, 0),
            ),
        ),
        barrier_regions=((0, 1), (2,)),
        input_binder=lambda input_ids, ordinals, _max_points: tuple(
            (
                input_id,
                tuple((1, 2, 3)[ordinal] for ordinal in ordinals),
            )
            for input_id in input_ids
        ),
    )


def _layout(*axes: DomainPointAxis) -> DomainIterationLayout:
    return DomainIterationLayout(
        DomainIterationLeaf(tuple(axis.id for axis in axes), len(axes[0].values)),
        axes,
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
    lowered: list[tuple[int, ...]] = []

    def compile_artifact(inputs: DomainResolvedInputs) -> object:
        lowered.append(inputs.ordinals)
        return f"artifact-{inputs.ordinals[0]}"

    compilation = compiled_jobs(
        request,
        max_points=2,
        compile_artifact=compile_artifact,
    )

    assert [job.point_ordinals for job in compilation.jobs] == [(0, 1), (2,)]
    assert lowered == []
    assert [job.take_artifact() for job in compilation.jobs] == [
        "artifact-0",
        "artifact-2",
    ]
    assert lowered == [(0, 1), (2,)]


def test_partition_preserves_complete_innermost_sweeps_when_capacity_allows() -> None:
    layout = DomainIterationLayout(
        DomainIterationProduct(
            (
                DomainIterationLeaf(("slow",), 2),
                DomainIterationLeaf(("fast",), 3),
            )
        ),
        (
            DomainPointAxis("slow", (10, 20), repeat_each=3),
            DomainPointAxis("fast", (1, 2, 3)),
        ),
    )
    request = replace(
        _request(),
        barrier_regions=((0, 1, 2, 3, 4, 5),),
        iteration_layout=layout,
    )

    assert request.partition(max_points=4) == ((0, 1, 2), (3, 4, 5))


def test_partition_respects_barrier_clipping_before_axis_alignment() -> None:
    layout = DomainIterationLayout(
        DomainIterationProduct(
            (
                DomainIterationLeaf(("slow",), 2),
                DomainIterationLeaf(("fast",), 3),
            )
        ),
        (
            DomainPointAxis("slow", (10, 20), repeat_each=3),
            DomainPointAxis("fast", (1, 2, 3)),
        ),
    )
    request = replace(
        _request(),
        barrier_regions=((1, 2, 3, 4, 5),),
        iteration_layout=layout,
    )

    assert request.partition(max_points=4) == ((1, 2), (3, 4, 5))


def test_compile_request_exposes_sdk_owned_input_normal_form() -> None:
    request = _request()

    assert request.input("x").normal_form == DomainPointAffine("x", 1, 0)
    assert not request.input("x").is_literal
    with pytest.raises(ValueError, match="not a scalar literal"):
        request.input("x").literal_value()


def test_domain_residual_input_exposes_literal_normal_form() -> None:
    assert _domain_input_normal_form(lit(None)) == DomainLiteral(None)
    literal_input = replace(
        _request().input("x"),
        normal_form=DomainLiteral(None),
    )

    assert literal_input.is_literal
    assert literal_input.literal_value() is None


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (point_col("x"), DomainPointAffine("x", 1, 0)),
        (point_col("x") * 2 + 1, DomainPointAffine("x", 2, 1)),
        (3 - 2 * point_col("x"), DomainPointAffine("x", -2, 3)),
        ((point_col("x") + 4) / 2, DomainPointAffine("x", 0.5, 2.0)),
    ],
)
def test_domain_bridge_projects_point_affine_normal_form(
    expression: ScalarExpr,
    expected: DomainPointAffine,
) -> None:
    assert _domain_input_normal_form(expression) == expected


def test_domain_bridge_rejects_multiple_or_nonlinear_point_columns() -> None:
    assert _domain_input_normal_form(point_col("x") + point_col("y")) is None
    assert _domain_input_normal_form(point_col("x") * point_col("x")) is None


def test_compile_request_exposes_exact_finite_point_axis() -> None:
    request = replace(
        _request(),
        iteration_layout=_layout(DomainPointAxis("x", (1, 2, 3), repeat_each=2)),
    )

    axis = request.point_axis("x")

    assert axis is not None
    assert axis.values_at((0, 1, 2, 3, 4, 5, 6)) == (1, 1, 2, 2, 3, 3, 1)
    assert request.point_axis("missing") is None


def test_iteration_layout_partitions_coverage_by_selected_axes() -> None:
    layout = DomainIterationLayout(
        DomainIterationProduct(
            (
                DomainIterationLeaf(("slow",), 2),
                DomainIterationLeaf(("fast",), 3),
            )
        ),
        (
            DomainPointAxis("slow", (10, 20), repeat_each=3),
            DomainPointAxis("fast", (1, 2, 3)),
        ),
    )

    assert layout.partition_by_axes(("slow",), range(6)) == (
        (0, 1, 2),
        (3, 4, 5),
    )
    assert layout.partition_by_axes(("fast",), range(6)) == (
        (0,),
        (1,),
        (2,),
        (3,),
        (4,),
        (5,),
    )
    assert layout.partition_by_axes((), (1, 2, 3, 4)) == ((1, 2, 3, 4),)
    assert layout.partition_by_axes(("unknown",), range(6)) is None


def test_partial_grid_leaf_exposes_known_axis_without_exact_extent() -> None:
    layout = DomainIterationLayout(
        DomainIterationLeaf(("fast",), None),
        (DomainPointAxis("fast", (1, 2, 3)),),
    )

    assert layout.preferred_tile_size is None
    assert layout.partition_by_axes(("fast",), range(6)) == (
        (0,),
        (1,),
        (2,),
        (3,),
        (4,),
        (5,),
    )


def test_compile_request_keeps_barriers_while_partitioning_by_axes() -> None:
    request = replace(
        _request(),
        barrier_regions=((0, 1), (2, 3, 4, 5)),
        iteration_layout=DomainIterationLayout(
            DomainIterationProduct(
                (
                    DomainIterationLeaf(("slow",), 2),
                    DomainIterationLeaf(("fast",), 3),
                )
            ),
            (
                DomainPointAxis("slow", (10, 20), repeat_each=3),
                DomainPointAxis("fast", (1, 2, 3)),
            ),
        ),
    )

    assert request.partition_by_axes(("slow",)) == (
        (0, 1),
        (2,),
        (3, 4, 5),
    )


def test_domain_input_resolution_uses_normal_forms_before_binder() -> None:
    def reject_binding(
        _input_ids: Sequence[str],
        _ordinals: Sequence[int],
        _max_points: int,
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        raise AssertionError("normal-form inputs must not reach the binder")

    request = replace(
        _request(),
        inputs=(
            replace(
                _request().input("x"),
                normal_form=DomainPointAffine("x", 2, 1),
            ),
        ),
        iteration_layout=_layout(DomainPointAxis("x", (0, 1, 2))),
        input_binder=reject_binding,
    )

    inputs = request.resolve_inputs(("x",), (0, 2), max_points=2)

    assert inputs.input("x") == (1, 5)
    assert inputs.binder_input_ids == ()


def test_domain_compiler_resolves_only_selected_inputs_and_points() -> None:
    request = _request()

    inputs = request.resolve_inputs(("x",), (1, 2), max_points=2)

    assert inputs.ordinals == (1, 2)
    assert inputs.input("x") == (2, 3)
    assert inputs.binder_input_ids == ("x",)
    with pytest.raises(ValueError, match="exceeds"):
        request.resolve_inputs(("x",), (0, 1), max_points=1)


def test_domain_input_binding_is_lazy() -> None:
    calls: list[tuple[tuple[int, ...], int]] = []

    def bind_inputs(
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        max_points: int,
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        selected = tuple(ordinals)
        calls.append((selected, max_points))
        return tuple((input_id, tuple(selected)) for input_id in input_ids)

    request = replace(
        _request(),
        input_binder=bind_inputs,
    )

    assert calls == []
    request.resolve_inputs(("x",), (2,), max_points=1)
    assert calls == [((2,), 1)]


def test_domain_input_binding_does_not_expose_unselected_inputs() -> None:
    request = _request()
    second_input = replace(request.inputs[0], id="y")
    selected_ids: list[tuple[str, ...]] = []

    def bind_inputs(
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        _max_points: int,
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        selected_ids.append(tuple(input_ids))
        return tuple((input_id, tuple(ordinals)) for input_id in input_ids)

    request = replace(
        request,
        call=replace(
            request.call,
            program=replace(
                request.call.program,
                inputs=(
                    *request.call.program.inputs,
                    replace(request.call.program.inputs[0], id="y"),
                ),
            ),
        ),
        inputs=(*request.inputs, second_input),
        input_binder=bind_inputs,
    )

    inputs = request.resolve_inputs(("y",), (1,), max_points=1)

    assert selected_ids == [("y",)]
    assert inputs.columns == (("y", (1,)),)
    with pytest.raises(KeyError):
        inputs.input("x")


def test_domain_input_resolution_binds_only_inputs_without_normal_forms() -> None:
    request = _request()
    second_input = replace(
        request.inputs[0],
        id="y",
        normal_form=None,
    )
    selected_ids: list[tuple[str, ...]] = []

    def bind_inputs(
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        _max_points: int,
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        selected_ids.append(tuple(input_ids))
        return tuple(
            (input_id, tuple(ordinal * 10 for ordinal in ordinals))
            for input_id in input_ids
        )

    request = replace(
        request,
        call=replace(
            request.call,
            program=replace(
                request.call.program,
                inputs=(
                    *request.call.program.inputs,
                    replace(request.call.program.inputs[0], id="y"),
                ),
            ),
        ),
        inputs=(*request.inputs, second_input),
        input_binder=bind_inputs,
        iteration_layout=_layout(DomainPointAxis("x", (1, 2, 3))),
    )

    inputs = request.resolve_inputs(("x", "y"), (0, 2), max_points=2)

    assert selected_ids == [("y",)]
    assert inputs.columns == (("x", (1, 3)), ("y", (0, 20)))
    assert inputs.binder_input_ids == ("y",)


def test_compiler_can_absorb_point_varying_inputs() -> None:
    request = _request()

    compilation = compiled_jobs(
        request,
        max_points=2,
        artifact_input_ids=("x",),
    )

    assert compilation.absorbed_input_ids == ("x",)
    assert compilation.binder_input_ids == ("x",)


def test_input_resolution_accepts_an_empty_selection() -> None:
    calls: list[tuple[str, ...]] = []

    def bind_inputs(
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        _max_points: int,
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        calls.append(tuple(input_ids))
        return tuple((input_id, tuple(ordinals)) for input_id in input_ids)

    request = replace(
        _request(),
        inputs=(replace(_request().inputs[0], normal_form=None),),
        input_binder=bind_inputs,
    )
    assert request.resolve_inputs((), (0, 1), max_points=2).columns == ()
    selected = request.resolve_inputs(("x",), (0, 1), max_points=2)

    assert selected.columns == (("x", (0, 1)),)
    assert selected.binder_input_ids == ("x",)
    assert calls == [("x",)]


def test_compilation_rejects_concretely_bound_residual_input() -> None:
    request = _request()
    compilation = compiled_jobs(
        request,
        max_points=2,
    )

    with pytest.raises(ValueError, match="concretized a residual input"):
        validate_domain_compilation(
            request,
            replace(compilation, binder_input_ids=("x",)),
        )


def test_compiled_artifact_inputs_are_absorbed_implicitly() -> None:
    request = _request()

    compilation = compiled_jobs(
        request,
        max_points=2,
        artifact_input_ids=("x",),
    )

    assert compilation.absorbed_input_ids == ("x",)


def test_compiler_can_absorb_dependency_closed_portable_transforms() -> None:
    request = _request_with_transform()

    compilation = compiled_jobs(
        request,
        max_points=2,
        absorbed_transform_ids=("normalize",),
    )

    assert compilation.absorbed_input_ids == ()
    assert compilation.absorbed_transform_ids == ("normalize",)


def test_compiler_cannot_absorb_host_only_transforms() -> None:
    request = _request_with_transform(portability="host_only")

    with pytest.raises(ValueError, match="host-only"):
        compiled_jobs(
            request,
            max_points=2,
            absorbed_transform_ids=("normalize",),
        )


def test_compilation_absorption_must_select_known_transforms() -> None:
    request = _request_with_transform()
    compilation = compiled_jobs(
        request,
        max_points=2,
    )

    with pytest.raises(ValueError, match="known and follow typed order"):
        validate_domain_compilation(
            request,
            replace(compilation, absorbed_transform_ids=("missing",)),
        )


def test_compilation_rejects_job_crossing_effect_region() -> None:
    request = _request()
    compilation = DomainCompilation(
        jobs=(DomainCompiledJob("job-0", (0, 1, 2), lambda: object()),),
    )

    with pytest.raises(ValueError, match="crosses a barrier region"):
        validate_domain_compilation(request, compilation)


def test_compilation_rejects_missing_logical_point() -> None:
    request = _request()
    compilation = DomainCompilation(
        jobs=(DomainCompiledJob("job-0", (0, 1), lambda: object()),),
    )

    with pytest.raises(ValueError, match="cover every logical point exactly once"):
        validate_domain_compilation(request, compilation)
