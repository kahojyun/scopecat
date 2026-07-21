from __future__ import annotations

from collections.abc import Sequence

import pytest
from hypothesis import given
from hypothesis import strategies as st

import scopecat as sc
from scopecat.authoring._intents import ModuleInputPort
from scopecat.authoring._scan_intents import (
    Scan,
    iter_scan_leaves,
    scan_point_id,
)
from scopecat.authoring._validation import validate_invocation_scans
from scopecat.authoring._value_refs import ValueRef
from scopecat.compiler.frontend.assembly_lowering import (
    lower_point_domain,
    point_domain_input_dependencies,
)
from scopecat.compiler.frontend.elaboration import SemanticExperimentIR
from scopecat.compiler.frontend.resolution import apply_scans
from scopecat.compiler.frontend.scan_dependencies import (
    ScanDependencyError,
    verify_scan_dependencies,
)
from scopecat.compiler.frontend.scan_lowering import lower_scan_points
from scopecat.compiler.relations.evaluation import ParameterRelationData
from scopecat.compiler.relations.point_domain import (
    PointAxis,
    PointDependentProduct,
    PointDomainExpr,
    PointProduct,
    PointRows,
    PointUnit,
    PointZip,
    iter_point_axis_linear,
    point_dependent_product,
)
from scopecat.compiler.relations.verification import RelationTypeBindings
from scopecat.compiler.typed.point_domain import (
    materialize_point_domain,
    verify_point_domain,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import ModelLocation

_FREQUENCY = sc.ScalarType(sc.QuantityType(unit="GHz"))
_DURATION = sc.ScalarType(sc.QuantityType(unit="ns"))


def _point(axis_id: str, *, duration: bool = False):
    return sc.point(axis_id, _DURATION if duration else _FREQUENCY)


def _values(axis_id: str, *, duration: bool = False) -> Scan:
    return sc.axis(
        _point(axis_id, duration=duration),
        [1.0, 2.0],
        unit="ns" if duration else "GHz",
    )


def _dependent(
    axis_id: str,
    dependency_id: str,
    *,
    duration: bool = False,
    direct_point: bool = False,
) -> Scan:
    value_type = _DURATION if duration else _FREQUENCY
    center = (
        _point(dependency_id, duration=duration)
        if direct_point
        else sc.input(dependency_id, value_type)
    )
    return sc.axis(
        _point(axis_id, duration=duration),
        center=center,
        span="2 ns" if duration else "2 GHz",
        points=2,
    )


def _axis_ids(scans: Sequence[Scan]) -> tuple[str, ...]:
    return tuple(
        scan_point_id(leaf) for scan in scans for leaf in iter_scan_leaves(scan)
    )


def _domain_columns(domain: PointDomainExpr[ValueRef]) -> tuple[str, ...]:
    if isinstance(domain, PointUnit):
        return ()
    if isinstance(domain, PointAxis):
        return (domain.id,)
    if isinstance(domain, PointRows):
        return tuple(column.id for column in domain.columns)
    if isinstance(domain, PointProduct):
        return tuple(
            column for factor in domain.factors for column in _domain_columns(factor)
        )
    if isinstance(domain, PointZip):
        return tuple(
            column for source in domain.sources for column in _domain_columns(source)
        )
    return (*_domain_columns(domain.left), *_domain_columns(domain.right))


@given(order=st.permutations(("a", "b", "c")))
def test_generated_dependency_chain_is_declaration_order_independent(
    order: list[str],
) -> None:
    scans = {
        "a": _values("a"),
        "b": _dependent("b", "a"),
        "c": _dependent("c", "b"),
    }
    selected = tuple(scans[axis_id] for axis_id in order)

    graph = verify_scan_dependencies(selected)
    resolved = apply_scans(
        SemanticExperimentIR(experiment_id="test", kind="test"),
        selected,
        inputs={},
    )

    assert tuple(axis.id for axis in graph.axes) == tuple(order)
    assert _axis_ids(graph.scans) == tuple(order)
    assert {(edge.producer_id, edge.consumer_id) for edge in graph.edges} == {
        ("a", "b"),
        ("b", "c"),
    }
    assert _domain_columns(resolved.point_domain) == ("a", "b", "c")


@given(order=st.permutations(("a", "b", "c", "d")))
def test_generated_independent_axes_retain_declaration_order(
    order: list[str],
) -> None:
    graph = verify_scan_dependencies(tuple(_values(axis_id) for axis_id in order))

    assert tuple(axis.id for axis in graph.axes) == tuple(order)
    assert _axis_ids(graph.scans) == tuple(order)


def test_literal_and_parameter_centers_are_not_point_dependencies() -> None:
    literal = sc.axis(
        _point("literal"),
        center=sc.Quantity(value=5.0, unit="GHz"),
        span="2 GHz",
        points=2,
    )
    parameter = sc.axis(
        _point("parameter"),
        center=sc.parameter("center", _FREQUENCY),
        span="2 GHz",
        points=2,
    )

    graph = verify_scan_dependencies((literal, parameter, _values("source")))

    assert _axis_ids(graph.scans) == ("literal", "parameter", "source")
    assert graph.edges == ()


def test_fixed_input_removes_an_otherwise_point_local_dependency() -> None:
    graph = verify_scan_dependencies(
        (_dependent("target", "source"), _values("source")),
        inputs={"source": sc.Quantity(value=5.0, unit="GHz")},
    )

    assert _axis_ids(graph.scans) == ("target", "source")
    assert graph.edges == ()


def test_unbound_scan_center_input_requires_a_point_provider() -> None:
    with pytest.raises(ScanDependencyError) as caught:
        verify_scan_dependencies((_dependent("target", "missing"),))

    assert [issue.code for issue in caught.value.issues] == ["scan_dependency_missing"]


def test_scan_and_base_source_cannot_both_provide_the_same_axis() -> None:
    with pytest.raises(ScanDependencyError) as caught:
        verify_scan_dependencies(
            (_values("shared"),),
            external_point_types={"shared": _FREQUENCY},
        )

    assert [issue.code for issue in caught.value.issues] == [
        "scan_dependency_provider_duplicate"
    ]


@pytest.mark.parametrize(
    ("scans", "code"),
    [
        ((_dependent("a", "a", direct_point=True),), "scan_dependency_self"),
        (
            (
                _dependent("a", "b", direct_point=True),
                _dependent("b", "a", direct_point=True),
            ),
            "scan_dependency_cycle",
        ),
        (
            (_dependent("a", "missing", direct_point=True),),
            "scan_dependency_missing",
        ),
    ],
)
def test_invalid_dependency_graphs_fail_before_relation_lowering(
    scans: tuple[Scan, ...],
    code: str,
) -> None:
    with pytest.raises(ScanDependencyError) as caught:
        verify_scan_dependencies(scans)

    assert code in {issue.code for issue in caught.value.issues}


def test_dependency_provider_type_is_checked_at_the_graph_boundary() -> None:
    consumer = _dependent(
        "duration",
        "source",
        duration=True,
        direct_point=True,
    )

    with pytest.raises(ScanDependencyError) as caught:
        verify_scan_dependencies((_values("source"), consumer))

    assert [issue.code for issue in caught.value.issues] == [
        "scan_dependency_type_mismatch"
    ]


def test_zip_rejects_dependencies_between_positional_branches() -> None:
    zipped = sc.zip(
        _values("source"),
        _dependent("target", "source", direct_point=True),
    )

    with pytest.raises(ScanDependencyError) as caught:
        verify_scan_dependencies((zipped,))

    assert [issue.code for issue in caught.value.issues] == [
        "scan_zip_sibling_dependency"
    ]


def test_zip_branches_can_share_an_external_ancestor() -> None:
    zipped = sc.zip(
        _dependent("left", "outer", direct_point=True),
        _dependent("right", "outer", direct_point=True),
    )

    graph = verify_scan_dependencies(
        (zipped,),
        external_point_types={"outer": _FREQUENCY},
    )

    assert _axis_ids(graph.scans) == ("left", "right")
    assert {(edge.producer_id, edge.consumer_id) for edge in graph.edges} == {
        ("outer", "left"),
        ("outer", "right"),
    }


def test_cartesian_groups_are_flattened_and_ordered_during_domain_composition() -> None:
    grouped = sc.cartesian(
        _dependent("c", "b"),
        sc.cartesian(_dependent("b", "a"), _values("a")),
    )

    graph = verify_scan_dependencies((grouped,))
    resolved = apply_scans(
        SemanticExperimentIR(experiment_id="test", kind="test"),
        (grouped,),
        inputs={},
    )

    assert _axis_ids(graph.scans) == ("c", "b", "a")
    assert len(graph.scans) == 1
    assert _domain_columns(resolved.point_domain) == ("a", "b", "c")


def test_positional_group_aggregate_cycle_is_rejected() -> None:
    positional = sc.zip(
        _dependent("a", "b", direct_point=True),
        _values("c"),
    )
    b = _dependent("b", "c", direct_point=True)

    with pytest.raises(CheckFailed) as caught:
        apply_scans(
            SemanticExperimentIR(experiment_id="test", kind="test"),
            (positional, b),
            inputs={},
        )

    assert [problem.code for problem in caught.value.problems] == [
        "scan_dependency_composition_cycle"
    ]


def test_scan_composition_cycle_is_not_attributed_to_a_downstream_base() -> None:
    positional = sc.zip(
        _dependent("a", "b", direct_point=True),
        _values("c"),
    )
    assembly = SemanticExperimentIR(
        experiment_id="test",
        kind="test",
        input_ports=(ModuleInputPort("a", _FREQUENCY),),
        point_domain=lower_scan_points(_dependent("base", "a")),
    )

    with pytest.raises(CheckFailed) as caught:
        apply_scans(
            assembly,
            (positional, _dependent("b", "c", direct_point=True)),
            inputs={},
        )

    problem = caught.value.problems[0]
    assert problem.code == "scan_dependency_composition_cycle"
    assert isinstance(problem.location, ModelLocation)
    assert problem.location.root == "scans"


def test_dependency_errors_are_projected_as_authoring_problems() -> None:
    assembly = SemanticExperimentIR(experiment_id="test", kind="test")
    scans = (
        _dependent("a", "b", direct_point=True),
        _dependent("b", "a", direct_point=True),
    )

    with pytest.raises(CheckFailed) as caught:
        apply_scans(assembly, scans, inputs={})

    assert "scan_dependency_cycle" in {
        problem.code for problem in caught.value.problems
    }
    assert all(
        isinstance(problem.location, ModelLocation) and problem.location.root == "scans"
        for problem in caught.value.problems
    )


def test_independent_scans_remain_an_explicit_product() -> None:
    assembly = SemanticExperimentIR(experiment_id="test", kind="test")

    resolved = apply_scans(
        assembly,
        (_values("left"), _values("right")),
        inputs={},
    )

    assert isinstance(resolved.point_domain, PointProduct)
    assert _domain_columns(resolved.point_domain) == ("left", "right")


def test_scan_dependency_chain_remains_directional_in_domain_ir() -> None:
    assembly = SemanticExperimentIR(experiment_id="test", kind="test")

    resolved = apply_scans(
        assembly,
        (
            _dependent("third", "second", direct_point=True),
            _dependent("second", "first", direct_point=True),
            _values("first"),
        ),
        inputs={},
    )

    assert isinstance(resolved.point_domain, PointDependentProduct)
    assert isinstance(resolved.point_domain.left, PointDependentProduct)
    assert _domain_columns(resolved.point_domain) == ("first", "second", "third")

    compiled = lower_point_domain(
        resolved.point_domain,
        inputs={},
        type_bindings=RelationTypeBindings(),
    )
    verified = verify_point_domain(compiled, program_id="test")
    materialized = materialize_point_domain(
        verified,
        ParameterRelationData(),
    )

    assert [path for path, _source in iter_point_axis_linear(verified.root)] == [
        ("left", "right"),
        ("right",),
    ]
    assert len(materialized.points) == 8
    assert tuple(materialized.points[0].row) == ("first", "second", "third")


def test_scan_input_dependency_binds_to_its_point_provider() -> None:
    assembly = SemanticExperimentIR(experiment_id="test", kind="test")

    resolved = apply_scans(
        assembly,
        (_dependent("second", "first"), _values("first")),
        inputs={},
    )
    compiled = lower_point_domain(
        resolved.point_domain,
        inputs=resolved.inputs,
        type_bindings=RelationTypeBindings(),
    )
    materialized = materialize_point_domain(
        verify_point_domain(compiled, program_id="test"),
        ParameterRelationData(),
    )

    assert set(resolved.inputs) == {"first"}
    assert len(materialized.points) == 4
    assert tuple(materialized.points[0].row) == ("first", "second")


def test_positional_scan_group_remains_an_explicit_zip() -> None:
    assembly = SemanticExperimentIR(experiment_id="test", kind="test")

    resolved = apply_scans(
        assembly,
        (sc.zip(_values("left"), _values("right")),),
        inputs={},
    )

    assert isinstance(resolved.point_domain, PointZip)
    assert _domain_columns(resolved.point_domain) == ("left", "right")


def test_nested_cartesian_region_is_scheduled_inside_a_zip() -> None:
    assembly = SemanticExperimentIR(experiment_id="test", kind="test")
    nested = sc.cartesian(
        _dependent("dependent", "source", direct_point=True),
        _values("source"),
    )
    positional = sc.zip(
        nested,
        sc.axis(_point("position"), [1.0, 2.0, 3.0, 4.0], unit="GHz"),
    )

    resolved = apply_scans(assembly, (positional,), inputs={})

    assert isinstance(resolved.point_domain, PointZip)
    assert isinstance(resolved.point_domain.sources[0], PointDependentProduct)
    assert _domain_columns(resolved.point_domain) == (
        "source",
        "dependent",
        "position",
    )


def test_base_point_source_and_scans_share_one_topological_order() -> None:
    base = lower_scan_points(_dependent("base", "a"))
    assembly = SemanticExperimentIR(
        experiment_id="test",
        kind="test",
        input_ports=(ModuleInputPort("a", _FREQUENCY),),
        point_domain=base,
    )

    resolved = apply_scans(
        assembly,
        (_values("independent"), _values("a")),
        inputs={},
    )

    assert isinstance(resolved.point_domain, PointDependentProduct)
    assert _domain_columns(resolved.point_domain) == ("independent", "a", "base")
    assert point_domain_input_dependencies(resolved.point_domain, inputs={}) == set()


def test_scan_can_depend_on_a_base_point_source() -> None:
    assembly = SemanticExperimentIR(
        experiment_id="test",
        kind="test",
        point_domain=lower_scan_points(_values("base")),
    )

    resolved = apply_scans(
        assembly,
        (_dependent("scan", "base", direct_point=True),),
        inputs={},
    )

    assert isinstance(resolved.point_domain, PointDependentProduct)
    assert _domain_columns(resolved.point_domain) == ("base", "scan")


def test_scan_input_dependency_binds_to_a_base_point_provider() -> None:
    assembly = SemanticExperimentIR(
        experiment_id="test",
        kind="test",
        point_domain=lower_scan_points(_values("base")),
    )

    resolved = apply_scans(
        assembly,
        (_dependent("scan", "base"),),
        inputs={},
    )
    compiled = lower_point_domain(
        resolved.point_domain,
        inputs=resolved.inputs,
        type_bindings=RelationTypeBindings(),
    )
    materialized = materialize_point_domain(
        verify_point_domain(compiled, program_id="test"),
        ParameterRelationData(),
    )

    assert set(resolved.inputs) == {"base"}
    assert len(materialized.points) == 4
    assert tuple(materialized.points[0].row) == ("base", "scan")


def test_base_and_scan_dependency_cycle_is_an_authoring_problem() -> None:
    assembly = SemanticExperimentIR(
        experiment_id="test",
        kind="test",
        input_ports=(ModuleInputPort("scan", _FREQUENCY),),
        point_domain=lower_scan_points(_dependent("base", "scan")),
    )

    with pytest.raises(CheckFailed) as caught:
        apply_scans(
            assembly,
            (_dependent("scan", "base", direct_point=True),),
            inputs={},
        )

    assert [problem.code for problem in caught.value.problems] == [
        "scan_dependency_composition_cycle"
    ]


def test_base_only_missing_input_fails_at_the_dependency_boundary() -> None:
    assembly = SemanticExperimentIR(
        experiment_id="test",
        kind="test",
        point_domain=lower_scan_points(_dependent("base", "missing")),
    )

    with pytest.raises(CheckFailed) as caught:
        apply_scans(assembly, (), inputs={})

    assert [problem.code for problem in caught.value.problems] == [
        "scan_dependency_missing"
    ]


def test_base_only_self_dependency_is_rejected() -> None:
    assembly = SemanticExperimentIR(
        experiment_id="test",
        kind="test",
        point_domain=lower_scan_points(_dependent("base", "base", direct_point=True)),
    )

    with pytest.raises(CheckFailed) as caught:
        apply_scans(assembly, (), inputs={})

    assert [problem.code for problem in caught.value.problems] == [
        "scan_dependency_self"
    ]


@pytest.mark.parametrize("direct_point", [False, True])
def test_dependent_product_closes_the_right_source_point_dependency(
    direct_point: bool,
) -> None:
    base_domain = point_dependent_product(
        lower_scan_points(_values("source")),
        lower_scan_points(_dependent("target", "source", direct_point=direct_point)),
    )
    assembly = SemanticExperimentIR(
        experiment_id="test",
        kind="test",
        point_domain=base_domain,
    )

    resolved = apply_scans(assembly, (), inputs={})

    assert resolved.point_domain == base_domain
    assert point_domain_input_dependencies(resolved.point_domain, inputs={}) == set()


def test_invocation_zip_length_mismatch_is_a_stable_problem() -> None:
    scans = (
        sc.zip(
            _values("left"),
            sc.axis(_point("right"), [1.0], unit="GHz"),
        ),
    )

    with pytest.raises(CheckFailed) as caught:
        validate_invocation_scans(scans)

    assert [problem.code for problem in caught.value.problems] == [
        "scan_zip_length_mismatch"
    ]
