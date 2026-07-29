"""Planning-only materialization of concrete host effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scopecat.compiler.typed.program import CoreProgram
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
    InvokeOperation,
    LocalOperation,
)
from scopecat.execution.program import RunCoverageEffect
from scopecat.kernel.product_identity import ProductUse
from scopecat.kernel.resource_identity import LogicalResourcePortId, ResourceRequirement
from scopecat.planning.routing import ResourcePortManifest


@dataclass(frozen=True, slots=True)
class LocalTargetPlan:
    """One closed local target selection reused by every coverage block.

    ``program`` is the authoritative linked program; ``product_uses`` is the
    local side of the local/domain demand cut.
    Physical manifests are selected once so bounded coverage evaluates only
    point-local values and entity selections, never the accepted configuration
    or provider inventory again.
    """

    program: CoreProgram
    product_uses: tuple[ProductUse, ...]
    instrument_order: tuple[str, ...]
    resource_ports: Mapping[LogicalResourcePortId, ResourcePortManifest]


@dataclass(frozen=True, slots=True)
class MaterializedLocalEffects:
    """Final local effects aligned with the ordered Core effect sequence."""

    compute_operations: tuple[RunCoverageEffect, ...]
    effect_operations: tuple[tuple[RunCoverageEffect, ...], ...]


def local_operation_resource_requirements(
    operation: LocalOperation,
) -> tuple[ResourceRequirement, ...]:
    """Return the logical instrument requirement of one local operation.

    Planning maps it through the accepted configuration only after local and
    domain ownership are closed, so driver-facing IDs never become scheduler
    identities implicitly.
    """

    if isinstance(
        operation,
        ApplyStateOperation | InvokeOperation | CollectOperation,
    ):
        return (ResourceRequirement(operation.instrument_id),)
    return ()
