from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path
from typing import cast

import pytest
import scopecat as sc
from scopecat.authoring._record_intents import ProductSelectionIntent
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_lower_table_value_ref,
)
from scopecat.compiler.frontend.invocation import PreparedInvocation
from scopecat.compiler.frontend.resolution import (
    CompiledInvocation,
    compile_prepared_invocation,
)
from scopecat.compiler.relations.point_domain import (
    PointDependentProduct,
    PointDomainExpr,
    PointProduct,
    PointRelationRows,
    PointUnit,
)

_TEMPLATE_ID = "examples.quantum.x-repetition-iq"
_EXPERIMENT_ID = "x-repetition-iq"
_SCRATCH_NAME = "x repetition iq"
_X_REPETITIONS = sc.point(
    "x_repetitions",
    sc.ScalarType(sc.IntType(minimum=0)),
)


@dataclass(frozen=True)
class _EquivalentAuthoringPaths:
    template: sc.ExperimentInvocation
    scratch: sc.Experiment


@pytest.fixture
def equivalent_authoring_paths(tmp_path: Path) -> _EquivalentAuthoringPaths:
    """Describe one experiment through both supported user authoring paths."""

    qubit = sc.input(
        "qubit",
        sc.ScalarType(sc.EntityType(entity_kind="logical_qubit")),
    )
    capture_module = (
        sc.module("examples.quantum.contract.capture")
        .inputs(qubit)
        .product("integrated_iq", unit="arb")
        .build()
    )
    capture = capture_module.instantiate("capture", qubit=qubit)
    scan_values = (0, 1, 2, 4)

    template = (
        sc.module("examples.quantum.contract.root")
        .inputs(qubit)
        .use(capture)
        .template(_TEMPLATE_ID, kind=_EXPERIMENT_ID)
        .experiment_id(_EXPERIMENT_ID)
        .inputs(sc.InputDescription(id="qubit"))
        .scan(_X_REPETITIONS, scan_values)
        .record_product(
            capture.products.integrated_iq,
            record_id="integrated_iq",
        )
        .build()
        .bind(qubit="q0")
    )
    scratch = (
        sc.open(tmp_path)
        .experiment(_SCRATCH_NAME)
        .entity("qubit", "q0", entity_kind="logical_qubit")
        .use(capture)
        .scan(_X_REPETITIONS, scan_values)
        .record_product(
            capture.products.integrated_iq,
            record_id="integrated_iq",
        )
    )
    return _EquivalentAuthoringPaths(template=template, scratch=scratch)


def test_template_and_scratch_compile_to_equivalent_execution_semantics(
    tmp_path: Path,
    equivalent_authoring_paths: _EquivalentAuthoringPaths,
) -> None:
    """Keep both UX forms above one config-free compiler contract.

    This deliberately stops before config linking or target execution.  The
    future fake AWG + acquisition-card example can replace the tiny capture
    module without changing what this contract considers entrypoint-neutral.
    """

    workspace = sc.open(tmp_path)
    template = _compile_through_workspace(
        workspace,
        equivalent_authoring_paths.template,
    )
    scratch = _compile_through_workspace(
        workspace,
        equivalent_authoring_paths.scratch,
    )

    assert _execution_semantics(template) == _execution_semantics(scratch)

    # These fields retain how the user entered the common compiler pipeline;
    # they are provenance, not a second execution model.
    assert template.request.template_id == _TEMPLATE_ID
    assert scratch.request.template_id == "scopecat.workspace.experiment"
    assert scratch.request.template_inputs["name"] == _SCRATCH_NAME


def _compile_through_workspace(
    workspace: sc.Workspace,
    experiment: sc.ExperimentInvocation | sc.Experiment,
) -> CompiledInvocation:
    prepared_handle = workspace.prepare(experiment)
    prepared = cast(
        "object", object.__getattribute__(prepared_handle, "_prepared_invocation")
    )
    assert isinstance(prepared, PreparedInvocation)
    return compile_prepared_invocation(prepared)


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
    )
    normalized_request = compiled.request.model_dump(
        mode="python",
        exclude={"id", "template_id", "template_inputs", "metadata"},
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
        selections = cast("tuple[ProductSelectionIntent, ...]", value)
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
    """Alpha-normalize transient relation-use and ValueRef identities."""

    if isinstance(domain, PointUnit):
        return ("unit",)
    if isinstance(domain, PointRelationRows):
        return (
            "rows",
            internal_lower_table_value_ref(domain.rows),
            domain.rows.value_type,
        )
    if isinstance(domain, PointProduct):
        return (
            "product",
            tuple(_point_domain_semantics(factor) for factor in domain.factors),
        )
    if isinstance(domain, PointDependentProduct):
        return (
            "dependent_product",
            _point_domain_semantics(domain.left),
            _point_domain_semantics(domain.right),
        )
    return (
        "zip",
        tuple(_point_domain_semantics(source) for source in domain.sources),
    )
