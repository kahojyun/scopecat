# pyright: reportUnusedFunction=false

from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.bind import bind_program
from scopecat.compiler.frontend.resolution import compile_invocation
from scopecat.config.environment import build_config_environment
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ProblemPhase,
    model_location,
)
from tests.testkit.authoring import (
    bind_invocation,
    load_config,
    simple_template,
)
from tests.testkit.instrument_host import compose_test_instruments
from tests.testkit.runtime import check_experiment, sqlite_project_services
from tests.testkit.signal_instruments import TestSignalInstrumentProvider


def test_missing_experiment_input_and_unknown_subject_report_stable_problems(
    tmp_path: Path,
) -> None:
    config = load_config()
    missing_subject = simple_template().bind()
    with pytest.raises(CheckFailed) as missing_error:
        bind_invocation(missing_subject, config_profile=config)
    assert missing_error.value.problems[0].code == ("experiment_missing_input")

    unknown_subject = simple_template().bind(subject="missing")
    with pytest.raises(CheckFailed) as subject_error:
        bind_invocation(unknown_subject, config_profile=config)
    assert subject_error.value.problems[0].code == "unknown_authoring_entity"


def test_unknown_experiment_inputs_are_reported_together_in_stable_order(
    tmp_path: Path,
) -> None:
    with pytest.raises(CheckFailed) as error:
        simple_template().bind(subject="q0").bind(zeta=1, alpha=2)

    problem = error.value.problems[0]
    assert problem.code == "experiment_unknown_input"
    assert problem.location == model_location("experiment", "inputs")
    assert problem.message.endswith("alpha, zeta")


def test_template_definition_reports_literal_errors() -> None:
    with pytest.raises(CheckFailed) as error:

        @sc.experiment(id="test.invalid-template", kind="invalid-template")
        def template(
            experiment: sc.ExperimentContext,
            count: sc.Input[int] = "not-an-int",  # pyright: ignore[reportArgumentType]
        ) -> None:
            del experiment, count

    assert [problem.code for problem in error.value.problems] == [
        "module_input_type_mismatch",
    ]
    assert {problem.phase for problem in error.value.problems} == {
        ProblemPhase.DEFINITION
    }


def test_template_bind_rejects_known_input_errors_without_requiring_missing() -> None:
    @sc.experiment(id="test.early-bind", kind="early-bind")
    def template(
        experiment: sc.ExperimentContext,
        count: sc.Input[int],
        required_later: sc.Input[float],
    ) -> None:
        del experiment, count, required_later

    # Missing values remain legal while an invocation is being assembled.
    partial = template.bind()
    with pytest.raises(CheckFailed) as error:
        partial.bind(count="not-an-int")

    assert [problem.code for problem in error.value.problems] == [
        "module_input_type_mismatch",
    ]

    with pytest.raises(TypeError, match="unexpected keyword argument 'zeta'"):
        template.bind(
            count=1,
            zeta=1,
            alpha=2,
        )


def test_grid_rejects_duplicate_axis_ids() -> None:
    first = sc.coordinate("first", sc.ScalarType(sc.FloatType()))
    second = sc.coordinate("second", sc.ScalarType(sc.FloatType()))

    with pytest.raises(ValueError, match="grid axis ids must be unique"):

        @sc.experiment(id="test.invalid-default-scans", kind="invalid-default-scans")
        def template(experiment: sc.ExperimentContext) -> None:
            experiment.grid(
                sc.axis(first, (1.0, 2.0)),
                sc.axis(second, (1.0,)),
                sc.axis(first, (3.0,)),
            )


def test_repeated_axis_overrides_use_the_latest_value() -> None:
    point = sc.coordinate("point", sc.ScalarType(sc.FloatType()))

    @sc.experiment(id="test.repeated-scan-overrides", kind="repeated-scan-overrides")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.grid(sc.axis(point, (1.0,)))

    invocation = (
        template().with_axis(sc.axis(point, (2.0,))).with_axis(sc.axis(point, (3.0,)))
    )

    assert invocation.point_plan.domain.axes == (sc.axis(point, (3.0,)),)
    compile_invocation(invocation)


def test_authoring_compile_precedes_config_binding(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(CheckFailed) as error:
        compiled = compile_invocation(simple_template().bind())
        bind_program(
            compiled.program,
            build_config_environment(load_config()),
        )

    assert error.value.problems[0].code == "experiment_missing_input"


def test_check_experiment_resolves_template_invocation_with_config_snapshot(
    tmp_path: Path,
) -> None:
    config = load_config()
    composition = compose_test_instruments(
        config=config,
        provider=TestSignalInstrumentProvider(),
    )
    result = check_experiment(
        simple_template().bind(subject="q0"),
        system=composition.system,
        services=sqlite_project_services(tmp_path),
        config=config,
    )

    assert result.preview is not None
    assert result.preview.experiment_id == simple_template().id


def _module_consuming_input() -> sc.ExperimentModule[None, ...]:
    @sc.module(id="test.consumed-input")
    def module(context: sc.ModuleContext, value: float) -> None:
        context.compute(
            "consume-value",
            fn=_identity_value,
            inputs={"value": value},
            output_type=sc.ScalarType(sc.FloatType()),
        )

    return module


def test_consumed_module_input_requires_binding_at_the_python_call() -> None:
    module = _module_consuming_input()

    with pytest.raises(TypeError, match="missing a required argument: 'value'"):
        module()


def test_declared_module_input_requires_binding_even_when_unused() -> None:
    @sc.module(id="test.unused-input")
    def module(context: sc.ModuleContext, unused: float) -> None:
        del context, unused

    with pytest.raises(TypeError, match="missing a required argument: 'unused'"):
        module()  # pyright: ignore[reportCallIssue]


def test_unused_child_binding_accepts_an_explicit_outer_value() -> None:
    @sc.module(id="test.unused-child")
    def child(context: sc.ModuleContext, child_value: float) -> None:
        del context, child_value

    @sc.module(id="test.unused-child-root")
    def outer(context: sc.ModuleContext, outer_value: float) -> None:
        context.use(child.instantiate("unused-child", child_value=outer_value))

    @sc.experiment(id="test.unused-child", kind="input")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.use(outer(1.0))

    bind_invocation(template(), config_profile=load_config())


def test_unused_child_expression_binding_accepts_an_explicit_outer_value() -> None:
    @sc.module(id="test.unused-child-expression")
    def child(context: sc.ModuleContext, child_value: float) -> None:
        del context, child_value

    @sc.module(id="test.unused-child-expression-root")
    def outer(context: sc.ModuleContext, outer_value: float) -> None:
        context.use(
            child.instantiate(
                "unused-child",
                child_value=outer_value + 1.0,
            )
        )

    @sc.experiment(id="test.unused-child-expression", kind="input")
    def template(experiment: sc.ExperimentContext) -> None:
        experiment.use(outer(1.0))

    bind_invocation(template(), config_profile=load_config())


def test_scan_point_does_not_implicitly_bind_consumed_module_input() -> None:
    module = _module_consuming_input()
    point = sc.coordinate("value", sc.ScalarType(sc.FloatType()))

    with pytest.raises(TypeError, match="missing a required argument: 'value'"):

        @sc.experiment(id="test.point-input", kind="input")
        def template(experiment: sc.ExperimentContext) -> None:
            experiment.use(module())
            experiment.grid(sc.axis(point, (1.0,)))


def _identity_value(value: object) -> object:
    return value
