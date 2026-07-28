from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.frontend.resolution import (
    compile_invocation,
    resolve_compiled_invocation,
)
from scopecat.config.environment import build_config_environment
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ProblemPhase,
    model_location,
)
from tests.testkit.authoring import (
    link_invocation,
    load_config,
    simple_template,
    template_fixture,
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
        link_invocation(missing_subject, config_profile=config)
    assert missing_error.value.problems[0].code == ("experiment_missing_input")

    unknown_subject = simple_template().bind(subject="missing")
    with pytest.raises(CheckFailed) as subject_error:
        link_invocation(unknown_subject, config_profile=config)
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
    count = sc.input("count", sc.ScalarType(sc.IntType()))
    module = sc.module_body(id="test.invalid-template").inputs(count).build()

    with pytest.raises(CheckFailed) as error:
        template_fixture(
            module,
            id="test.invalid-template",
            kind="invalid-template",
            defaults={"count": "not-an-int"},
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_input_type_mismatch",
    ]
    assert {problem.phase for problem in error.value.problems} == {
        ProblemPhase.DEFINITION
    }


def test_template_bind_rejects_known_input_errors_without_requiring_missing() -> None:
    count = sc.input("count", sc.ScalarType(sc.IntType()))
    module = sc.module_body(id="test.early-bind").inputs(count).build()
    template = template_fixture(
        module,
        id="test.early-bind",
        kind="early-bind",
        required_inputs=("required_later",),
    )

    # Missing values remain legal while an invocation is being assembled.
    template.bind()

    with pytest.raises(CheckFailed) as error:
        template.bind().bind(count="not-an-int")

    assert [problem.code for problem in error.value.problems] == [
        "module_input_type_mismatch",
    ]

    with pytest.raises(TypeError, match="unexpected keyword argument 'zeta'"):
        template.bind(count=1, zeta=1, alpha=2)


def test_compile_validates_default_scan_axes() -> None:
    first = sc.coordinate("first", sc.ScalarType(sc.FloatType()))
    second = sc.coordinate("second", sc.ScalarType(sc.FloatType()))
    module = sc.module_body(id="test.invalid-default-scans").build()

    template = template_fixture(
        module,
        id="test.invalid-default-scans",
        kind="invalid-default-scans",
        scans=(
            sc.axis(first, (1.0, 2.0)),
            sc.axis(second, (1.0,)),
            sc.axis(first, (3.0,)),
        ),
    )

    with pytest.raises(CheckFailed) as error:
        compile_invocation(template())

    assert [problem.code for problem in error.value.problems] == [
        "scan_axis_duplicate",
    ]


def test_compile_rejects_repeated_scan_overrides_before_merging() -> None:
    point = sc.coordinate("point", sc.ScalarType(sc.FloatType()))
    module = sc.module_body(id="test.repeated-scan-overrides").build()
    template = template_fixture(
        module,
        id="test.repeated-scan-overrides",
        kind="repeated-scan-overrides",
        scans=(sc.axis(point, (1.0,)),),
    )
    invocation = template().scan(sc.axis(point, (2.0,))).scan(sc.axis(point, (3.0,)))

    with pytest.raises(CheckFailed) as error:
        compile_invocation(invocation)

    assert [problem.code for problem in error.value.problems] == [
        "scan_axis_duplicate",
    ]


def test_authoring_compile_precedes_config_linking(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(CheckFailed) as error:
        compiled = compile_invocation(simple_template().bind())
        resolve_compiled_invocation(
            compiled,
            environment=build_config_environment(load_config()),
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
    assert result.preview.experiment_id == simple_template().definition.id


def _module_consuming_input() -> tuple[sc.ExperimentModule[...], sc.ValueRef]:
    value_type = sc.ScalarType(sc.FloatType())
    value = sc.input("value", value_type)
    consume = sc.compute(
        "consume-value",
        fn=_identity_value,
        inputs={"value": value},
        output_type=value_type,
    )
    module = (
        sc.module_body(id="test.consumed-input").inputs(value).computes(consume).build()
    )
    return module, value


def test_consumed_module_input_requires_binding_during_authoring_compile() -> None:
    module, _value = _module_consuming_input()
    invocation = template_fixture(
        module,
        id="test.consumed-input",
        kind="input",
    ).bind()

    with pytest.raises(CheckFailed) as error:
        compile_invocation(invocation)

    problem = error.value.problems[0]
    assert problem.code == "module_input_binding_missing"
    assert problem.phase is ProblemPhase.AUTHORING
    assert problem.location == model_location("inputs")


def test_unconsumed_module_input_does_not_require_binding(tmp_path: Path) -> None:
    value = sc.input("unused", sc.ScalarType(sc.FloatType()))
    module = sc.module_body(id="test.unused-input").inputs(value).build()
    invocation = template_fixture(
        module,
        id="test.unused-input",
        kind="input",
    ).bind()

    link_invocation(invocation, config_profile=load_config())


def test_unused_child_binding_does_not_consume_outer_input(tmp_path: Path) -> None:
    child_value = sc.input("child_value", sc.ScalarType(sc.FloatType()))
    outer_value = sc.input("outer_value", sc.ScalarType(sc.FloatType()))
    child = sc.module_body(id="test.unused-child").inputs(child_value).build()
    outer = (
        sc.module_body(id="test.unused-child-root")
        .inputs(outer_value)
        .use(child.instantiate("unused-child", child_value=outer_value))
        .build()
    )
    invocation = template_fixture(
        outer,
        id="test.unused-child",
        kind="input",
    ).bind()

    link_invocation(invocation, config_profile=load_config())


def test_unused_child_expression_binding_does_not_consume_outer_input(
    tmp_path: Path,
) -> None:
    value_type = sc.ScalarType(sc.FloatType())
    child_value = sc.input("child_value", value_type)
    outer_value = sc.input("outer_value", value_type)
    child = (
        sc.module_body(id="test.unused-child-expression").inputs(child_value).build()
    )
    outer = (
        sc.module_body(id="test.unused-child-expression-root")
        .inputs(outer_value)
        .use(
            child.instantiate(
                "unused-child",
                child_value=outer_value + 1.0,
            )
        )
        .build()
    )
    invocation = template_fixture(
        outer,
        id="test.unused-child-expression",
        kind="input",
    ).bind()

    link_invocation(invocation, config_profile=load_config())


def test_scan_point_does_not_implicitly_bind_consumed_module_input() -> None:
    module, _value = _module_consuming_input()
    invocation = template_fixture(
        module,
        id="test.point-input",
        kind="input",
        scans=(
            sc.axis(
                sc.coordinate("value", sc.ScalarType(sc.FloatType())),
                (1.0,),
            ),
        ),
    ).bind()

    with pytest.raises(CheckFailed) as error:
        compile_invocation(invocation)

    assert error.value.problems[0].code == "module_input_binding_missing"


def _identity_value(value: object) -> object:
    return value
