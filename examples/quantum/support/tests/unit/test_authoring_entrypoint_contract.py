from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Annotated, cast

import pytest
import scopecat as sc
from scopecat.authoring._products import RecordSelection
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_scalar_value_ref,
)
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    compile_invocation,
)
from scopecat.graph.relations.point_domain import (
    PointAxis,
    PointAxisLinear,
    PointDomainExpr,
    PointUnit,
)

_TEMPLATE_ID = "examples.quantum.x-repetition-iq"
_EXPERIMENT_ID = "x-repetition-iq"
_QUBIT = sc.ScalarType(sc.EntityType(entity_kind="logical_qubit"))
_X_REPETITIONS = sc.coordinate(
    "x_repetitions",
    sc.ScalarType(sc.IntType(minimum=0)),
)


@dataclass(frozen=True)
class _EquivalentAuthoringPaths:
    template: sc.ExperimentInvocation
    scratch: sc.ExperimentInvocation


@pytest.fixture
def equivalent_authoring_paths() -> _EquivalentAuthoringPaths:
    """Describe one experiment through both supported user authoring paths."""

    scan_values = (0, 1, 2, 4)

    @sc.module(id="examples.quantum.contract.capture")
    def capture_module(
        qubit: Annotated[sc.Input[str], _QUBIT],
    ) -> sc.ModuleBuilder:
        return sc.module_body().product("integrated_iq", unit="arb")

    def experiment_body() -> sc.ExperimentBody:
        capture = capture_module.instantiate("capture", qubit="q0")
        return (
            sc.experiment(capture)
            .scan(_X_REPETITIONS, scan_values)
            .record_product(
                capture.products.integrated_iq,
                record_id="integrated_iq",
            )
        )

    @sc.template(id=_TEMPLATE_ID, kind=_EXPERIMENT_ID)
    def template_definition() -> sc.ExperimentBody:
        return experiment_body()

    @sc.scratch(
        id="examples.quantum.x-repetition-iq.scratch",
        kind=_EXPERIMENT_ID,
    )
    def scratch_definition() -> sc.ExperimentBody:
        return experiment_body()

    return _EquivalentAuthoringPaths(
        template=template_definition(),
        scratch=scratch_definition(),
    )


def test_template_and_scratch_compile_to_equivalent_execution_semantics(
    tmp_path: Path,
    equivalent_authoring_paths: _EquivalentAuthoringPaths,
) -> None:
    """Keep both UX forms above one config-free compiler contract."""

    del tmp_path
    template = compile_invocation(equivalent_authoring_paths.template)
    scratch = compile_invocation(equivalent_authoring_paths.scratch)

    assert _execution_semantics(template) == _execution_semantics(scratch)

    assert template.request.experiment_id == _TEMPLATE_ID
    assert scratch.request.experiment_id == "examples.quantum.x-repetition-iq.scratch"


def _execution_semantics(compiled: CompiledInvocation) -> object:
    assembly = compiled.assembly.source
    normalized_assembly = tuple(
        (
            selected.name,
            _normalized_assembly_field(
                selected.name,
                cast("object", getattr(assembly, selected.name)),
            ),
        )
        for selected in fields(assembly)
        if selected.name != "experiment_id"
    )
    normalized_request = compiled.request.model_dump(
        mode="python",
        exclude={"id", "experiment_id", "inputs", "metadata"},
    )
    return normalized_assembly, assembly.inputs, normalized_request


def _normalized_assembly_field(name: str, value: object) -> object:
    if name == "metadata":
        metadata = cast("Mapping[str, object]", value)
        return {
            key: item for key, item in metadata.items() if key not in {"source", "name"}
        }
    if name == "point_domain":
        return _point_domain_semantics(cast("PointDomainExpr[ValueRef]", value))
    if name == "record_selections":
        selections = cast("tuple[RecordSelection, ...]", value)
        return tuple(
            (
                selection.product_id.qualified_name,
                selection.record_id,
                dict(selection.metadata),
            )
            for selection in selections
        )
    return value


def _point_domain_semantics(
    domain: PointDomainExpr[ValueRef],
) -> object:
    """Alpha-normalize transient ValueRef identities."""

    if isinstance(domain, PointUnit):
        return ("unit",)
    if isinstance(domain, PointAxis):
        source = domain.source
        return (
            "axis",
            domain.id,
            domain.value_type,
            (
                (
                    "linear",
                    internal_lower_scalar_value_ref(source.center),
                    source.span,
                    source.count,
                )
                if isinstance(source, PointAxisLinear)
                else ("values", source.values)
            ),
        )
    return (
        "product",
        tuple(_point_domain_semantics(factor) for factor in domain.factors),
    )
