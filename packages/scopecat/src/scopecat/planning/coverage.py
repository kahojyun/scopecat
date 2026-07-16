"""Target-neutral ownership of executable semantic tasks.

Coverage is selected once, before provider or target effects.  It deliberately
uses stable semantic identities and structural program paths rather than
transient object identity.  Record projections are consumers of product values
and therefore are not execution tasks of their own.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from scopecat.compiler.typed.program import TypedProgram
from scopecat.kernel.product_identity import ProductUseId

type ExecutionTaskKind = Literal[
    "parameter_overlay",
    "route",
    "compute",
    "state",
    "action",
    "domain_execution",
    "measurement_transform",
    "product",
]
type ExecutionResourceKind = Literal["target", "instrument", "channel", "group"]

_TASK_KIND_ORDER: dict[ExecutionTaskKind, int] = {
    "parameter_overlay": 0,
    "route": 1,
    "compute": 2,
    "state": 3,
    "action": 4,
    "domain_execution": 5,
    "measurement_transform": 6,
    "product": 7,
}


@dataclass(frozen=True, slots=True, order=True)
class ExecutionTask:
    """One exact target-neutral task claimed by an execution unit."""

    kind: ExecutionTaskKind
    id: str

    def __post_init__(self) -> None:
        if not self.id:
            msg = "execution task ids must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True, order=True)
class ExecutionResourceClaim:
    """Exclusive physical ownership required while one unit has effects."""

    kind: ExecutionResourceKind
    id: str

    def __post_init__(self) -> None:
        if not self.id:
            msg = "execution resource claim ids must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class ExecutionCoverage:
    """Canonical unique set of semantic tasks owned by one execution unit."""

    tasks: tuple[ExecutionTask, ...]

    def __post_init__(self) -> None:
        selected = tuple(self.tasks)
        if len(selected) != len(set(selected)):
            msg = "execution coverage cannot claim one task more than once"
            raise ValueError(msg)
        canonical = tuple(
            sorted(selected, key=lambda task: (_TASK_KIND_ORDER[task.kind], task.id))
        )
        object.__setattr__(self, "tasks", canonical)

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]:
        return tuple(
            ProductUseId(task.id) for task in self.tasks if task.kind == "product"
        )


def program_execution_coverage(program: TypedProgram) -> ExecutionCoverage:
    """Return the complete executable task inventory of one linked program."""

    return ExecutionCoverage(
        (
            *(
                ExecutionTask("parameter_overlay", str(index))
                for index, _overlay in enumerate(program.parameter_overlays)
            ),
            *(
                ExecutionTask("route", route.port_id.qualified_name)
                for route in program.route_intents
            ),
            *(
                ExecutionTask("compute", node.id.qualified_name)
                for node in program.compute_nodes
            ),
            *(
                ExecutionTask("state", str(index))
                for index, _state in enumerate(program.state)
            ),
            *(
                ExecutionTask("action", action.id.qualified_name)
                for action in program.actions
            ),
            *(
                ExecutionTask("domain_execution", "domain")
                for execution in (program.domain_execution,)
                if execution is not None
            ),
            *(
                ExecutionTask(
                    "measurement_transform",
                    transform.id.qualified_name,
                )
                for transform in program.measurement_transforms
            ),
            *(ExecutionTask("product", use.id.value) for use in program.product_uses),
        )
    )


def product_execution_coverage(
    product_use_ids: tuple[ProductUseId, ...],
) -> ExecutionCoverage:
    """Build the product-value portion of one unit's coverage."""

    return ExecutionCoverage(
        tuple(ExecutionTask("product", use_id.value) for use_id in product_use_ids)
    )


__all__ = [
    "ExecutionCoverage",
    "ExecutionResourceClaim",
    "ExecutionResourceKind",
    "ExecutionTask",
    "ExecutionTaskKind",
    "product_execution_coverage",
    "program_execution_coverage",
]
