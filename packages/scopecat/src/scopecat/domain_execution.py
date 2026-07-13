"""Public target boundary for one prepared domain-program execution.

Domain adapters consume the target-neutral linked program and close every
target, result, value, transform, and record-projection decision before a run
is durably accepted.  Scopecat retains ownership of runtime submission,
correlation, journalling, recording, and terminal run evidence.

The first public contract is deliberately synchronous: the initial fetch must
either return the complete result or violate the adapter contract. Polling and
resumption require a separate durable lifecycle and are not implied here.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from scopecat._compiler.linked import LinkedPlan, MaterializedLinkedPoints
from scopecat.domain_invocation import (
    ClosedDomainInvocation,
    ClosedDomainOutputValues,
    ProductUseId,
)
from scopecat.domain_runtime import CorrelatedDomainFetch, DomainRuntime
from scopecat.execution_coverage import (
    ExecutionCoverage,
    ExecutionResourceClaim,
    ExecutionTask,
    product_execution_coverage,
)
from scopecat.measurement_projection import BoundMeasurementProjection
from scopecat.measurement_transforms import BoundHostMeasurementTransformPlan
from scopecat.measurement_values import BoundDomainMeasurementValueFragment
from scopecat.models.run_plan import RunPlanDomainExecution

type ErasedDomainInvocation = ClosedDomainInvocation[Hashable, Hashable, object]
type ErasedDomainRuntime = DomainRuntime[
    Hashable,
    Hashable,
    object,
    object,
]
type ErasedDomainRealizer = Callable[
    [CorrelatedDomainFetch[object]],
    ClosedDomainOutputValues[Hashable, Hashable],
]


@dataclass(frozen=True, slots=True)
class PreparedDomainExecution:
    """A pure proof that one linked program is ready for domain effects.

    The type-erased runtime fields form an existential adapter boundary: an
    adapter constructs all three from one concrete address/payload/result type
    family, while core never inspects those domain-owned values.
    """

    adapter_id: str
    semantic_operation_id: str
    linked_points: MaterializedLinkedPoints = field(repr=False)
    invocation: ErasedDomainInvocation = field(repr=False)
    runtime: ErasedDomainRuntime = field(repr=False, compare=False)
    realize: ErasedDomainRealizer = field(repr=False, compare=False)
    source_fragment: BoundDomainMeasurementValueFragment[
        Hashable,
        Hashable,
    ] = field(repr=False)
    projection: BoundMeasurementProjection = field(repr=False)
    claimed_tasks: tuple[ExecutionTask, ...] = ()
    resource_claims: tuple[ExecutionResourceClaim, ...] = ()
    transforms: BoundHostMeasurementTransformPlan | None = field(
        default=None,
        repr=False,
    )
    completion_contract: Literal["synchronous"] = "synchronous"

    def __post_init__(self) -> None:
        if not self.adapter_id:
            msg = "domain execution adapter_id must be non-empty"
            raise ValueError(msg)
        if not self.semantic_operation_id:
            msg = "domain execution semantic_operation_id must be non-empty"
            raise ValueError(msg)
        if not callable(self.realize):
            msg = "domain execution realizer must be callable"
            raise TypeError(msg)
        if self.completion_contract != "synchronous":
            msg = "domain execution currently supports only synchronous completion"
            raise ValueError(msg)
        for method_name in ("submit", "fetch", "reconcile"):
            if not callable(getattr(self.runtime, method_name, None)):
                msg = f"domain runtime requires a callable {method_name} method"
                raise TypeError(msg)

        claimed_tasks = tuple(self.claimed_tasks)
        if any(task.kind == "product" for task in claimed_tasks):
            msg = (
                "domain product coverage is derived from its bound value assembly; "
                "claimed_tasks must contain only non-product tasks"
            )
            raise ValueError(msg)
        ExecutionCoverage(claimed_tasks)
        resource_claims = tuple(self.resource_claims)
        if len(resource_claims) != len(set(resource_claims)):
            msg = "domain execution resource claims must be unique"
            raise ValueError(msg)
        object.__setattr__(self, "claimed_tasks", claimed_tasks)
        object.__setattr__(self, "resource_claims", resource_claims)

        assembly = self.source_fragment.selection
        linked_points = self.linked_points
        if self.invocation.result_mapping.linked_points is not linked_points:
            msg = "domain invocation must retain the prepared linked points"
            raise ValueError(msg)
        if assembly.linked_points is not linked_points:
            msg = "domain source fragment must retain the prepared linked points"
            raise ValueError(msg)
        if self.projection.product_values is not assembly:
            msg = "domain projection must retain the source value assembly"
            raise ValueError(msg)
        if (
            self.source_fragment.result_contract_fingerprint
            != self.invocation.result_mapping.contract_fingerprint
        ):
            msg = "domain source fragment must retain the invocation result contract"
            raise ValueError(msg)

        transforms = self.transforms
        if transforms is None:
            if tuple(fragment.id for fragment in assembly.fragments) != (
                self.source_fragment.fragment_id,
            ):
                msg = "domain execution without transforms requires one source fragment"
                raise ValueError(msg)
            return
        if transforms.value_assembly is not assembly:
            msg = "domain transforms must retain the source value assembly"
            raise ValueError(msg)
        if transforms.source_fragment_ids != (self.source_fragment.fragment_id,):
            msg = "domain execution currently requires exactly one domain source"
            raise ValueError(msg)

    @property
    def domain_product_use_ids(self) -> frozenset[ProductUseId]:
        """Return logical uses produced directly by the domain invocation."""

        return frozenset(
            self.source_fragment.selection.fragment(
                self.source_fragment.fragment_id
            ).product_use_ids
        )

    @property
    def owned_product_use_ids(self) -> tuple[ProductUseId, ...]:
        """Return every direct or host-transformed value owned by this job."""

        return self.projection.product_values.product_use_ids

    @property
    def coverage(self) -> ExecutionCoverage:
        """Return exact semantic ownership selected for this domain job."""

        products = product_execution_coverage(self.owned_product_use_ids)
        return ExecutionCoverage((*self.claimed_tasks, *products.tasks))


class DomainExecutionAdapter(Protocol):
    """Pure selector of one explicitly covered domain-program execution unit.

    The adapter owns only the tasks retained by ``PreparedDomainExecution``.
    Exact whole-plan coverage and composition with local instrument units are
    selected by the execution backend before effects.
    """

    @property
    def adapter_id(self) -> str: ...

    def prepare(self, linked: LinkedPlan) -> PreparedDomainExecution: ...


def project_domain_run_plan_execution(
    prepared: PreparedDomainExecution,
    *,
    unit_id: str,
) -> RunPlanDomainExecution:
    """Project accepted target identity without retaining adapter payloads."""

    intent = prepared.invocation.intent
    return RunPlanDomainExecution(
        unit_id=unit_id,
        adapter_id=prepared.adapter_id,
        semantic_operation_id=prepared.semantic_operation_id,
        completion_contract=prepared.completion_contract,
        invocation_id=intent.invocation_id,
        intent_fingerprint=intent.intent_fingerprint,
        target_id=intent.target_id,
        compiler_id=intent.compiler_id,
        capability_fingerprint=intent.capability_fingerprint,
        artifact_id=intent.artifact_id,
        artifact_fingerprint=intent.artifact_fingerprint,
    )


def erase_prepared_domain_execution[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
    PayloadT,
    ResultT,
](
    *,
    adapter_id: str,
    semantic_operation_id: str,
    linked_points: MaterializedLinkedPoints,
    invocation: ClosedDomainInvocation[EntryAddressT, ResultAddressT, PayloadT],
    runtime: DomainRuntime[EntryAddressT, ResultAddressT, PayloadT, ResultT],
    realize: Callable[
        [CorrelatedDomainFetch[ResultT]],
        ClosedDomainOutputValues[EntryAddressT, ResultAddressT],
    ],
    source_fragment: BoundDomainMeasurementValueFragment[
        EntryAddressT,
        ResultAddressT,
    ],
    projection: BoundMeasurementProjection,
    claimed_tasks: tuple[ExecutionTask, ...] = (),
    resource_claims: tuple[ExecutionResourceClaim, ...] = (),
    transforms: BoundHostMeasurementTransformPlan | None = None,
) -> PreparedDomainExecution:
    """Close one concrete adapter type family behind the core execution ABI."""

    return PreparedDomainExecution(
        adapter_id=adapter_id,
        semantic_operation_id=semantic_operation_id,
        linked_points=linked_points,
        invocation=cast("ErasedDomainInvocation", invocation),
        runtime=cast("ErasedDomainRuntime", runtime),
        realize=cast("ErasedDomainRealizer", realize),
        source_fragment=cast(
            "BoundDomainMeasurementValueFragment[Hashable, Hashable]",
            source_fragment,
        ),
        projection=projection,
        claimed_tasks=claimed_tasks,
        resource_claims=resource_claims,
        transforms=transforms,
    )


__all__ = [
    "DomainExecutionAdapter",
    "PreparedDomainExecution",
    "erase_prepared_domain_execution",
    "project_domain_run_plan_execution",
]
