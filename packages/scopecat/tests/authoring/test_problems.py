from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.frontend.environment import validate_config_environment
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.compiler.frontend.resolution import (
    compile_prepared_invocation,
    resolve_prepared_invocation,
)
from scopecat.composition.local import local_workspace_services
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.planning.authoring import resolve_experiment
from scopecat.runs.service import check_experiment
from tests.testkit.authoring import load_config, simple_template, template_fixture
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.signal_instruments import TestSignalInstrumentProvider


def test_template_missing_input_and_unknown_subject_report_stable_problems(
    tmp_path: Path,
) -> None:
    config = load_config()
    missing_subject = simple_template().bind()
    with pytest.raises(CheckFailed) as missing_error:
        resolve_experiment(missing_subject, config_profile=config)
    assert missing_error.value.problems[0].code == ("experiment_template_missing_input")

    unknown_subject = simple_template().bind(subject="missing")
    with pytest.raises(CheckFailed) as subject_error:
        resolve_experiment(unknown_subject, config_profile=config)
    assert subject_error.value.problems[0].code == "unknown_authoring_entity"


def test_template_unknown_inputs_are_reported_together_in_stable_order(
    tmp_path: Path,
) -> None:
    with pytest.raises(CheckFailed) as error:
        resolve_experiment(
            simple_template().bind(subject="q0", zeta=1, alpha=2),
            config_profile=load_config(),
        )

    problem = error.value.problems[0]
    assert problem.code == "experiment_template_unknown_input"
    assert problem.location == model_location("template", "inputs")
    assert problem.message.endswith("alpha, zeta")


def test_template_definition_reports_config_free_errors_together() -> None:
    count = sc.input("count", sc.ScalarType(sc.IntType()))
    module = sc.module_body(id="test.invalid-template").inputs(count).build()

    with pytest.raises(CheckFailed) as error:
        template_fixture(
            module,
            id="test.invalid-template",
            kind="invalid-template",
            inputs=(
                sc.InputDescription(id="label"),
                sc.InputDescription(id="label"),
                sc.InputDescription(id="count", default="not-an-int"),
            ),
            records=(sc.record_product("missing"),),
        )

    assert [problem.code for problem in error.value.problems] == [
        "experiment_template_input_duplicate",
        "module_input_type_mismatch",
        "module_product_unknown",
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
        inputs=(sc.InputDescription(id="required-later"),),
    )

    # Missing values remain legal while an invocation is being assembled.
    template.bind()

    with pytest.raises(CheckFailed) as error:
        template.bind(count="not-an-int", zeta=1, alpha=2)

    assert [problem.code for problem in error.value.problems] == [
        "experiment_template_unknown_input",
        "module_input_type_mismatch",
    ]
    assert error.value.problems[0].message.endswith("alpha, zeta")


def test_template_build_validates_default_scan_shape() -> None:
    first = sc.point("first", sc.ScalarType(sc.FloatType()))
    second = sc.point("second", sc.ScalarType(sc.FloatType()))
    module = sc.module_body(id="test.invalid-default-scans").build()

    with pytest.raises(CheckFailed) as error:
        template_fixture(
            module,
            id="test.invalid-default-scans",
            kind="invalid-default-scans",
            scans=(
                sc.zip(sc.axis(first, (1.0, 2.0)), sc.axis(second, (1.0,))),
                sc.axis(first, (3.0,)),
            ),
        )

    assert [problem.code for problem in error.value.problems] == [
        "scan_axis_duplicate",
        "scan_zip_length_mismatch",
    ]


def test_template_build_validates_product_and_record_selection_names() -> None:
    module = (
        sc.module_body(id="test.invalid-selections").product("signal", "phase").build()
    )

    with pytest.raises(CheckFailed) as error:
        template_fixture(
            module,
            id="test.invalid-selections",
            kind="invalid-selections",
            records=(
                sc.record_product("signal"),
                sc.record_product("signal", record_id="renamed"),
                sc.record_product("phase", record_id="renamed"),
            ),
        )

    assert [problem.code for problem in error.value.problems] == [
        "template_record_duplicate",
    ]


def test_authoring_compile_precedes_config_validity_check(tmp_path: Path) -> None:
    valid_environment = validate_config_environment(load_config())
    invalid_environment = replace(
        valid_environment,
        problems=(
            blocking_problem(
                code="test_invalid_config",
                message="invalid config for ordering test",
                category=ProblemCategory.INVALID_INPUT,
                phase=ProblemPhase.CONFIGURATION,
                location=model_location("config"),
            ),
        ),
    )

    with pytest.raises(CheckFailed) as error:
        resolve_prepared_invocation(
            prepare_invocation(simple_template().bind()),
            environment=invalid_environment,
        )

    assert error.value.problems[0].code == "experiment_template_missing_input"


def test_check_experiment_resolves_template_invocation_with_config_profile(
    tmp_path: Path,
) -> None:
    result = check_experiment(
        prepare_invocation(simple_template().bind(subject="q0")),
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        services=local_workspace_services(tmp_path),
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    assert result.preview is not None
    assert result.preview.experiment_id == simple_template().id


def test_check_experiment_resolves_template_invocation_with_config_snapshot(
    tmp_path: Path,
) -> None:
    result = check_experiment(
        prepare_invocation(simple_template().bind(subject="q0")),
        system=sc.ExperimentSystem(provider=TestSignalInstrumentProvider()),
        services=local_workspace_services(tmp_path),
        config_profile=load_config(),
    )

    assert result.preview is not None
    assert result.preview.experiment_id == simple_template().id


def _module_consuming_input() -> tuple[sc.ExperimentModule, sc.ValueRef]:
    value = sc.input("value", sc.ScalarType(sc.FloatType()))
    consume = sc.compute(
        "consume-value",
        fn=_identity_value,
        inputs={"value": value},
        output_type=value.value_type,
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
        compile_prepared_invocation(prepare_invocation(invocation))

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

    resolve_experiment(invocation, config_profile=load_config())


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

    resolve_experiment(invocation, config_profile=load_config())


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

    resolve_experiment(invocation, config_profile=load_config())


def test_scan_point_satisfies_consumed_module_input(tmp_path: Path) -> None:
    module, _value = _module_consuming_input()
    invocation = template_fixture(
        module,
        id="test.point-input",
        kind="input",
        scans=(
            sc.axis(
                sc.point("value", sc.ScalarType(sc.FloatType())),
                (1.0,),
            ),
        ),
    ).bind()

    resolve_experiment(invocation, config_profile=load_config())


def _identity_value(value: object) -> object:
    return value
