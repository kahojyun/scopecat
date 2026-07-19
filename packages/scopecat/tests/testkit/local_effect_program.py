"""Test-only local effect programs for focused interpreter unit tests."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from scopecat.compiler.linking.bound import MaterializedLocalSemantics
from scopecat.execution.local.lowering import lower_local_effect_fields
from scopecat.execution.local.program import PointProgram
from scopecat.execution.ports.resources import ResourceClaim
from scopecat.kernel.product_identity import ProductUse, ProductUseId


@dataclass(frozen=True, slots=True)
class StubLocalEffectProgram:
    """Minimal structural program used where a full RunProgram is irrelevant."""

    experiment_id: str
    points: tuple[PointProgram, ...]
    product_uses: tuple[ProductUse, ...]
    collection_product_use_ids: tuple[ProductUseId, ...]
    resource_order: tuple[str, ...]
    resource_claims: tuple[ResourceClaim, ...]

    @property
    def point_count(self) -> int:
        return len(self.points)


def lower_test_local_effect_program(
    semantics: MaterializedLocalSemantics,
    *,
    instrument_order: Sequence[str],
) -> StubLocalEffectProgram:
    (
        points,
        product_uses,
        resource_order,
        resource_claims,
    ) = lower_local_effect_fields(semantics, instrument_order=instrument_order)
    local_product_realizations = semantics.local_product_realizations
    if local_product_realizations is None:
        raise AssertionError("test semantics require selected product realizations")
    return StubLocalEffectProgram(
        experiment_id=semantics.experiment_id,
        points=points,
        product_uses=product_uses,
        collection_product_use_ids=tuple(
            realization.product_use_id
            for realization in local_product_realizations.entries
        ),
        resource_order=resource_order,
        resource_claims=resource_claims,
    )
