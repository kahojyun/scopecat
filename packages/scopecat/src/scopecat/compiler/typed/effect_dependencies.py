"""Typed dependency analysis for effect barriers and target placement."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scopecat.compiler.relations.analysis import PlanReferenceKind
from scopecat.compiler.relations.uses import RelationUse
from scopecat.compiler.semantic.availability import ValueRate
from scopecat.compiler.semantic.compute_result import ComputeResultRef
from scopecat.compiler.semantic.model import ValueId
from scopecat.compiler.semantic.value_expressions import ValueExpr
from scopecat.compiler.typed.action import ActionSpec
from scopecat.compiler.typed.program import CoreProgram, core_state
from scopecat.compiler.typed.state import (
    PhysicalStateResourceTarget,
    SetStateSpec,
    StateSpecVariant,
)


@dataclass(frozen=True, slots=True)
class EffectDependencies:
    """Dependencies whose variation can change an observable effect."""

    point_columns: tuple[str, ...] = ()
    point_compute_results: tuple[str, ...] = ()
    point_parameter_tables: tuple[str, ...] = ()

    @property
    def point_varying(self) -> bool:
        return bool(
            self.point_columns
            or self.point_compute_results
            or self.point_parameter_tables
        )


@dataclass(frozen=True, slots=True)
class EffectBarrierAnalysis:
    """Compiler facts that constrain domain jobs across logical points."""

    state: EffectDependencies
    action_ids: tuple[str, ...] = ()

    @property
    def requires_single_point_regions(self) -> bool:
        return self.state.point_varying or bool(self.action_ids)

    @property
    def reasons(self) -> tuple[str, ...]:
        reasons: list[str] = []
        if self.state.point_varying:
            reasons.append("point_varying_state")
        if self.action_ids:
            reasons.append("point_action")
        return tuple(reasons)


def analyze_effect_barriers(program: CoreProgram) -> EffectBarrierAnalysis:
    """Derive point barriers from typed effect dependencies, without evaluation."""

    point_outputs = {
        node.result.id: node.id.qualified_name
        for node in program.compute_nodes
        if node.result.availability.rate is ValueRate.POINT
    }
    point_parameter_tables = {
        overlay.table_id
        for overlay in program.parameter_overlays
        if _value_point_columns(overlay.value_use.value)
        or any(_value_point_columns(use.value) for use in overlay.key_uses.values())
    }
    point_columns: set[str] = set()
    point_compute_results: set[str] = set()
    varying_parameter_tables: set[str] = set()
    for spec in core_state(program):
        _collect_state_dependencies(
            spec,
            point_outputs=point_outputs,
            point_parameter_tables=point_parameter_tables,
            point_columns=point_columns,
            point_compute_results=point_compute_results,
            varying_parameter_tables=varying_parameter_tables,
        )
    return EffectBarrierAnalysis(
        state=EffectDependencies(
            point_columns=tuple(sorted(point_columns)),
            point_compute_results=tuple(sorted(point_compute_results)),
            point_parameter_tables=tuple(sorted(varying_parameter_tables)),
        ),
        action_ids=tuple(
            effect.id.qualified_name
            for effect in program.effects
            if isinstance(effect, ActionSpec)
        ),
    )


def _collect_state_dependencies(
    spec: StateSpecVariant,
    *,
    point_outputs: Mapping[ValueId, str],
    point_parameter_tables: set[str],
    point_columns: set[str],
    point_compute_results: set[str],
    varying_parameter_tables: set[str],
) -> None:
    if isinstance(spec, SetStateSpec):
        uses: list[RelationUse[ValueExpr] | ComputeResultRef] = [spec.value_use]
        if isinstance(spec.resource_target, PhysicalStateResourceTarget):
            uses.append(spec.resource_target.use)
        uses.extend(spec.route_entity_uses)
        for use in uses:
            if isinstance(use, ComputeResultRef):
                operation_id = point_outputs.get(use.value_id)
                if operation_id is not None:
                    point_compute_results.add(operation_id)
                continue
            _collect_value_dependencies(
                use.value,
                point_parameter_tables=point_parameter_tables,
                point_columns=point_columns,
                varying_parameter_tables=varying_parameter_tables,
            )
        return

    _collect_value_dependencies(
        spec.relation_use.value,
        point_parameter_tables=point_parameter_tables,
        point_columns=point_columns,
        varying_parameter_tables=varying_parameter_tables,
    )
    for child in spec.state:
        _collect_state_dependencies(
            child,
            point_outputs=point_outputs,
            point_parameter_tables=point_parameter_tables,
            point_columns=point_columns,
            point_compute_results=point_compute_results,
            varying_parameter_tables=varying_parameter_tables,
        )


def _collect_value_dependencies(
    value: ValueExpr,
    *,
    point_parameter_tables: set[str],
    point_columns: set[str],
    varying_parameter_tables: set[str],
) -> None:
    references = value.plan.references
    point_columns.update(references.ids(PlanReferenceKind.POINT_COLUMN))
    parameter_tables = set(references.ids(PlanReferenceKind.PARAMETER_TABLE))
    varying_parameter_tables.update(parameter_tables & point_parameter_tables)


def _value_point_columns(value: ValueExpr) -> tuple[str, ...]:
    return value.plan.references.ids(PlanReferenceKind.POINT_COLUMN)
