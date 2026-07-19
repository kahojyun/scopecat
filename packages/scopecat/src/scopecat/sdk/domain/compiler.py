"""Pure domain compilation over typed residual experiment semantics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from scopecat.compiler.relations.specialization import BindingTime
from scopecat.compiler.semantic.value_expressions import ValueExpr
from scopecat.compiler.typed.point_domain import VerifiedPointDomain
from scopecat.execution.ports.resources import ResourceClaim
from scopecat.kernel.value_types import ValueType
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.view import DomainCallView


@dataclass(frozen=True, slots=True)
class DomainResidualInput:
    """One typed domain input after request/config partial evaluation."""

    id: str
    value_type: ValueType
    expression: ValueExpr = field(repr=False)
    binding_time: BindingTime

    def __post_init__(self) -> None:
        if not self.id:
            msg = "domain residual input id must be non-empty"
            raise ValueError(msg)
        if self.expression.value_type != self.value_type:
            msg = "domain residual input expression must retain its declared type"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DomainBoundPoint:
    """Compiler-requested concrete bindings for one logical point."""

    logical_ordinal: int
    inputs: tuple[tuple[str, object], ...]

    def input(self, name: str) -> object:
        for input_name, value in self.inputs:
            if input_name == name:
                return value
        raise KeyError(name)


@dataclass(frozen=True, slots=True)
class DomainCompileRequest:
    """One symbolic point space and its bounded domain-call region."""

    call: DomainCallView
    point_space: VerifiedPointDomain = field(repr=False)
    inputs: tuple[DomainResidualInput, ...]
    barrier_regions: tuple[tuple[int, ...], ...]
    _bound_points: tuple[DomainBoundPoint, ...] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        inputs = tuple(self.inputs)
        regions = tuple(tuple(region) for region in self.barrier_regions)
        input_ids = tuple(input_value.id for input_value in inputs)
        if len(input_ids) != len(set(input_ids)):
            raise ValueError("domain residual input ids must be unique")
        expected_input_ids = tuple(port.id for port in self.call.program.inputs)
        if input_ids != expected_input_ids:
            msg = "domain residual inputs must follow the complete program input order"
            raise ValueError(msg)
        selected_ordinals = tuple(ordinal for region in regions for ordinal in region)
        if selected_ordinals != tuple(range(len(selected_ordinals))):
            msg = "domain barrier regions must exactly partition logical point ordinals"
            raise ValueError(msg)
        if any(not region for region in regions):
            raise ValueError("domain barrier regions must be non-empty")
        bound_ordinals = tuple(point.logical_ordinal for point in self._bound_points)
        if bound_ordinals != selected_ordinals:
            raise ValueError("domain bound points must match the barrier-region order")
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "barrier_regions", regions)
        object.__setattr__(self, "_bound_points", tuple(self._bound_points))

    def input(self, name: str) -> DomainResidualInput:
        for input_value in self.inputs:
            if input_value.id == name:
                return input_value
        raise KeyError(name)

    def partition(self, *, max_points: int) -> tuple[tuple[int, ...], ...]:
        """Return a contiguous capacity-limited partition within barriers."""

        if type(max_points) is not int or max_points <= 0:
            raise ValueError("domain job capacity must be a positive integer")
        return tuple(
            tuple(region[offset : offset + max_points])
            for region in self.barrier_regions
            for offset in range(0, len(region), max_points)
        )

    def bind_points(
        self,
        ordinals: Sequence[int],
        *,
        max_points: int,
    ) -> tuple[DomainBoundPoint, ...]:
        """Bind one compiler-selected finite region under an explicit budget."""

        selected = tuple(ordinals)
        if type(max_points) is not int or max_points <= 0:
            raise ValueError("domain point binding budget must be positive")
        if len(selected) > max_points:
            raise ValueError("domain point binding exceeds the requested budget")
        by_ordinal = {point.logical_ordinal: point for point in self._bound_points}
        try:
            return tuple(by_ordinal[ordinal] for ordinal in selected)
        except KeyError as error:
            msg = "domain point binding selects an unknown ordinal"
            raise ValueError(msg) from error


@dataclass(frozen=True, slots=True)
class DomainCompiledJob:
    """One pure target artifact assigned to exact logical point ordinals."""

    id: str
    point_ordinals: tuple[int, ...]
    artifact: object = field(repr=False)
    resource_claims: tuple[ResourceClaim, ...] = ()

    def __post_init__(self) -> None:
        ordinals = tuple(self.point_ordinals)
        if not self.id or not ordinals:
            raise ValueError("compiled domain job id and points must be non-empty")
        if ordinals != tuple(sorted(set(ordinals))):
            msg = "compiled domain job ordinals must be unique and canonical"
            raise ValueError(msg)
        object.__setattr__(self, "point_ordinals", ordinals)
        object.__setattr__(self, "resource_claims", tuple(self.resource_claims))


@dataclass(frozen=True, slots=True)
class DomainCompilation:
    """Pure target lowering result before runtime preparation."""

    compiler_id: str
    target_id: str
    jobs: tuple[DomainCompiledJob, ...]
    pushed_transform_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        jobs = tuple(self.jobs)
        if not self.compiler_id or not self.target_id:
            msg = "domain compiler and target ids must be non-empty"
            raise ValueError(msg)
        job_ids = tuple(job.id for job in jobs)
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("compiled domain job ids must be unique")
        object.__setattr__(self, "jobs", jobs)
        object.__setattr__(
            self,
            "pushed_transform_ids",
            tuple(self.pushed_transform_ids),
        )


class DomainCompiler(Protocol):
    """Pure compiler plus runtime binding for one explicit domain target."""

    @property
    def compiler_id(self) -> str: ...

    @property
    def target_id(self) -> str: ...

    def compile(self, request: DomainCompileRequest) -> DomainCompilation | None: ...

    def prepare(
        self,
        job: DomainCompiledJob,
        context: DomainBatchContext,
    ) -> PreparedDomainExecution: ...


def validate_domain_compilation(
    request: DomainCompileRequest,
    compilation: DomainCompilation,
) -> None:
    """Require exact point coverage without crossing a barrier region."""

    expected = tuple(
        ordinal for region in request.barrier_regions for ordinal in region
    )
    selected = tuple(
        ordinal for job in compilation.jobs for ordinal in job.point_ordinals
    )
    if tuple(sorted(selected)) != expected or len(selected) != len(set(selected)):
        msg = "compiled domain jobs must cover every logical point exactly once"
        raise ValueError(msg)
    regions = tuple(frozenset(region) for region in request.barrier_regions)
    for job in compilation.jobs:
        points = frozenset(job.point_ordinals)
        if not any(points <= region for region in regions):
            msg = f"compiled domain job {job.id!r} crosses a barrier region"
            raise ValueError(msg)
    _validate_transform_pushdown(request, compilation)


def _validate_transform_pushdown(
    request: DomainCompileRequest,
    compilation: DomainCompilation,
) -> None:
    transforms = request.call.measurement_transforms
    pushed = compilation.pushed_transform_ids
    pushed_set = set(pushed)
    if len(pushed) != len(pushed_set):
        raise ValueError("pushed measurement transform ids must be unique")
    canonical = tuple(
        transform.id for transform in transforms if transform.id in pushed_set
    )
    if pushed != canonical:
        raise ValueError("pushed measurement transforms must follow graph order")
    known_ids = {transform.id for transform in transforms}
    if pushed_set - known_ids:
        raise ValueError("domain compilation pushed an unknown measurement transform")

    available = {
        product_use.id
        for result in request.call.results
        for product_use in result.product_uses
    }
    for transform in transforms:
        if transform.id not in pushed_set:
            continue
        if transform.semantic.portability != "portable":
            raise ValueError("domain compilation cannot push a host-only transform")
        required = {input_port.product_use.id for input_port in transform.inputs}
        if not required <= available:
            raise ValueError("pushed measurement transforms are not dependency closed")
        available.update(
            product_use.id
            for output in transform.outputs
            for product_use in output.product_uses
        )


def compiled_jobs(
    request: DomainCompileRequest,
    *,
    compiler_id: str,
    target_id: str,
    max_points: int,
    artifacts: Sequence[object] | None = None,
    pushed_transform_ids: Sequence[str] = (),
) -> DomainCompilation:
    """Build the ordinary contiguous lowering chosen by a domain compiler."""

    partitions = request.partition(max_points=max_points)
    selected_artifacts = tuple(artifacts) if artifacts is not None else partitions
    if len(selected_artifacts) != len(partitions):
        raise ValueError("compiled artifacts must match the selected job partition")
    compilation = DomainCompilation(
        compiler_id=compiler_id,
        target_id=target_id,
        jobs=tuple(
            DomainCompiledJob(
                id=f"{compiler_id}.job-{index}",
                point_ordinals=ordinals,
                artifact=artifact,
            )
            for index, (ordinals, artifact) in enumerate(
                zip(partitions, selected_artifacts, strict=True)
            )
        ),
        pushed_transform_ids=tuple(pushed_transform_ids),
    )
    validate_domain_compilation(request, compilation)
    return compilation


__all__ = [
    "DomainBoundPoint",
    "DomainCompilation",
    "DomainCompileRequest",
    "DomainCompiledJob",
    "DomainCompiler",
    "DomainResidualInput",
    "compiled_jobs",
    "validate_domain_compilation",
]
