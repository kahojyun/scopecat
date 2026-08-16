# pyright: reportPrivateUsage=false
"""Structured, bounded inspection of quantum compilation stages."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.inspection import (
    CompiledInspectionFact,
    CompiledProgramInspection,
    CompiledProgramInspectionLayer,
    CompiledProgramInspectionLink,
    CompiledProgramInspectionNode,
    CompiledProgramInspectionQuery,
    query_compiled_program_nodes,
)

from scopecat_quantum.authoring import (
    QUANTUM_PROGRAM_DIALECT_ID,
    BoundProgram,
    Program,
)
from scopecat_quantum.authoring._inspection import _inspection_node, _InspectionNode
from scopecat_quantum.circuits import Measure
from scopecat_quantum.gates import GateCall
from scopecat_quantum.programs import (
    ImplementedGate,
    Parallel,
    ParallelEach,
    QuantumNode,
    Repeat,
    estimate_quantum_program_workload,
)
from scopecat_quantum.programs import (
    Sequence as QuantumSequence,
)
from scopecat_quantum.pulses import (
    Acquire,
    DriveSignal,
    FluxSignal,
    Play,
    ReadoutSignal,
    ScheduledPulseEvent,
    ScheduledPulseProgram,
    ShiftPhase,
    pulse_leaf_owners,
)


@dataclass(frozen=True, slots=True)
class QuantumInspectionBounds:
    """Hard response budget for each structured program layer."""

    max_nodes_per_layer: int = 128

    def __post_init__(self) -> None:
        if self.max_nodes_per_layer <= 0:
            raise ValueError("quantum inspection node limits must be positive")


def inspect_quantum_program(
    program: Program,
    *,
    bound: BoundProgram | None = None,
    scheduled: ScheduledPulseProgram | None = None,
    bounds: QuantumInspectionBounds | None = None,
    query: CompiledProgramInspectionQuery | None = None,
    snapshot_id: str | None = None,
) -> CompiledProgramInspection:
    """Project authored, bound-logical, and scheduled views with stable links."""

    selected_bounds = bounds or QuantumInspectionBounds()
    selected_snapshot_id = snapshot_id or f"quantum-program:{program.id}"
    authored = _authored_layer(
        program,
        selected_bounds,
        query=query,
        snapshot_id=selected_snapshot_id,
    )
    layers = [authored]
    links: list[CompiledProgramInspectionLink] = []
    logical_operation_nodes: dict[str, str] = {}
    if bound is not None:
        logical, logical_operation_nodes = _logical_layer(
            bound,
            selected_bounds,
            query=query,
            snapshot_id=selected_snapshot_id,
        )
        layers.append(logical)
    if scheduled is not None:
        scheduled_layer, scheduled_links = _scheduled_layer(
            scheduled,
            logical_operation_nodes=logical_operation_nodes,
            bounds=selected_bounds,
            query=query,
            snapshot_id=selected_snapshot_id,
        )
        layers.append(scheduled_layer)
        links.extend(scheduled_links)
    return CompiledProgramInspection(
        dialect_id=QUANTUM_PROGRAM_DIALECT_ID,
        program_id=program.id,
        snapshot_id=selected_snapshot_id,
        layers=tuple(layers),
        links=tuple(links),
        query=query,
    )


def _bounded_layer(
    *,
    id: str,
    label: str,
    kind: str,
    nodes: Sequence[CompiledProgramInspectionNode],
    root_ids: tuple[str, ...],
    bounds: QuantumInspectionBounds,
    query: CompiledProgramInspectionQuery | None,
    snapshot_id: str,
    facts: tuple[CompiledInspectionFact, ...] = (),
) -> CompiledProgramInspectionLayer:
    all_nodes = tuple(nodes)
    selected, page = query_compiled_program_nodes(
        id,
        all_nodes,
        query=query,
        default_limit=bounds.max_nodes_per_layer,
        snapshot_id=snapshot_id,
    )
    return CompiledProgramInspectionLayer(
        id=id,
        label=label,
        kind=kind,
        node_count=len(all_nodes),
        nodes_truncated=len(selected) < len(all_nodes),
        root_ids=root_ids,
        nodes=selected,
        page=page,
        facts=facts,
    )


def _authored_layer(
    program: Program,
    bounds: QuantumInspectionBounds,
    *,
    query: CompiledProgramInspectionQuery | None,
    snapshot_id: str,
) -> CompiledProgramInspectionLayer:
    root_id = "authored:program"
    tree = _inspection_node(program.body)
    nodes = [
        CompiledProgramInspectionNode(
            id=root_id,
            kind="program",
            label=f"program {program.id}",
            child_count=1,
            result_ids=tuple(result.id for result in program.results),
            facts=(
                CompiledInspectionFact("port_count", len(program.ports)),
                CompiledInspectionFact("result_count", len(program.results)),
            ),
        )
    ]

    def visit(
        inspection_node: _InspectionNode,
        *,
        parent_id: str,
        path: tuple[int, ...],
    ) -> None:
        node_id = "authored:" + "/".join(str(index) for index in path)
        label = inspection_node.label
        nodes.append(
            CompiledProgramInspectionNode(
                id=node_id,
                kind=label.split(" ", maxsplit=1)[0],
                label=label,
                parent_id=parent_id,
                child_count=len(inspection_node.children),
            )
        )
        for index, child in enumerate(inspection_node.children):
            visit(child, parent_id=node_id, path=(*path, index))

    visit(tree, parent_id=root_id, path=(0,))
    return _bounded_layer(
        id="authored",
        label="Authored program",
        kind="authored",
        nodes=nodes,
        root_ids=(root_id,),
        bounds=bounds,
        query=query,
        snapshot_id=snapshot_id,
    )


def _logical_layer(
    bound: BoundProgram,
    bounds: QuantumInspectionBounds,
    *,
    query: CompiledProgramInspectionQuery | None,
    snapshot_id: str,
) -> tuple[CompiledProgramInspectionLayer, dict[str, str]]:
    root_id = "logical:program"
    workload = estimate_quantum_program_workload(bound.verified)
    nodes = [
        CompiledProgramInspectionNode(
            id=root_id,
            kind="program",
            label=f"bound {bound.program.id.value}",
            child_count=1,
            result_ids=tuple(result.id for result in bound.results),
            facts=(
                CompiledInspectionFact(
                    "operation_count",
                    workload.structural_operation_count,
                ),
                CompiledInspectionFact(
                    "unresolved_operation_count",
                    len(bound.verified.unresolved.operations),
                ),
                CompiledInspectionFact(
                    "expanded_operation_count",
                    workload.expanded_operation_count,
                ),
                CompiledInspectionFact(
                    "selected_entity_count",
                    workload.selected_entity_count,
                ),
                CompiledInspectionFact(
                    "max_parallel_width",
                    workload.max_parallel_width,
                ),
            ),
        )
    ]
    operation_nodes: dict[str, str] = {}

    def visit(node: QuantumNode, *, parent_id: str, path: tuple[int, ...]) -> None:
        structural_id = "logical:" + "/".join(str(index) for index in path)
        children: tuple[QuantumNode, ...]
        facts: tuple[CompiledInspectionFact, ...] = ()
        result_ids: tuple[str, ...] = ()
        if isinstance(node, QuantumSequence):
            kind, label, children = "sequence", "sequence", node.operations
            entity_ids: tuple[str, ...] = ()
        elif isinstance(node, Parallel):
            kind, label, children = "parallel", "parallel", node.branches
            entity_ids = ()
        elif isinstance(node, ParallelEach):
            kind, label, children = (
                "parallel_each",
                (
                    f"parallel_each ${node.entity_set_id} "
                    f"({len(node.entity_ids)} entities)"
                ),
                (node.operation,),
            )
            entity_ids = tuple(entity.value for entity in node.entity_ids)
            facts = (
                CompiledInspectionFact("entity_set_id", node.entity_set_id),
                CompiledInspectionFact("entity_count", len(node.entity_ids)),
            )
        elif isinstance(node, Repeat):
            kind, label, children = (
                "repeat",
                f"repeat x{node.count}",
                (node.operation,),
            )
            entity_ids = ()
            facts = (CompiledInspectionFact("count", node.count),)
        else:
            children = ()
            operation_id = node.id.value
            structural_id = f"logical:operation:{operation_id}"
            operation_nodes[operation_id] = structural_id
            if isinstance(node, GateCall):
                kind = "gate"
                entity_ids = tuple(qubit.value for qubit in node.qubits)
                label = f"{node.gate_id.value}({', '.join(entity_ids)})"
            elif isinstance(node, Measure):
                kind = "measure"
                entity_ids = (node.qubit.value,)
                result_ids = (node.acquisition_slot_id.local_id,)
                label = f"measure {node.qubit.value} → {result_ids[0]}"
            elif isinstance(node, ImplementedGate):
                kind = "implemented_gate"
                entity_ids = tuple(qubit.value for qubit in node.call.qubits)
                label = f"{node.call.gate_id.value} implementation"
                facts = (
                    CompiledInspectionFact(
                        "candidate_id",
                        node.candidate_id or "inline",
                    ),
                )
            else:
                kind = "pulse_block"
                entity_ids = tuple(
                    owner.value for owner in pulse_leaf_owners(node.pulse_template.body)
                )
                label = f"pulse {node.pulse_template.id.value}"
                result_ids = tuple(
                    output.local_id
                    for _source, output in node.acquisition_slot_bindings
                )
        nodes.append(
            CompiledProgramInspectionNode(
                id=structural_id,
                kind=kind,
                label=label,
                parent_id=parent_id,
                child_count=len(children),
                entity_ids=tuple(dict.fromkeys(entity_ids)),
                result_ids=result_ids,
                facts=facts,
            )
        )
        for index, child in enumerate(children):
            visit(child, parent_id=structural_id, path=(*path, index))

    visit(bound.program.body, parent_id=root_id, path=(0,))
    layer = _bounded_layer(
        id="logical",
        label="Bound logical program",
        kind="logical",
        nodes=nodes,
        root_ids=(root_id,),
        bounds=bounds,
        query=query,
        snapshot_id=snapshot_id,
    )
    return layer, operation_nodes


def _scheduled_layer(
    scheduled: ScheduledPulseProgram,
    *,
    logical_operation_nodes: dict[str, str],
    bounds: QuantumInspectionBounds,
    query: CompiledProgramInspectionQuery | None,
    snapshot_id: str,
) -> tuple[
    CompiledProgramInspectionLayer,
    tuple[CompiledProgramInspectionLink, ...],
]:
    root_id = "scheduled:program"
    nodes = [
        CompiledProgramInspectionNode(
            id=root_id,
            kind="program",
            label=f"schedule {scheduled.id.value}",
            child_count=len(scheduled.events),
            duration_seconds=str(scheduled.duration_seconds),
            result_ids=tuple(slot.id.local_id for slot in scheduled.acquisition_slots),
            facts=(
                CompiledInspectionFact("event_count", len(scheduled.events)),
                CompiledInspectionFact(
                    "acquisition_count", len(scheduled.acquisition_slots)
                ),
            ),
        )
    ]
    links: list[CompiledProgramInspectionLink] = []
    for event in scheduled.events:
        event_node = _scheduled_event_node(event, parent_id=root_id)
        nodes.append(event_node)
        source_operation_id = _source_operation_id(event)
        source_node_id = (
            _logical_operation_node(
                source_operation_id,
                logical_operation_nodes,
            )
            if source_operation_id is not None
            else None
        )
        if source_node_id is not None:
            links.append(
                CompiledProgramInspectionLink(
                    source_layer_id="logical",
                    source_node_id=source_node_id,
                    target_layer_id="scheduled",
                    target_node_id=event_node.id,
                    relation="lowers_to",
                )
            )
    layer = _bounded_layer(
        id="scheduled",
        label="Scheduled pulse events",
        kind="scheduled",
        nodes=nodes,
        root_ids=(root_id,),
        bounds=bounds,
        query=query,
        snapshot_id=snapshot_id,
        facts=(
            CompiledInspectionFact(
                "duration_seconds", str(scheduled.duration_seconds), unit="s"
            ),
        ),
    )
    returned_node_ids = {node.id for node in layer.nodes}
    return layer, tuple(
        link for link in links if link.target_node_id in returned_node_ids
    )


def _logical_operation_node(
    source_operation_id: str,
    operation_nodes: dict[str, str],
) -> str | None:
    exact = operation_nodes.get(source_operation_id)
    if exact is not None:
        return exact
    template_ids = tuple(
        operation_id
        for operation_id in operation_nodes
        if source_operation_id.endswith(f"/{operation_id}")
    )
    if not template_ids:
        return None
    template_id = max(template_ids, key=len)
    return operation_nodes[template_id]


def _scheduled_event_node(
    event: ScheduledPulseEvent,
    *,
    parent_id: str,
) -> CompiledProgramInspectionNode:
    instruction = event.instruction
    signal = instruction.signal
    if isinstance(signal, FluxSignal):
        entity_ids = (signal.owner.value,)
        signal_label = f"flux({signal.owner.value})"
    else:
        entity_ids = (signal.qubit.value,)
        signal_kind = (
            "drive"
            if isinstance(signal, DriveSignal)
            else "readout"
            if isinstance(signal, ReadoutSignal)
            else "acquire"
        )
        signal_label = f"{signal_kind}({signal.qubit.value})"
    result_ids = (
        (instruction.slot_id.local_id,) if isinstance(instruction, Acquire) else ()
    )
    facts: list[CompiledInspectionFact] = [
        CompiledInspectionFact("signal", signal_label),
    ]
    if isinstance(instruction, Play):
        kind = "play"
        facts.append(
            CompiledInspectionFact(
                "envelope",
                type(instruction.envelope).__name__,
            )
        )
    elif isinstance(instruction, Acquire):
        kind = "acquire"
    elif isinstance(instruction, ShiftPhase):
        kind = "shift_phase"
        facts.append(
            CompiledInspectionFact(
                "phase", instruction.phase.value, unit=instruction.phase.unit
            )
        )
    else:
        kind = "delay"
    return CompiledProgramInspectionNode(
        id=f"scheduled:event:{event.id.value}",
        kind=kind,
        label=f"{kind} {signal_label}",
        parent_id=parent_id,
        entity_ids=entity_ids,
        result_ids=result_ids,
        start_seconds=str(event.start_seconds),
        duration_seconds=str(event.duration_seconds),
        facts=tuple(facts),
    )


def _source_operation_id(event: ScheduledPulseEvent) -> str | None:
    scope = event.id.scope
    for index in range(len(scope) - 1, -1, -1):
        if scope[index] == "operations" and index + 1 < len(scope):
            return scope[index + 1]
    return None


__all__ = ["QuantumInspectionBounds", "inspect_quantum_program"]
