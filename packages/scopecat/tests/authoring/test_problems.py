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
from tests.testkit.authoring import load_config, simple_template
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
    module = sc.module("test.invalid-template").inputs(count).build()

    with pytest.raises(CheckFailed) as error:
        (
            module.template("test.invalid-template", kind="invalid-template")
            .inputs(
                sc.InputDescription(id="label"),
                sc.InputDescription(id="label"),
                sc.InputDescription(id="count", default="not-an-int"),
            )
            .record_product("missing")
            .build()
        )

    assert [problem.code for problem in error.value.problems] == [
        "experiment_template_input_duplicate",
        "module_input_type_mismatch",
        "module_product_unknown",
    ]


def test_template_bind_rejects_known_input_errors_without_requiring_missing() -> None:
    count = sc.input("count", sc.ScalarType(sc.IntType()))
    template = (
        sc.module("test.early-bind")
        .inputs(count)
        .build()
        .template("test.early-bind", kind="early-bind")
        .input("required-later")
        .build()
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

    with pytest.raises(CheckFailed) as error:
        (
            sc.module("test.invalid-default-scans")
            .template("test.invalid-default-scans", kind="invalid-default-scans")
            .scan(sc.zip(sc.axis(first, (1.0, 2.0)), sc.axis(second, (1.0,))))
            .scan(first, (3.0,))
            .build()
        )

    assert [problem.code for problem in error.value.problems] == [
        "scan_axis_duplicate",
        "scan_zip_length_mismatch",
    ]


def test_template_build_validates_product_and_record_selection_names() -> None:
    module = sc.module("test.invalid-selections").product("signal", "phase").build()

    with pytest.raises(CheckFailed) as error:
        (
            module.template("test.invalid-selections", kind="invalid-selections")
            .record_product("signal")
            .record_product("signal", record_id="renamed")
            .record_product("phase", record_id="renamed")
            .build()
        )

    assert [problem.code for problem in error.value.problems] == [
        "module_record_duplicate",
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
    assert result.preview.experiment_id == "authored-simple-scan"


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
    assert result.preview.experiment_id == "authored-simple-scan"


def _module_consuming_input() -> tuple[sc.ExperimentModule, sc.ValueRef]:
    value = sc.input("value", sc.ScalarType(sc.FloatType()))
    consume = sc.compute(
        "consume-value",
        fn=_identity_value,
        inputs={"value": value},
        output_type=value.value_type,
    )
    module = sc.module("test.consumed-input").inputs(value).computes(consume).build()
    return module, value


def test_consumed_module_input_requires_binding_during_authoring_compile() -> None:
    module, _value = _module_consuming_input()
    invocation = module.template("test.consumed-input", kind="input").build().bind()

    with pytest.raises(CheckFailed) as error:
        compile_prepared_invocation(prepare_invocation(invocation))

    problem = error.value.problems[0]
    assert problem.code == "module_input_binding_missing"
    assert problem.phase is ProblemPhase.AUTHORING
    assert problem.location == model_location("inputs")


def test_unconsumed_module_input_does_not_require_binding(tmp_path: Path) -> None:
    value = sc.input("unused", sc.ScalarType(sc.FloatType()))
    module = sc.module("test.unused-input").inputs(value).build()
    invocation = module.template("test.unused-input", kind="input").build().bind()

    resolve_experiment(invocation, config_profile=load_config())


def test_unused_child_binding_does_not_consume_outer_input(tmp_path: Path) -> None:
    child_value = sc.input("child_value", sc.ScalarType(sc.FloatType()))
    outer_value = sc.input("outer_value", sc.ScalarType(sc.FloatType()))
    child = sc.module("test.unused-child").inputs(child_value).build()
    outer = (
        sc.module("test.unused-child-root")
        .inputs(outer_value)
        .use(child.instantiate("unused-child", child_value=outer_value))
        .build()
    )
    invocation = outer.template("test.unused-child", kind="input").build().bind()

    resolve_experiment(invocation, config_profile=load_config())


def test_unused_child_expression_binding_does_not_consume_outer_input(
    tmp_path: Path,
) -> None:
    value_type = sc.ScalarType(sc.FloatType())
    child_value = sc.input("child_value", value_type)
    outer_value = sc.input("outer_value", value_type)
    child = sc.module("test.unused-child-expression").inputs(child_value).build()
    outer = (
        sc.module("test.unused-child-expression-root")
        .inputs(outer_value)
        .use(
            child.instantiate(
                "unused-child",
                child_value=outer_value + 1.0,
            )
        )
        .build()
    )
    invocation = (
        outer.template("test.unused-child-expression", kind="input").build().bind()
    )

    resolve_experiment(invocation, config_profile=load_config())


def test_scan_point_satisfies_consumed_module_input(tmp_path: Path) -> None:
    module, _value = _module_consuming_input()
    invocation = (
        module.template("test.point-input", kind="input")
        .scan(
            sc.point("value", sc.ScalarType(sc.FloatType())),
            (1.0,),
        )
        .build()
        .bind()
    )

    resolve_experiment(invocation, config_profile=load_config())


def _identity_value(value: object) -> object:
    return value
