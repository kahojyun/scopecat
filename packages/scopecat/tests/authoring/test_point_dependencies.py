from __future__ import annotations

import pytest

import scopecat as sc
from scopecat.compiler.frontend.elaboration import elaborate_module
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import model_location
from tests.testkit.authoring import link_invocation, load_config

_FREQUENCY_TYPE = sc.ScalarType(sc.QuantityType(unit="GHz"))


def _identity(value: object) -> object:
    return value


def _point_module(
    point: sc.ValueRef,
    *,
    module_id: str,
) -> sc.ExperimentModule[...]:
    consume = sc.compute(
        f"{module_id}.consume",
        fn=_identity,
        inputs={"value": point},
        output_type=_FREQUENCY_TYPE,
    )
    return sc.module_body(id=module_id).computes(consume).build()


def _resolve(module: sc.ExperimentModule[...], *, scan: sc.Scan | None = None) -> None:
    call = module()

    @sc.template(id="test.point-dependency", kind="point_dependency")
    def template_definition() -> sc.ExperimentBody:
        body = sc.experiment(call)
        return body if scan is None else body.scan(scan)

    link_invocation(
        template_definition(),
        config_profile=load_config(),
    )


def test_direct_point_dependency_requires_a_scan() -> None:
    frequency = sc.coordinate("frequency", _FREQUENCY_TYPE)
    module = _point_module(frequency, module_id="test.direct-point")

    with pytest.raises(CheckFailed) as error:
        _resolve(module)

    problem = error.value.problems[0]
    assert problem.code == "experiment_point_dependency_missing"
    assert problem.location == model_location("scans", "frequency")


def test_direct_point_dependency_rejects_same_id_with_wrong_type() -> None:
    frequency = sc.coordinate("frequency", _FREQUENCY_TYPE)
    module = _point_module(frequency, module_id="test.mistyped-point")
    wrong_frequency = sc.coordinate(
        "frequency",
        sc.ScalarType(sc.StringType()),
    )

    with pytest.raises(CheckFailed) as error:
        _resolve(module, scan=sc.axis(wrong_frequency, ("5 GHz",)))

    problem = error.value.problems[0]
    assert problem.code == "experiment_point_dependency_type_mismatch"
    assert problem.location == model_location("scans", "frequency")
    assert "Scalar[String]" in problem.message
    assert "Scalar[Quantity[GHz]]" in problem.message


def test_direct_point_dependency_accepts_matching_scan() -> None:
    frequency = sc.coordinate("frequency", _FREQUENCY_TYPE)
    module = _point_module(frequency, module_id="test.matching-point")

    _resolve(module, scan=sc.axis(frequency, (5.0,), unit="GHz"))


def test_nested_module_preserves_bound_point_dependency() -> None:
    child_frequency = sc.input("frequency", _FREQUENCY_TYPE)
    consume = sc.compute(
        "test.point-child.consume",
        fn=_identity,
        inputs={"value": child_frequency},
        output_type=_FREQUENCY_TYPE,
    )
    child = (
        sc.module_body(id="test.point-child")
        .inputs(child_frequency)
        .computes(consume)
        .build()
    )
    parent_frequency = sc.coordinate("frequency", _FREQUENCY_TYPE)
    parent = (
        sc.module_body(id="test.point-parent")
        .use(child.instantiate("point-child", frequency=parent_frequency))
        .build()
    )

    assembly = elaborate_module(parent.ir)
    assert tuple(
        (dependency.id, dependency.value_type)
        for dependency in assembly.point_dependencies
    ) == (("frequency", _FREQUENCY_TYPE),)

    with pytest.raises(CheckFailed) as error:
        _resolve(parent)
    assert error.value.problems[0].code == "experiment_point_dependency_missing"

    _resolve(
        parent,
        scan=sc.axis(parent_frequency, (5.0,), unit="GHz"),
    )
