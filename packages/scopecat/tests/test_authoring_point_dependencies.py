from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.authoring._module_composition import assemble_module_internal
from scopecat.authoring._resolution import resolve_experiment
from scopecat.errors import ValidationFailed
from tests.support.authoring import load_config

_FREQUENCY_TYPE = sc.ScalarType(sc.QuantityType(unit="GHz"))


def _identity(value: object) -> object:
    return value


def _point_module(
    point: sc.ValueRef,
    *,
    module_id: str,
) -> sc.ExperimentModule:
    consume = sc.compute(
        f"{module_id}.consume",
        fn=_identity,
        inputs={"value": point},
        output_type=point.value_type,
    )
    return sc.module(module_id).computes(consume).build()


def _resolve(module: sc.ExperimentModule, *, scan: sc.Scan | None = None) -> None:
    builder = module.template("test.point-dependency", kind="point_dependency")
    if scan is not None:
        builder = builder.scan(scan)
    invocation = builder.build().bind()
    resolve_experiment(
        invocation,
        workspace=Path("/tmp/scopecat-test"),
        config_profile=load_config(),
    )


def test_direct_point_dependency_requires_a_scan() -> None:
    frequency = sc.point("frequency", _FREQUENCY_TYPE)
    module = _point_module(frequency, module_id="test.direct-point")

    with pytest.raises(ValidationFailed) as error:
        _resolve(module)

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "experiment_point_dependency_missing"
    assert diagnostic.path == "scans.frequency"


def test_direct_point_dependency_rejects_same_id_with_wrong_type() -> None:
    frequency = sc.point("frequency", _FREQUENCY_TYPE)
    module = _point_module(frequency, module_id="test.mistyped-point")
    wrong_frequency = sc.point(
        "frequency",
        sc.ScalarType(sc.StringType()),
    )

    with pytest.raises(ValidationFailed) as error:
        _resolve(module, scan=sc.axis(wrong_frequency, ("5 GHz",)))

    diagnostic = error.value.diagnostics[0]
    assert diagnostic.code == "experiment_point_dependency_type_mismatch"
    assert diagnostic.path == "scans.frequency"
    assert "Scalar[String]" in diagnostic.message
    assert "Scalar[Quantity[GHz]]" in diagnostic.message


def test_direct_point_dependency_accepts_matching_scan() -> None:
    frequency = sc.point("frequency", _FREQUENCY_TYPE)
    module = _point_module(frequency, module_id="test.matching-point")

    _resolve(module, scan=sc.axis(frequency, (5.0,), unit="GHz"))


def test_nested_module_preserves_bound_point_dependency() -> None:
    child_frequency = sc.input("frequency", _FREQUENCY_TYPE)
    consume = sc.compute(
        "test.point-child.consume",
        fn=_identity,
        inputs={"value": child_frequency},
        output_type=child_frequency.value_type,
    )
    child = (
        sc.module("test.point-child").inputs(child_frequency).computes(consume).build()
    )
    parent_frequency = sc.point("frequency", _FREQUENCY_TYPE)
    parent = (
        sc.module("test.point-parent").use(child(frequency=parent_frequency)).build()
    )

    assembly = assemble_module_internal(parent)
    assert tuple(
        (dependency.id, dependency.value_type)
        for dependency in assembly.point_dependencies
    ) == (("frequency", _FREQUENCY_TYPE),)

    with pytest.raises(ValidationFailed) as error:
        _resolve(parent)
    assert error.value.diagnostics[0].code == "experiment_point_dependency_missing"

    _resolve(
        parent,
        scan=sc.axis(parent_frequency, (5.0,), unit="GHz"),
    )
