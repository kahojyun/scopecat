"""Planning-only materialization of concrete host effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scopecat.compiler.semantic.model import ValueId
from scopecat.compiler.typed.program import CoreProgram
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
    ComputeOperation,
    LocalOperation,
)
from scopecat.execution.program import RunCoverageEffect
from scopecat.kernel.product_identity import ProductUse
from scopecat.kernel.resource_identity import LogicalResourcePortId, ResourceClaim
from scopecat.planning.routing import ResourcePortManifest


@dataclass(frozen=True, slots=True)
class ComputeBindingSeed:
    """Planning-only run results available while binding point computation."""

    signatures: Mapping[ValueId, str]
    payload_ids: Mapping[ValueId, str]


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
    run_operations: tuple[ComputeOperation, ...]
    compute_seed: ComputeBindingSeed


@dataclass(frozen=True, slots=True)
class MaterializedLocalEffects:
    """Final local effects aligned with the ordered Core effect sequence."""

    compute_operations: tuple[RunCoverageEffect, ...]
    effect_operations: tuple[tuple[RunCoverageEffect, ...], ...]


def local_operation_resource_claims(
    operation: LocalOperation,
) -> tuple[ResourceClaim, ...]:
    """Return the coarse instrument identity used by run scheduling.

    Channel and topology bindings remain part of each concrete command, but the
    scheduler has no hierarchical conflict semantics. Leasing the owning
    instrument once therefore expresses the complete enforceable exclusion.
    """

    if isinstance(
        operation,
        ApplyStateOperation | CollectOperation,
    ):
        return (ResourceClaim(operation.instrument_id),)
    return ()
