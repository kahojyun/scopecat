from __future__ import annotations

from collections.abc import Sequence
from collections.abc import Set as AbstractSet

from scopecat.compiler.linking.linked import LinkedPlan, materialize_linked_points
from scopecat.kernel.product_identity import ProductUseId
from scopecat.planning.local_materialization import (
    MaterializedLocalEffects,
)
from scopecat.planning.local_materialization import (
    materialize_local_execution as lower_local_execution,
)


def materialize_local_execution(
    linked: LinkedPlan,
    *,
    product_use_ids: AbstractSet[ProductUseId] | None = None,
    instrument_order: Sequence[str] = (),
) -> MaterializedLocalEffects:
    """Test convenience for linking-era tests that do not inspect point closure."""

    return lower_local_execution(
        materialize_linked_points(linked),
        product_use_ids=product_use_ids,
        instrument_order=instrument_order,
    )
