# pyright: reportUnnecessaryTypeIgnoreComment=true

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Annotated, assert_type

import pytest

import scopecat as sc
from scopecat.api.analysis import AnalysisDefinition, AnalysisInvocation
from scopecat.sdk.instruments import InterfaceRef

_COUNT_TYPE = sc.IntType(minimum=0)
_COUNTER = InterfaceRef("test.counter/v1")
_COUNTER_COUNT = _COUNTER.property("count")
_GLOBAL_COUNT = sc.coordinate("global_count", sc.ScalarType(_COUNT_TYPE))


def _identity_count(*, value: object) -> object:
    return value


def test_module_decorator_injects_one_explicit_context() -> None:
    elaborations = 0

    @sc.module()
    def count_source(
        module: sc.ModuleContext,
        count: Annotated[sc.Input[int], _COUNT_TYPE],
    ) -> None:
        """Expose the selected count."""

        nonlocal elaborations
        elaborations += 1
        count_ref = assert_type(sc.input_ref(count), sc.ValueRef)
        counter = module.resource("test.counter/v1", requires=(_COUNTER,))
        module.bind_property(counter, _COUNTER_COUNT, value=count_ref)

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


def test_module_definition_requires_an_annotated_context() -> None:
    def missing_context(count: int) -> None:
        del count

    with pytest.raises(TypeError, match="first definition parameter"):
        sc.module(  # pyright: ignore[reportCallIssue]
            missing_context  # pyright: ignore[reportArgumentType]
        )


def test_module_definition_rejects_global_symbolic_values() -> None:
    def captured(module: sc.ModuleContext) -> None:
        module.compute(
            "captured",
            fn=_identity_count,
            inputs={"value": _GLOBAL_COUNT},
            output_type=sc.ScalarType(_COUNT_TYPE),
        )

    with pytest.raises(TypeError, match="declare typed module parameters"):
        sc.module(captured)


def test_template_infers_identity_description_and_defaults() -> None:
    @sc.module
    def count_source(
        module: sc.ModuleContext,
        count: Annotated[sc.Input[int], _COUNT_TYPE],
    ) -> None:
        counter = module.resource("test.counter/v1", requires=(_COUNTER,))
        module.bind_property(counter, _COUNTER_COUNT, value=count)

    @sc.template
    def count_experiment(
        experiment: sc.ExperimentContext,
        count: Annotated[sc.Input[int], _COUNT_TYPE] = 2,
    ) -> None:
        """Run one count experiment."""

        experiment.run(count_source(count=count))

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


def test_template_and_scratch_share_the_context_protocol() -> None:
    count = sc.coordinate("count", sc.ScalarType(_COUNT_TYPE))

    @sc.module
    def count_source(
        module: sc.ModuleContext,
        value: Annotated[sc.Input[int], _COUNT_TYPE],
    ) -> None:
        counter = module.resource("test.counter/v1", requires=(_COUNTER,))
        module.bind_property(counter, _COUNTER_COUNT, value=value)

    def body(experiment: sc.ExperimentContext) -> None:
        experiment.run(count_source(value=count))
        experiment.scan(sc.axis(count, (1, 2, 3)))

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
    assert inspect.signature(scratch).parameters == inspect.Signature().parameters
    assert scratch.__wrapped__ is body


def test_scratch_preserves_typed_call_contract() -> None:
    @sc.module
    def count_source(
        module: sc.ModuleContext,
        count: Annotated[sc.Input[int], _COUNT_TYPE],
    ) -> None:
        del module, count

    @sc.scratch
    def count_scratch(
        experiment: sc.ExperimentContext,
        count: int = 2,
    ) -> None:
        experiment.run(count_source(count=count))

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
    def invalid(module: sc.ModuleContext, value: object) -> None:
        del module, value

    with pytest.raises(TypeError, match="needs a scalar Python type"):
        sc.module(invalid)

    def mismatched(
        module: sc.ModuleContext,
        value: Annotated[sc.Input[str], sc.IntType()],
    ) -> None:
        del module, value

    with pytest.raises(TypeError, match="Python annotation is incompatible"):
        sc.module(mismatched)


def test_repeated_default_module_calls_require_explicit_instances() -> None:
    @sc.module
    def source(module: sc.ModuleContext) -> None:
        del module

    def repeated(experiment: sc.ExperimentContext) -> None:
        experiment.run(source())
        experiment.run(source())

    with pytest.raises(ValueError, match="duplicate module instance ids"):
        sc.template(id="test.repeated-defaults")(repeated)

    @sc.template(id="test.explicit-instances")
    def explicit(experiment: sc.ExperimentContext) -> None:
        experiment.run(source.instantiate("left"))
        experiment.run(source.instantiate("right"))

    assert tuple(
        call.instance_id for call in explicit.definition.module.body.child_instances
    ) == ("left", "right")
