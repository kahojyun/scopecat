from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend import resolution
from scopecat.compiler.frontend.invocation import prepare_invocation
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location


def _quantity_scan_parts() -> tuple[sc.ValueRef, sc.Compute]:
    quantity_type = sc.ScalarType(sc.QuantityType(unit="GHz"))
    target = sc.point("frequency", quantity_type)
    center = sc.compute(
        "compute-center",
        fn=lambda: sc.Quantity(value=5.0, unit="GHz"),
        output_type=quantity_type,
    )
    return target, center


def test_default_scan_center_rejects_external_operation() -> None:
    target, center = _quantity_scan_parts()
    builder = (
        sc.module("test.scan-stage.default")
        .computes(center)
        .build()
        .template("test.scan-stage.default", kind="scan-stage")
        .scan(
            target,
            center=center.output,
            span=sc.Quantity(value=0.1, unit="GHz"),
            points=3,
        )
    )

    with pytest.raises(CheckFailed) as error:
        builder.build()

    problem = error.value.problems[0]
    assert problem.code == "value_requires_execution"
    assert problem.location == model_location("template", "default_scans", 0, "center")
    assert "scan center" in problem.message


def test_invocation_scan_center_rejects_external_operation() -> None:
    target, center = _quantity_scan_parts()
    template = (
        sc.module("test.scan-stage.invocation")
        .computes(center)
        .build()
        .template("test.scan-stage.invocation", kind="scan-stage")
        .build()
    )
    invocation = template.bind().scan(
        target,
        center=center.output,
        span=sc.Quantity(value=0.1, unit="GHz"),
        points=3,
    )

    with pytest.raises(CheckFailed) as error:
        resolution.compile_prepared_invocation(prepare_invocation(invocation))

    problem = error.value.problems[0]
    assert problem.code == "value_requires_execution"
    assert problem.location == model_location("scans", 0, "center")


def test_parameter_scan_key_rejects_external_operation() -> None:
    entity_type = sc.ScalarType(sc.EntityType())
    key = sc.compute(
        "compute-key",
        fn=lambda: "q0",
        output_type=entity_type,
    )
    target = sc.point("gain", sc.ScalarType(sc.FloatType()))
    scan = sc.param_axis(
        target,
        sc.param_row("device-parameters", device=key.output),
        "gain",
        (0.5, 1.0),
    )
    builder = (
        sc.module("test.scan-stage.parameter-key")
        .computes(key)
        .build()
        .template("test.scan-stage.parameter-key", kind="scan-stage")
        .scan(scan)
    )

    with pytest.raises(CheckFailed) as error:
        builder.build()

    problem = error.value.problems[0]
    assert problem.code == "value_requires_execution"
    assert problem.location == model_location("template", "default_scans", 0, "device")
    assert "parameter scan key" in problem.message


def test_compile_does_not_hide_failures_after_template_expansion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = sc.point("value", sc.ScalarType(sc.FloatType()))
    template = (
        sc.module("test.compile-boundary")
        .template("test.compile-boundary", kind="compile-boundary")
        .build()
    )
    invocation = template.bind().scan(target, (1.0, 2.0))

    def fail_projection(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("late pure-compile failure")

    monkeypatch.setattr(resolution, "project_scan_record", fail_projection)

    with pytest.raises(RuntimeError, match="late pure-compile failure"):
        resolution.compile_prepared_invocation(prepare_invocation(invocation))


def test_compile_does_not_hide_failures_during_scan_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invocation = (
        sc.module("test.compile-early-boundary")
        .template("test.compile-early-boundary", kind="compile-boundary")
        .build()
        .bind()
    )

    def fail_scan_selection(_invocation: object) -> object:
        raise RuntimeError("early pure-compile failure")

    monkeypatch.setattr(resolution, "_effective_scans", fail_scan_selection)

    with pytest.raises(RuntimeError, match="early pure-compile failure"):
        resolution.compile_prepared_invocation(prepare_invocation(invocation))
