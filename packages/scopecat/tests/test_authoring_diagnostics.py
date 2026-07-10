from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat._workflows.runs import preview_experiment
from scopecat.authoring._invocation_plan import prepare_invocation
from scopecat.authoring._resolution import resolve_experiment
from scopecat.errors import ValidationFailed
from tests.support.authoring import (
    EXAMPLE_DIR,
    load_config,
    simple_template,
)


def test_template_missing_input_and_unknown_subject_report_stable_diagnostics(
    tmp_path: Path,
) -> None:
    config = load_config()
    missing_subject = simple_template().bind()
    with pytest.raises(ValidationFailed) as missing_error:
        resolve_experiment(missing_subject, workspace=tmp_path, config_profile=config)
    assert missing_error.value.diagnostics[0].code == (
        "experiment_template_missing_input"
    )

    unknown_subject = simple_template().bind(subject="missing")
    with pytest.raises(ValidationFailed) as subject_error:
        resolve_experiment(unknown_subject, workspace=tmp_path, config_profile=config)
    assert subject_error.value.diagnostics[0].code == "unknown_authoring_entity"


def test_template_unknown_inputs_are_reported_together_in_stable_order(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(
            simple_template().bind(subject="q0", zeta=1, alpha=2),
            workspace=tmp_path,
            config_profile=load_config(),
        )

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "experiment_template_unknown_input"
    assert diagnostic.path == "template.inputs"
    assert diagnostic.message.endswith("alpha, zeta")


def test_preview_experiment_resolves_template_invocation_with_config_profile(
    tmp_path: Path,
) -> None:
    result = preview_experiment(
        prepare_invocation(simple_template().bind(subject="q0")),
        workspace=tmp_path,
        config_profile=EXAMPLE_DIR / "config-profile.json",
    )

    assert result.template_id == "test.simple_scan"
    assert result.experiment_id == "authored-simple-scan"


def test_preview_experiment_resolves_template_invocation_with_config_snapshot(
    tmp_path: Path,
) -> None:
    result = preview_experiment(
        prepare_invocation(simple_template().bind(subject="q0")),
        workspace=tmp_path,
        config_profile=load_config(),
    )

    assert result.template_id == "test.simple_scan"
    assert result.experiment_id == "authored-simple-scan"


def _module_consuming_input() -> tuple[sc.ExperimentModule, sc.ValueRef]:
    value = sc.input("value", sc.ScalarType(sc.FloatType()))
    consume = sc.compute(
        "consume-value",
        fn=lambda value: value,
        inputs={"value": value},
        output_type=value.value_type,
    )
    module = sc.module("test.consumed-input").inputs(value).computes(consume).build()
    return module, value


def test_consumed_module_input_requires_binding_or_point_value(tmp_path: Path) -> None:
    module, _value = _module_consuming_input()
    invocation = module.template("test.consumed-input", kind="input").build().bind()

    with pytest.raises(ValidationFailed) as error:
        resolve_experiment(invocation, workspace=tmp_path, config_profile=load_config())

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "module_input_binding_missing"
    assert diagnostic.path == "inputs"


def test_unconsumed_module_input_does_not_require_binding(tmp_path: Path) -> None:
    value = sc.input("unused", sc.ScalarType(sc.FloatType()))
    module = sc.module("test.unused-input").inputs(value).build()
    invocation = module.template("test.unused-input", kind="input").build().bind()

    resolve_experiment(invocation, workspace=tmp_path, config_profile=load_config())


def test_unused_child_binding_does_not_consume_outer_input(tmp_path: Path) -> None:
    child_value = sc.input("child_value", sc.ScalarType(sc.FloatType()))
    outer_value = sc.input("outer_value", sc.ScalarType(sc.FloatType()))
    child = sc.module("test.unused-child").inputs(child_value).build()
    outer = (
        sc.module("test.unused-child-root")
        .inputs(outer_value)
        .use(child(child_value=outer_value))
        .build()
    )
    invocation = outer.template("test.unused-child", kind="input").build().bind()

    resolve_experiment(invocation, workspace=tmp_path, config_profile=load_config())


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

    resolve_experiment(invocation, workspace=tmp_path, config_profile=load_config())
