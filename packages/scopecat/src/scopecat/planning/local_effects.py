"""Planning-only materialization of concrete host effects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from scopecat.compiler.linking.implementations import SelectedLocalImplementations
from scopecat.compiler.linking.product_realizations import (
    SelectedLocalProductRealizations,
)
from scopecat.compiler.semantic.model import ValueId
from scopecat.compiler.typed.dependencies import VariationAnalysis
from scopecat.compiler.typed.program import CoreProgram
from scopecat.execution.local.program import (
    ApplyStateOperation,
    CollectOperation,
    ComputeOperation,
    InstrumentActionOperation,
    LocalOperation,
)
from scopecat.execution.program import RunCoverageEffect
from scopecat.kernel.resource_identity import ResourceClaim


@dataclass(frozen=True, slots=True)
class ComputeBindingSeed:
    """Planning-only run results available while binding point computation."""

    signatures: Mapping[ValueId, str]
    payload_ids: Mapping[ValueId, str]


@dataclass(frozen=True, slots=True)
class LocalTargetPlan:
    """One closed local target selection reused by every coverage block."""

    program: CoreProgram
    implementations: SelectedLocalImplementations
    product_realizations: SelectedLocalProductRealizations
    instrument_order: tuple[str, ...]
    variation: VariationAnalysis
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
    """Derive exact physical claims from one final local operation."""

    claims: list[ResourceClaim] = []
    bindings = ()
    if isinstance(operation, ApplyStateOperation):
        claims.append(ResourceClaim(operation.instrument_id))
        bindings = tuple(
            binding
            for target in operation.targets
            for binding in target.channel_bindings
        )
    elif isinstance(operation, InstrumentActionOperation):
        claims.append(ResourceClaim(operation.instrument_id))
        bindings = tuple(
            binding for field in operation.fields for binding in field.channel_bindings
        )
    elif isinstance(operation, CollectOperation):
        claims.append(ResourceClaim(operation.instrument_id))
        bindings = tuple(
            binding
            for request in operation.command.requests
            for binding in request.channel_bindings
        )
    for binding in bindings:
        claims.append(ResourceClaim(binding.channel_id, "channel"))
        claims.extend(
            ResourceClaim(group_id, "group") for group_id in binding.group_ids
        )
    return tuple(dict.fromkeys(claims))
