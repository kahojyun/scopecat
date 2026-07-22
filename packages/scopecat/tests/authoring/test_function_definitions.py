# pyright: reportUnnecessaryTypeIgnoreComment=true

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, assert_type

import pytest

import scopecat as sc

_COUNT_TYPE = sc.IntType(minimum=0)


@dataclass(frozen=True)
class _DomainCall:
    module_invocation: sc.ModuleInvocation


def test_module_decorator_closes_a_symbolic_function_once() -> None:
    elaborations = 0

    @sc.module()
    def count_source(count: Annotated[sc.Input[int], _COUNT_TYPE]):
        """Expose the selected count."""

        nonlocal elaborations
        elaborations += 1
        return (
            sc.module_body()
            .resource("counter")
            .action(
                "set-count",
                resource="counter",
                capability="counter",
                fields={"count": count},
            )
        )

    assert elaborations == 1
    assert count_source.id.endswith(".count_source")
    assert count_source.metadata["description"] == "Expose the selected count."
    assert count_source.input_ports[0].value_type == sc.ScalarType(_COUNT_TYPE)
    signature = inspect.signature(count_source)
    assert tuple(signature.parameters) == ("count",)
    assert signature.return_annotation is sc.ModuleInvocation
    assert count_source.__wrapped__.__name__ == "count_source"
    assert isinstance(count_source, sc.ModuleDefinition)
    invocation = assert_type(count_source(2), sc.ModuleInvocation)
    assert invocation.instance_id == "count_source"

    if TYPE_CHECKING:
        count_source(count="invalid")  # pyright: ignore[reportArgumentType]
        count_source(unknown=2)  # pyright: ignore[reportCallIssue]


def test_template_infers_identity_description_and_defaults() -> None:
    @sc.module
    def count_source(count: Annotated[sc.Input[int], _COUNT_TYPE]):
        return (
            sc.module_body()
            .resource("counter")
            .action(
                "set-count",
                resource="counter",
                capability="counter",
                fields={"count": count},
            )
        )

    @sc.template
    def count_experiment(count: Annotated[sc.Input[int], _COUNT_TYPE] = 2):
        """Run one count experiment."""

        return sc.experiment(count_source(count=count))

    assert count_experiment.id.endswith(".count_experiment")
    assert count_experiment.kind == "count_experiment"
    assert count_experiment.description == "Run one count experiment."
    assert count_experiment.inputs[0].default == 2
    default_invocation = count_experiment()
    assert default_invocation.template is count_experiment
    assert default_invocation.inputs == {}
    signature = inspect.signature(count_experiment)
    assert signature.parameters["count"].default == 2
    assert signature.return_annotation is sc.ExperimentInvocation
    assert isinstance(count_experiment, sc.TemplateDefinition)
    invocation = assert_type(count_experiment(3), sc.ExperimentInvocation)
    assert invocation.inputs == {"count": 3}

    if TYPE_CHECKING:
        count_experiment(count="invalid")  # pyright: ignore[reportArgumentType]
        count_experiment(unknown=3)  # pyright: ignore[reportCallIssue]


def test_template_body_enriches_signature_input_metadata() -> None:
    @sc.module
    def count_source(count: Annotated[sc.Input[int], _COUNT_TYPE]):
        return (
            sc.module_body()
            .resource("counter")
            .action(
                "set-count",
                resource="counter",
                capability="counter",
                fields={"count": count},
            )
        )

    @sc.template
    def count_experiment(count: Annotated[sc.Input[int], _COUNT_TYPE] = 2):
        call = count_source(count=count)
        return sc.experiment(call).input(
            "count",
            label="Count",
            description="Number of increments.",
            metadata={"group": "counter"},
        )

    [description] = count_experiment.inputs
    assert description.default == 2
    assert description.label == "Count"
    assert description.description == "Number of increments."
    assert description.metadata == {"group": "counter"}


def test_template_and_scratch_share_the_experiment_body_protocol() -> None:
    count = sc.point("count", sc.ScalarType(_COUNT_TYPE))

    @sc.module
    def count_source(value: Annotated[sc.Input[int], _COUNT_TYPE]):
        return (
            sc.module_body()
            .resource("counter")
            .action(
                "set-count",
                resource="counter",
                capability="counter",
                fields={"count": value},
            )
        )

    def body() -> sc.ExperimentBody:
        call = count_source(value=count)
        return sc.experiment(call).scan(count, (1, 2, 3))

    template = sc.template(id="test.function.template", kind="count")(body)
    scratch = sc.scratch(id="test.function.scratch", kind="count")(body)

    template_invocation = template()
    scratch_invocation = scratch()
    assert (
        template_invocation.template.default_scans
        == scratch_invocation.template.default_scans
    )
    assert tuple(
        instance.module.id for instance in template.module.ir.body.instances
    ) == tuple(
        instance.module.id
        for instance in scratch_invocation.template.module.ir.body.instances
    )
    assert inspect.signature(scratch).parameters == inspect.signature(body).parameters
    assert scratch.__wrapped__ is body


def test_scratch_preserves_typed_call_contract() -> None:
    @sc.module
    def count_source(count: Annotated[sc.Input[int], _COUNT_TYPE]):
        return sc.module_body()

    @sc.scratch
    def count_scratch(count: int = 2) -> sc.ExperimentBody:
        return sc.experiment(count_source(count=count))

    signature = inspect.signature(count_scratch)
    assert signature.parameters["count"].default == 2
    assert signature.return_annotation is sc.ExperimentInvocation
    invocation = assert_type(count_scratch(3), sc.ExperimentInvocation)
    [instance] = invocation.template.module.ir.body.instances
    assert [binding.import_id for binding in instance.input_bindings] == ["count"]

    if TYPE_CHECKING:
        count_scratch("invalid")  # pyright: ignore[reportArgumentType]
        count_scratch(unknown=3)  # pyright: ignore[reportCallIssue]


def test_definition_annotations_require_an_unambiguous_value_type() -> None:
    def invalid(value: object):
        return sc.module_body()

    with pytest.raises(TypeError, match="needs a scalar Python type"):
        sc.module(invalid)

    def mismatched(value: Annotated[sc.Input[str], sc.IntType()]):
        return sc.module_body()

    with pytest.raises(TypeError, match="Python annotation is incompatible"):
        sc.module(mismatched)


def test_repeated_default_module_calls_require_explicit_instances() -> None:
    @sc.module
    def source():
        return sc.module_body()

    with pytest.raises(ValueError, match="duplicate instance ids"):
        sc.experiment(source(), source())

    body = sc.experiment(
        source.instantiate("left"),
        source.instantiate("right"),
    )
    assert tuple(call.instance_id for call in body.module.invocations) == (
        "left",
        "right",
    )


def test_module_calls_compose_through_builders_and_function_sequences() -> None:
    @sc.module
    def source():
        return sc.module_body()

    left = _DomainCall(source.instantiate("left"))
    right = _DomainCall(source.instantiate("right"))

    @sc.module
    def combined():
        return (left, right)

    assert tuple(call.instance_id for call in combined.ir.body.instances) == (
        "left",
        "right",
    )
    assert tuple(
        call.instance_id for call in sc.module_body().use(left, right).invocations
    ) == ("left", "right")
