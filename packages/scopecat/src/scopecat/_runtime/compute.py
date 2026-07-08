"""Runtime compute evaluation and reuse policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from pydantic import BaseModel

from scopecat._planning.planner import PlannerPoint
from scopecat._runtime.graph import RuntimeComputeStep, RuntimeGraph, RuntimePoint
from scopecat._runtime.lowering import evaluate_compute_nodes_for_point
from scopecat.diagnostics import Diagnostic
from scopecat.experiments import PointRouteBinding
from scopecat.models.artifact import CommandPayload


@dataclass(frozen=True)
class ComputeApplySummary:
    evaluated_node_count: int = 0
    reused_node_count: int = 0
    payload_count: int = 0


@dataclass(frozen=True)
class RuntimeComputeResult:
    payloads: dict[str, CommandPayload]
    summary: ComputeApplySummary
    diagnostics: tuple[Diagnostic, ...] = ()


@dataclass(frozen=True)
class _ComputeCacheEntry:
    signature: object
    token: object
    result: object


@dataclass
class RuntimeComputeCache:
    """Point-to-point cache for pure runtime compute nodes."""

    entries: dict[str, _ComputeCacheEntry] = field(default_factory=dict)

    def evaluate_point(
        self,
        *,
        point: RuntimePoint,
        graph: RuntimeGraph,
    ) -> RuntimeComputeResult:
        if not point.compute_steps:
            return RuntimeComputeResult(payloads={}, summary=ComputeApplySummary())
        compute_results: dict[tuple[int, str], object] = {}
        node_tokens: dict[str, object] = {}
        payloads: dict[str, CommandPayload] = {}
        diagnostics: list[Diagnostic] = []
        evaluated_node_ids: list[str] = []
        reused_node_ids: list[str] = []
        for step in point.compute_steps:
            node = graph.compute_nodes_by_id.get(step.node_id)
            if node is None:
                continue
            signature = _compute_signature(
                step=step,
                point=point,
                upstream_tokens=node_tokens,
            )
            cache_entry = self.entries.get(step.node_id)
            can_reuse = _compute_step_is_cacheable(step)
            if (
                can_reuse
                and cache_entry is not None
                and cache_entry.signature == signature
            ):
                result = cache_entry.result
                compute_results[(point.point_index, step.node_id)] = result
                node_tokens[step.node_id] = cache_entry.token
                reused_node_ids.append(step.node_id)
                if step.payload_id is not None and step.payload_kind is not None:
                    payloads[step.payload_id] = CommandPayload(
                        id=step.payload_id,
                        kind=step.payload_kind,
                        metadata={
                            "compute_node_id": step.node_id,
                            "point_index": point.point_index,
                            "compute_status": "reused",
                        },
                        payload=result,
                    )
                continue
            _results, point_payloads, point_diagnostics = (
                evaluate_compute_nodes_for_point(
                    point=PlannerPoint(
                        point_index=point.point_index,
                        point_uid=point.point_uid,
                        row=point.row,
                    ),
                    params=point.params,
                    compute_nodes=[node],
                    route_bindings=point.route_bindings,
                    compute_payload_kinds=(
                        {step.node_id: step.payload_kind}
                        if step.payload_kind is not None
                        else {}
                    ),
                    initial_compute_results=compute_results,
                )
            )
            diagnostics.extend(
                Diagnostic.model_validate(diagnostic)
                for diagnostic in point_diagnostics
            )
            compute_results.update(_results)
            for payload in point_payloads.values():
                tagged_payload = payload.model_copy(
                    update={
                        "metadata": {
                            **payload.metadata,
                            "compute_status": "evaluated",
                        }
                    }
                )
                payloads[tagged_payload.id] = tagged_payload
            if point_diagnostics:
                node_tokens[step.node_id] = (
                    "failed",
                    point.point_index,
                    step.node_id,
                )
                continue
            result = _results.get((point.point_index, step.node_id))
            if result is None:
                continue
            evaluated_node_ids.append(step.node_id)
            token = signature if can_reuse else ("uncacheable", id(result))
            node_tokens[step.node_id] = token
            if can_reuse:
                self.entries[step.node_id] = _ComputeCacheEntry(
                    signature=signature,
                    token=token,
                    result=result,
                )
        return RuntimeComputeResult(
            payloads=payloads,
            summary=ComputeApplySummary(
                evaluated_node_count=len(evaluated_node_ids),
                reused_node_count=len(reused_node_ids),
                payload_count=len(payloads),
            ),
            diagnostics=tuple(diagnostics),
        )


def _compute_step_is_cacheable(step: RuntimeComputeStep) -> bool:
    return not step.dependencies.input_refs


def _compute_signature(
    *,
    step: RuntimeComputeStep,
    point: RuntimePoint,
    upstream_tokens: dict[str, object],
) -> object:
    dependencies = step.dependencies
    return (
        (
            "point_columns",
            tuple(
                (column_id, _versioned_value(point.row.get(column_id)))
                for column_id in dependencies.point_columns
            ),
        ),
        (
            "scalar_params",
            tuple(
                (
                    parameter_id,
                    _versioned_value(point.params.scalars.get(parameter_id)),
                )
                for parameter_id in dependencies.scalar_params
            ),
        ),
        (
            "parameter_tables",
            tuple(
                (table_id, _versioned_value(point.params.tables.get(table_id)))
                for table_id in dependencies.parameter_tables
            ),
        ),
        (
            "routes",
            tuple(
                (port_id, _versioned_value(_route_for_port(point, port_id)))
                for port_id in dependencies.routes
            ),
        ),
        (
            "upstream_compute",
            tuple(
                (node_id, upstream_tokens.get(node_id, ("missing", node_id)))
                for node_id in dependencies.upstream_compute
            ),
        ),
    )


def _route_for_port(point: RuntimePoint, port_id: str) -> PointRouteBinding | None:
    for route in point.route_bindings:
        if route.port_id == port_id:
            return route
    return None


def _versioned_value(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, BaseModel):
        return (
            type(value).__module__,
            type(value).__qualname__,
            _versioned_value(value.model_dump(mode="python")),
        )
    if isinstance(value, dict):
        mapping = cast("dict[object, object]", value)
        return tuple(
            (str(key), _versioned_value(item))
            for key, item in sorted(mapping.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, list | tuple):
        sequence = cast("list[object] | tuple[object, ...]", value)
        return tuple(_versioned_value(item) for item in sequence)
    shape = getattr(value, "shape", None)
    dtype = getattr(value, "dtype", None)
    if shape is not None or dtype is not None:
        return (
            "array_like",
            id(value),
            tuple(int(dim) for dim in shape) if shape is not None else None,
            str(dtype) if dtype is not None else None,
        )
    return ("object", id(value))


__all__ = [
    "ComputeApplySummary",
    "RuntimeComputeCache",
    "RuntimeComputeResult",
]
