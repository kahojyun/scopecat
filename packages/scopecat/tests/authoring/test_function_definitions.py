# pyright: reportUnnecessaryTypeIgnoreComment=true

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, assert_type

import pytest

import scopecat as sc
from scopecat.api.analysis import AnalysisDefinition, AnalysisInvocation
from scopecat.sdk.instruments import InterfaceRef

_COUNT_TYPE = sc.IntType(minimum=0)
_COUNTER = InterfaceRef("test.counter/v1")
_COUNTER_COUNT = _COUNTER.property("count")


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
        count_ref = assert_type(sc.input_ref(count), sc.ValueRef)
        return (
            sc.procedure()
            .resource("test.counter/v1", requires=(_COUNTER,))
            .bind_property(
                "test.counter/v1",
                _COUNTER_COUNT,
                value=count_ref,
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
    assert isinstance(count_source, sc.ExperimentModule)
    invocation = assert_type(count_source(2), sc.ModuleInvocation)
    assert invocation.instance_id == "count_source"

    if TYPE_CHECKING:
        count_source(count="invalid")  # pyright: ignore[reportArgumentType]
        count_source(unknown=2)  # pyright: ignore[reportCallIssue]


def test_builder_module_call_flattens_only_supplied_extra_inputs() -> None:
    count = sc.input("count", sc.ScalarType(_COUNT_TYPE))
    module = sc.procedure(id="test.builder-call").inputs(count).build()

    signature = inspect.signature(module)
    assert signature.parameters["count"].kind is inspect.Parameter.KEYWORD_ONLY
    invocation = module(count=2)
    assert tuple(invocation.inputs) == ("count",)

    with pytest.raises(ValueError, match="received undeclared inputs: 'extra'"):
        module(count=2, extra=3)


def test_template_infers_identity_description_and_defaults() -> None:
    @sc.module
    def count_source(count: Annotated[sc.Input[int], _COUNT_TYPE]):
        return (
            sc.procedure()
            .resource("test.counter/v1", requires=(_COUNTER,))
            .bind_property(
                "test.counter/v1",
                _COUNTER_COUNT,
                value=count,
            )
        )

    @sc.template
    def count_experiment(count: Annotated[sc.Input[int], _COUNT_TYPE] = 2):
        """Run one count experiment."""

        return sc.experiment(count_source(count=count))

    assert count_experiment.definition.id.endswith(".count_experiment")
    assert count_experiment.definition.kind == "count_experiment"
    assert count_experiment.definition.inputs[0].default == 2
    default_invocation = count_experiment()
    assert default_invocation.definition is count_experiment.definition
    assert default_invocation.inputs == {}
    signature = inspect.signature(count_experiment)
    assert signature.parameters["count"].default == 2
    assert signature.return_annotation is sc.ExperimentInvocation
    assert isinstance(count_experiment, sc.ExperimentTemplate)
    invocation = assert_type(count_experiment(3), sc.ExperimentInvocation)
    assert invocation.inputs == {"count": 3}

    if TYPE_CHECKING:
        count_experiment(count="invalid")  # pyright: ignore[reportArgumentType]
        count_experiment(unknown=3)  # pyright: ignore[reportCallIssue]


def test_analysis_decorator_preserves_configuration_signature() -> None:
    evaluations = 0

    @sc.analysis_step(id="readout.fit")
    def readout_fit(
        context: sc.AnalysisContext,
        *,
        qubit: str,
        attempts: int = 2,
    ) -> sc.Analysis:
        nonlocal evaluations
        evaluations += 1
        return context.result(f"readout fit for {qubit}").table(
            [{"attempts": attempts}]
        )

    assert evaluations == 0
    assert readout_fit.id == "readout.fit"
    assert readout_fit.__wrapped__.__name__ == "readout_fit"
    assert isinstance(readout_fit, AnalysisDefinition)
    signature = inspect.signature(readout_fit)
    assert tuple(signature.parameters) == ("qubit", "attempts")
    assert signature.return_annotation is AnalysisInvocation
    step = assert_type(readout_fit(qubit="q0"), AnalysisInvocation)
    assert step.id == "readout.fit"
    assert step.arguments == (("qubit", "q0"),)

    if TYPE_CHECKING:
        readout_fit(qubit=1)  # pyright: ignore[reportArgumentType]
        readout_fit(unknown="q0")  # pyright: ignore[reportCallIssue]


def test_template_functions_require_explicit_experiment_bodies() -> None:
    def raw_procedure_body() -> sc.ModuleBuilder:
        return sc.procedure()

    with pytest.raises(TypeError, match=r"return experiment\(\) bodies"):
        sc.template(  # pyright: ignore[reportCallIssue]
            raw_procedure_body  # pyright: ignore[reportArgumentType]
        )


def test_template_and_scratch_share_the_experiment_body_protocol() -> None:
    count = sc.coordinate("count", sc.ScalarType(_COUNT_TYPE))

    @sc.module
    def count_source(value: Annotated[sc.Input[int], _COUNT_TYPE]):
        return (
            sc.procedure()
            .resource("test.counter/v1", requires=(_COUNTER,))
            .bind_property(
                "test.counter/v1",
                _COUNTER_COUNT,
                value=value,
            )
        )

    def body() -> sc.ExperimentBody:
        call = count_source(value=count)
        return sc.experiment(call).scan(sc.axis(count, (1, 2, 3)))

    template = sc.template(id="test.function.template", kind="count")(body)
    scratch = sc.scratch(id="test.function.scratch", kind="count")(body)

    template_invocation = template()
    scratch_invocation = scratch()
    assert (
        template_invocation.definition.default_scans
        == scratch_invocation.definition.default_scans
    )
    assert tuple(
        instance.module.id
        for instance in template.definition.module.body.child_instances
    ) == tuple(
        instance.module.id
        for instance in scratch_invocation.definition.module.body.child_instances
    )
    assert inspect.signature(scratch).parameters == inspect.signature(body).parameters
    assert scratch.__wrapped__ is body


def test_scratch_preserves_typed_call_contract() -> None:
    @sc.module
    def count_source(count: Annotated[sc.Input[int], _COUNT_TYPE]):
        return sc.procedure()

    @sc.scratch
    def count_scratch(count: int = 2) -> sc.ExperimentBody:
        return sc.experiment(count_source(count=count))

    signature = inspect.signature(count_scratch)
    assert signature.parameters["count"].default == 2
    assert signature.return_annotation is sc.ExperimentInvocation
    invocation = assert_type(count_scratch(3), sc.ExperimentInvocation)
    [instance] = invocation.definition.module.body.child_instances
    assert [binding.import_id for binding in instance.input_bindings] == ["count"]

    if TYPE_CHECKING:
        count_scratch("invalid")  # pyright: ignore[reportArgumentType]
        count_scratch(unknown=3)  # pyright: ignore[reportCallIssue]


def test_definition_annotations_require_an_unambiguous_value_type() -> None:
    def invalid(value: object):
        return sc.procedure()

    with pytest.raises(TypeError, match="needs a scalar Python type"):
        sc.module(invalid)

    def mismatched(value: Annotated[sc.Input[str], sc.IntType()]):
        return sc.procedure()

    with pytest.raises(TypeError, match="Python annotation is incompatible"):
        sc.module(mismatched)


def test_repeated_default_module_calls_require_explicit_instances() -> None:
    @sc.module
    def source():
        return sc.procedure()

    with pytest.raises(ValueError, match="duplicate module instance ids"):
        sc.experiment(source(), source()).module.build(id="test.repeated-defaults")

    body = sc.experiment(
        source.instantiate("left"),
        source.instantiate("right"),
    )
    assert tuple(
        call.instance_id
        for call in body.module.procedure
        if isinstance(call, sc.ModuleInvocation)
    ) == (
        "left",
        "right",
    )


def test_module_calls_compose_through_builders_and_function_sequences() -> None:
    @sc.module
    def source():
        return sc.procedure()

    left = _DomainCall(source.instantiate("left"))
    right = _DomainCall(source.instantiate("right"))

    @sc.module
    def combined():
        return sc.procedure().use(left, right)

    assert tuple(call.instance_id for call in combined.ir.body.child_instances) == (
        "left",
        "right",
    )
    assert tuple(
        call.instance_id
        for call in sc.procedure().use(left, right).procedure
        if isinstance(call, sc.ModuleInvocation)
    ) == ("left", "right")
