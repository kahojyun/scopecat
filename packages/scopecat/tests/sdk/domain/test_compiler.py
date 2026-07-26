from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import pytest

from scopecat.kernel.value_types import Int, Scalar
from scopecat.sdk.domain.compiler import (
    DomainCompilation,
    DomainCompiledInputs,
    DomainCompiledJob,
    DomainCompileRequest,
    DomainCompileTemplate,
    DomainInput,
    DomainResolvedInputs,
    compiled_jobs,
    validate_domain_compilation,
)
from scopecat.sdk.domain.view import (
    DomainCallView,
    DomainInputPortView,
    DomainProgramView,
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
    return DomainCompileTemplate(
        call=DomainCallView(id="call", program=program, results=()),
        program_inputs=(DomainInput("x"),),
        compiler_inputs=(),
    ).bind_points(
        (0, 1, 2),
        program_input_binder=lambda input_ids, ordinals, _max_points: tuple(
            (
                input_id,
                tuple((1, 2, 3)[ordinal] for ordinal in ordinals),
            )
            for input_id in input_ids
        ),
        compiler_input_binder=lambda _input_ids, _ordinals, _max_points: (),
    )


def test_compiler_partitions_contiguous_points_by_capacity() -> None:
    request = _request()
    lowered: list[tuple[int, ...]] = []

    def compile_artifact(inputs: DomainCompiledInputs) -> object:
        lowered.append(inputs.ordinals)
        return f"artifact-{inputs.ordinals[0]}"

    compilation = compiled_jobs(
        request,
        max_points=2,
        compile_artifact=compile_artifact,
    )

    assert [job.point_ordinals for job in compilation.jobs] == [(0, 1), (2,)]
    assert [job.artifact for job in compilation.jobs] == [
        "artifact-0",
        "artifact-2",
    ]
    assert lowered == [(0, 1), (2,)]


def test_partition_uses_only_the_bounded_capacity() -> None:
    request = replace(
        _request(),
        point_ordinals=(0, 1, 2, 3, 4, 5),
    )

    assert request.partition(max_points=4) == ((0, 1, 2, 3), (4, 5))


def test_compile_request_rejects_noncontiguous_points() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        replace(_request(), point_ordinals=(0, 2))


def test_resolved_inputs_decode_each_collection_into_a_typed_value() -> None:
    inputs = DomainResolvedInputs(
        ordinals=(2, 4),
        columns=(("rows", (({"value": 1},), ({"value": 2}, {"value": 3}))),),
    )

    def decode(rows: Sequence[dict[str, int]]) -> tuple[int, ...]:
        return tuple(row["value"] for row in rows)

    decoded = inputs.decode_collection("rows", decode)

    assert decoded == ((1,), (2, 3))


def test_domain_compiler_resolves_only_selected_inputs_and_points() -> None:
    request = _request()

    inputs = request.resolve_program_inputs(("x",), (1, 2), max_points=2)

    assert inputs.ordinals == (1, 2)
    assert inputs.input("x") == (2, 3)
    with pytest.raises(ValueError, match="exceeds"):
        request.resolve_program_inputs(("x",), (0, 1), max_points=1)


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
        program_input_binder=bind_inputs,
    )

    assert calls == []
    request.resolve_program_inputs(("x",), (2,), max_points=1)
    assert calls == [((2,), 1)]


def test_domain_input_binding_does_not_expose_unselected_inputs() -> None:
    request = _request()
    second_input = replace(request.program_inputs[0], id="y")
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
        program_inputs=(*request.program_inputs, second_input),
        program_input_binder=bind_inputs,
    )

    inputs = request.resolve_program_inputs(("y",), (1,), max_points=1)

    assert selected_ids == [("y",)]
    assert inputs.columns == (("y", (1,)),)
    with pytest.raises(KeyError):
        inputs.input("x")


def test_domain_input_resolution_binds_all_selected_inputs() -> None:
    request = _request()
    second_input = DomainInput("y")
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
        program_inputs=(*request.program_inputs, second_input),
        program_input_binder=bind_inputs,
    )

    inputs = request.resolve_program_inputs(("x", "y"), (0, 2), max_points=2)

    assert selected_ids == [("x", "y")]
    assert inputs.columns == (("x", (0, 20)), ("y", (0, 20)))


def test_compiler_can_absorb_point_varying_inputs() -> None:
    request = _request()

    compilation = compiled_jobs(
        request,
        max_points=2,
        artifact_input_ids=("x",),
    )

    assert compilation.absorbed_input_ids == ("x",)


def test_compiled_jobs_resolve_every_compiler_input_separately() -> None:
    request = _request()
    compiler_port = DomainInputPortView("calibrations", Scalar(Int()))
    compiler_binds: list[tuple[str, ...]] = []
    lowered: list[tuple[object, ...]] = []

    def bind_compiler_inputs(
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        _max_points: int,
    ) -> tuple[tuple[str, tuple[object, ...]], ...]:
        compiler_binds.append(tuple(input_ids))
        return (("calibrations", tuple(10 + value for value in ordinals)),)

    def compile_artifact(inputs: DomainCompiledInputs) -> object:
        lowered.append(inputs.compiler.input("calibrations"))
        return object()

    request = replace(
        request,
        call=replace(
            request.call,
            program=replace(
                request.call.program,
                compiler_inputs=(compiler_port,),
            ),
        ),
        compiler_inputs=(DomainInput("calibrations"),),
        compiler_input_binder=bind_compiler_inputs,
    )

    compiled_jobs(
        request,
        max_points=2,
        compile_artifact=compile_artifact,
    )

    assert compiler_binds == [("calibrations",), ("calibrations",)]
    assert lowered == [(10, 11), (12,)]


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
        program_input_binder=bind_inputs,
    )
    assert request.resolve_program_inputs((), (0, 1), max_points=2).columns == ()
    selected = request.resolve_program_inputs(("x",), (0, 1), max_points=2)

    assert selected.columns == (("x", (0, 1)),)
    assert calls == [("x",)]


def test_compiled_artifact_inputs_are_absorbed_implicitly() -> None:
    request = _request()

    compilation = compiled_jobs(
        request,
        max_points=2,
        artifact_input_ids=("x",),
    )

    assert compilation.absorbed_input_ids == ("x",)


def test_compilation_rejects_missing_logical_point() -> None:
    request = _request()
    compilation = DomainCompilation(
        jobs=(DomainCompiledJob("job-0", (0, 1), object()),),
    )

    with pytest.raises(ValueError, match="cover every logical point exactly once"):
        validate_domain_compilation(request, compilation)
