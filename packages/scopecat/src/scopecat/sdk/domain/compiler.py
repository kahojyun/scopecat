"""Pure domain compilation over typed residual experiment semantics."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from itertools import pairwise
from math import prod
from typing import Protocol, cast

from scopecat.compiler.relations.scalar_eval import CellValue, eval_binary
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.resource_identity import ResourceClaim
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.view import DomainCallView

type DomainAffineNumber = int | float


@dataclass(frozen=True, slots=True)
class DomainLiteral:
    """One scalar value closed by core partial evaluation."""

    value: object

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", deepcopy(self.value))


@dataclass(frozen=True, slots=True)
class DomainPointAffine:
    """One numeric affine function of a single logical point column."""

    point_column_id: str
    scale: DomainAffineNumber
    offset: DomainAffineNumber

    def apply(self, value: object) -> object:
        """Evaluate this normal form with core scalar arithmetic semantics."""

        selected = cast("CellValue", value)
        scaled = (
            deepcopy(selected)
            if self.scale == 1
            else eval_binary("*", self.scale, selected)
        )
        return scaled if self.offset == 0 else eval_binary("+", scaled, self.offset)


@dataclass(frozen=True, slots=True)
class DomainPointAxis:
    """Exact values of one finite point column in logical ordinal order."""

    id: str
    values: tuple[object, ...]
    repeat_each: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", deepcopy(tuple(self.values)))

    def values_at(self, ordinals: Sequence[int]) -> tuple[object, ...]:
        """Select axis values without materializing domain input expressions."""

        return tuple(
            self.values[(ordinal // self.repeat_each) % len(self.values)]
            for ordinal in ordinals
        )


@dataclass(frozen=True, slots=True)
class DomainIterationUnit:
    """Exact-one identity in a projected iteration layout."""

    @property
    def extent(self) -> int:
        return 1


@dataclass(frozen=True, slots=True)
class DomainIterationLeaf:
    """One positional relation leaf providing zero or more point axes."""

    axis_ids: tuple[str, ...]
    extent: int | None

    def __post_init__(self) -> None:
        if self.extent is not None and self.extent < 0:
            raise ValueError("domain iteration leaf extent must be nonnegative")
        if len(self.axis_ids) != len(set(self.axis_ids)):
            raise ValueError("domain iteration leaf axis ids must be unique")


@dataclass(frozen=True, slots=True)
class DomainIterationOpaque:
    """A layout region whose structure is not safely projectable."""

    extent: int | None

    def __post_init__(self) -> None:
        if self.extent is not None and self.extent < 0:
            raise ValueError("domain opaque iteration extent must be nonnegative")


@dataclass(frozen=True, slots=True)
class DomainIterationDependent:
    """Ordered product whose right layout is evaluated per left point."""

    left: DomainIterationNode
    right: DomainIterationNode
    extent: int | None

    def __post_init__(self) -> None:
        if self.extent is not None and self.extent < 0:
            raise ValueError("domain dependent iteration extent must be nonnegative")


@dataclass(frozen=True, slots=True)
class DomainIterationProduct:
    """Ordered left-major Cartesian iteration; the last factor is fastest."""

    factors: tuple[DomainIterationNode, ...]

    def __post_init__(self) -> None:
        if len(self.factors) < 2:
            raise ValueError("domain iteration product requires at least two factors")

    @property
    def extent(self) -> int | None:
        extents = tuple(factor.extent for factor in self.factors)
        if any(item is None for item in extents):
            return None
        return prod(cast("tuple[int, ...]", extents))


@dataclass(frozen=True, slots=True)
class DomainIterationZip:
    """Positional iteration of equally long sources."""

    sources: tuple[DomainIterationNode, ...]
    extent: int | None

    def __post_init__(self) -> None:
        if len(self.sources) < 2:
            raise ValueError("domain iteration zip requires at least two sources")
        if self.extent is not None and self.extent < 0:
            raise ValueError("domain iteration zip extent must be nonnegative")


type DomainIterationNode = (
    DomainIterationUnit
    | DomainIterationLeaf
    | DomainIterationOpaque
    | DomainIterationDependent
    | DomainIterationProduct
    | DomainIterationZip
)


@dataclass(frozen=True, slots=True)
class DomainIterationLayout:
    """SDK-owned exact/opaque projection of logical scan nesting and axes."""

    root: DomainIterationNode
    axes: tuple[DomainPointAxis, ...] = ()

    def __post_init__(self) -> None:
        axes = tuple(self.axes)
        axis_ids = tuple(axis.id for axis in axes)
        if len(axis_ids) != len(set(axis_ids)):
            raise ValueError("domain point axis ids must be unique")
        leaf_axis_ids = tuple(_iteration_axis_ids(self.root))
        if leaf_axis_ids != axis_ids:
            raise ValueError(
                "domain iteration leaves must own projected axes in layout order"
            )
        object.__setattr__(self, "axes", axes)

    def point_axis(self, name: str) -> DomainPointAxis | None:
        return next((axis for axis in self.axes if axis.id == name), None)

    def partition_by_axes(
        self,
        axis_ids: Sequence[str],
        ordinals: Sequence[int],
    ) -> tuple[tuple[int, ...], ...] | None:
        """Partition selected ordinals by exact values of the requested axes.

        ``None`` means at least one requested axis crosses an opaque layout
        boundary. Empty support is one invariant coverage. Only adjacent equal
        projections are joined, so effect and capacity boundaries supplied by
        the caller remain authoritative.
        """

        selected = tuple(ordinals)
        requested = tuple(axis_ids)
        if len(requested) != len(set(requested)):
            raise ValueError("domain variation axis ids must be unique")
        axes = tuple(self.point_axis(axis_id) for axis_id in requested)
        if any(axis is None for axis in axes):
            return None
        if not selected:
            return ()
        exact_axes = cast("tuple[DomainPointAxis, ...]", axes)
        signatures = tuple(
            stable_content_hash(
                tuple(
                    content_fingerprint(value)
                    for axis in exact_axes
                    for value in axis.values_at((ordinal,))
                )
            )
            for ordinal in selected
        )
        partitions: list[tuple[int, ...]] = []
        start = 0
        for offset in range(1, len(selected)):
            if signatures[offset] != signatures[start]:
                partitions.append(selected[start:offset])
                start = offset
        partitions.append(selected[start:])
        return tuple(partitions)

    @property
    def preferred_tile_size(self) -> int | None:
        """Return the complete innermost sweep size when it is exact."""

        node = (
            self.root.factors[-1]
            if isinstance(self.root, DomainIterationProduct)
            else self.root.right
            if isinstance(self.root, DomainIterationDependent)
            else self.root
        )
        extent = node.extent
        return extent if extent not in {None, 0} else None


def _iteration_axis_ids(node: DomainIterationNode) -> tuple[str, ...]:
    if isinstance(node, DomainIterationLeaf):
        return node.axis_ids
    if isinstance(node, DomainIterationProduct):
        return tuple(
            axis_id
            for factor in node.factors
            for axis_id in _iteration_axis_ids(factor)
        )
    if isinstance(node, DomainIterationDependent):
        return (*_iteration_axis_ids(node.left), *_iteration_axis_ids(node.right))
    if isinstance(node, DomainIterationZip):
        return tuple(
            axis_id
            for source in node.sources
            for axis_id in _iteration_axis_ids(source)
        )
    return ()


@dataclass(frozen=True, slots=True)
class DomainInput:
    """One typed program input with an optional SDK-owned normal form."""

    id: str
    normal_form: DomainLiteral | DomainPointAffine | None = field(
        default=None,
        repr=False,
    )

    def __post_init__(self) -> None:
        if not self.id:
            msg = "domain input id must be non-empty"
            raise ValueError(msg)

    @property
    def is_literal(self) -> bool:
        """Return whether partial evaluation produced a scalar literal."""

        return isinstance(self.normal_form, DomainLiteral)

    def literal_value(self) -> object:
        """Read the scalar literal normal form, including a literal ``None``."""

        if not isinstance(self.normal_form, DomainLiteral):
            msg = f"domain input {self.id!r} is not a scalar literal"
            raise ValueError(msg)
        return deepcopy(self.normal_form.value)

    @property
    def point_affine(self) -> DomainPointAffine | None:
        """Project numeric ``scale * point_column + offset`` when exact."""

        return (
            self.normal_form
            if isinstance(self.normal_form, DomainPointAffine)
            else None
        )


@dataclass(frozen=True, slots=True)
class DomainResolvedInputs:
    """Resolved columns plus inputs that required the opaque binder fallback."""

    ordinals: tuple[int, ...]
    columns: tuple[tuple[str, tuple[object, ...]], ...]
    binder_input_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        ordinals = tuple(self.ordinals)
        columns = tuple((name, tuple(values)) for name, values in self.columns)
        names = tuple(name for name, _values in columns)
        binder_input_ids = tuple(self.binder_input_ids)
        if len(names) != len(set(names)):
            raise ValueError("resolved domain input ids must be unique")
        if len(binder_input_ids) != len(set(binder_input_ids)):
            raise ValueError("domain binder input ids must be unique")
        if set(binder_input_ids) - set(names):
            raise ValueError("domain binder inputs must belong to resolved columns")
        if any(len(values) != len(ordinals) for _name, values in columns):
            raise ValueError("resolved domain input columns must match point count")
        object.__setattr__(self, "ordinals", ordinals)
        object.__setattr__(self, "columns", columns)
        object.__setattr__(self, "binder_input_ids", binder_input_ids)

    def input(self, name: str) -> tuple[object, ...]:
        """Return one input column in selected ordinal order."""

        for input_name, values in self.columns:
            if input_name == name:
                return values
        raise KeyError(name)


type DomainInputBinder = Callable[
    [Sequence[str], Sequence[int], int],
    tuple[tuple[str, tuple[object, ...]], ...],
]


@dataclass(frozen=True, slots=True)
class DomainCompileTemplate:
    """Static domain target projection shared by every coverage request."""

    call: DomainCallView
    inputs: tuple[DomainInput, ...]
    iteration_layout: DomainIterationLayout | None = None

    def bind_coverage(
        self,
        barrier_regions: Sequence[Sequence[int]],
        input_binder: DomainInputBinder,
    ) -> DomainCompileRequest:
        return DomainCompileRequest(
            call=self.call,
            inputs=self.inputs,
            barrier_regions=tuple(tuple(region) for region in barrier_regions),
            input_binder=input_binder,
            iteration_layout=self.iteration_layout,
        )


@dataclass(frozen=True, slots=True)
class DomainCompileRequest:
    """One symbolic point space and its bounded domain-call region."""

    call: DomainCallView
    inputs: tuple[DomainInput, ...]
    barrier_regions: tuple[tuple[int, ...], ...]
    input_binder: DomainInputBinder = field(repr=False, compare=False)
    iteration_layout: DomainIterationLayout | None = None

    def __post_init__(self) -> None:
        inputs = tuple(self.inputs)
        regions = tuple(tuple(region) for region in self.barrier_regions)
        input_ids = tuple(input_value.id for input_value in inputs)
        if len(input_ids) != len(set(input_ids)):
            raise ValueError("domain input ids must be unique")
        expected_input_ids = tuple(port.id for port in self.call.program.inputs)
        if input_ids != expected_input_ids:
            msg = "domain inputs must follow the complete program input order"
            raise ValueError(msg)
        selected_ordinals = tuple(ordinal for region in regions for ordinal in region)
        if any(
            following != preceding + 1
            for preceding, following in pairwise(selected_ordinals)
        ):
            msg = "domain barrier regions must select contiguous logical point ordinals"
            raise ValueError(msg)
        if any(not region for region in regions):
            raise ValueError("domain barrier regions must be non-empty")
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "barrier_regions", regions)

    def input(self, name: str) -> DomainInput:
        for input_value in self.inputs:
            if input_value.id == name:
                return input_value
        raise KeyError(name)

    def point_axis(self, name: str) -> DomainPointAxis | None:
        """Return an exact finite point axis when core specialization exposed one."""

        layout = self.iteration_layout
        return None if layout is None else layout.point_axis(name)

    def partition_by_axes(
        self,
        axis_ids: Sequence[str],
    ) -> tuple[tuple[int, ...], ...] | None:
        """Project exact axis variation inside the current effect barriers."""

        layout = self.iteration_layout
        if layout is None:
            return None
        partitions: list[tuple[int, ...]] = []
        for region in self.barrier_regions:
            projected = layout.partition_by_axes(axis_ids, region)
            if projected is None:
                return None
            partitions.extend(projected)
        return tuple(partitions)

    def partition(self, *, max_points: int) -> tuple[tuple[int, ...], ...]:
        """Return a contiguous capacity-limited partition within barriers."""

        if type(max_points) is not int or max_points <= 0:
            raise ValueError("domain job capacity must be a positive integer")
        preferred = (
            None
            if self.iteration_layout is None
            else self.iteration_layout.preferred_tile_size
        )
        return tuple(
            block
            for region in self.barrier_regions
            for block in _partition_region(
                region,
                max_points=max_points,
                preferred_tile_size=preferred,
            )
        )

    def resolve_inputs(
        self,
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        *,
        max_points: int,
    ) -> DomainResolvedInputs:
        """Resolve a selected input set from normal forms or one binder call."""

        requested_input_ids = tuple(input_ids)
        requested_input_set = set(requested_input_ids)
        known_input_ids = tuple(input_value.id for input_value in self.inputs)
        selected_input_ids = tuple(
            input_id for input_id in known_input_ids if input_id in requested_input_set
        )
        if len(requested_input_ids) != len(requested_input_set):
            raise ValueError("domain input binding ids must be unique")
        if requested_input_set - set(known_input_ids):
            raise ValueError("domain input binding selects an unknown input")
        selected = tuple(ordinals)
        if type(max_points) is not int or max_points <= 0:
            raise ValueError("domain input binding budget must be positive")
        if len(selected) > max_points:
            raise ValueError("domain input binding exceeds the requested budget")
        known_ordinals = frozenset(
            ordinal for region in self.barrier_regions for ordinal in region
        )
        if any(ordinal not in known_ordinals for ordinal in selected):
            raise ValueError("domain input binding selects an unknown ordinal")
        resolved: dict[str, tuple[object, ...]] = {}
        unresolved: list[str] = []
        for input_id in selected_input_ids:
            input_value = self.input(input_id)
            if input_value.is_literal:
                value = input_value.literal_value()
                resolved[input_id] = tuple(deepcopy(value) for _ordinal in selected)
                continue
            affine = input_value.point_affine
            axis = None if affine is None else self.point_axis(affine.point_column_id)
            if affine is not None and axis is not None:
                resolved[input_id] = tuple(
                    affine.apply(value) for value in axis.values_at(selected)
                )
                continue
            unresolved.append(input_id)
        bound = (
            self.input_binder(tuple(unresolved), selected, max_points)
            if unresolved
            else ()
        )
        if tuple(name for name, _values in bound) != tuple(unresolved):
            raise ValueError("domain input binder must return exactly selected inputs")
        if any(len(values) != len(selected) for _name, values in bound):
            msg = "domain input binder columns must match the selected point count"
            raise ValueError(msg)
        resolved.update(bound)
        return DomainResolvedInputs(
            ordinals=selected,
            columns=tuple(
                (input_id, resolved[input_id]) for input_id in selected_input_ids
            ),
            binder_input_ids=tuple(unresolved),
        )


@dataclass(frozen=True, slots=True)
class DomainCompiledJob:
    """One lightweight target recipe assigned to exact logical point ordinals."""

    id: str
    point_ordinals: tuple[int, ...]
    artifact_factory: Callable[[], object] | None = field(repr=False)

    def __post_init__(self) -> None:
        ordinals = tuple(self.point_ordinals)
        if not self.id or not ordinals:
            raise ValueError("compiled domain job id and points must be non-empty")
        if ordinals != tuple(sorted(set(ordinals))):
            msg = "compiled domain job ordinals must be unique and canonical"
            raise ValueError(msg)
        object.__setattr__(self, "point_ordinals", ordinals)

    def take_artifact(self) -> object:
        """Materialize and release this job's one-shot target recipe."""

        factory = self.artifact_factory
        if factory is None:
            raise RuntimeError(f"compiled domain job {self.id!r} was already prepared")
        object.__setattr__(self, "artifact_factory", None)
        return factory()


@dataclass(frozen=True, slots=True)
class DomainCompilation:
    """Pure target lowering with absorption and opaque-binder evidence."""

    jobs: tuple[DomainCompiledJob, ...]
    absorbed_input_ids: tuple[str, ...] = ()
    absorbed_transform_ids: tuple[str, ...] = ()
    binder_input_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        jobs = tuple(self.jobs)
        job_ids = tuple(job.id for job in jobs)
        absorbed_input_ids = tuple(self.absorbed_input_ids)
        absorbed_transform_ids = tuple(self.absorbed_transform_ids)
        binder_input_ids = tuple(self.binder_input_ids)
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("compiled domain job ids must be unique")
        if len(binder_input_ids) != len(set(binder_input_ids)):
            raise ValueError("compiled binder input ids must be unique")
        object.__setattr__(self, "jobs", jobs)
        object.__setattr__(self, "absorbed_input_ids", absorbed_input_ids)
        object.__setattr__(self, "absorbed_transform_ids", absorbed_transform_ids)
        object.__setattr__(self, "binder_input_ids", binder_input_ids)


class DomainCompiler(Protocol):
    """Pure system compiler plus runtime binding for domain calls."""

    def claim_resources(
        self,
        call: DomainCallView,
    ) -> tuple[ResourceClaim, ...] | None: ...

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
    _validate_absorption(request, compilation)
    known_input_ids = tuple(input_value.id for input_value in request.inputs)
    binder_input_set = set(compilation.binder_input_ids)
    if compilation.binder_input_ids != tuple(
        input_id for input_id in known_input_ids if input_id in binder_input_set
    ):
        raise ValueError("compiled binder inputs must be known and follow typed order")
    if binder_input_set - set(compilation.absorbed_input_ids):
        raise ValueError("domain compiler concretized a residual input with the binder")


def _validate_absorption(
    request: DomainCompileRequest,
    compilation: DomainCompilation,
) -> None:
    _validate_absorbed_ids(
        kind="input",
        canonical_ids=tuple(input_value.id for input_value in request.inputs),
        absorbed_ids=compilation.absorbed_input_ids,
    )
    transforms = request.call.measurement_transforms
    absorbed_set = _validate_absorbed_ids(
        kind="measurement transform",
        canonical_ids=tuple(transform.id for transform in transforms),
        absorbed_ids=compilation.absorbed_transform_ids,
    )

    available = {
        product_use.id
        for result in request.call.results
        for product_use in result.product_uses
    }
    for transform in transforms:
        if transform.id not in absorbed_set:
            continue
        if transform.semantic.portability != "portable":
            raise ValueError("domain compilation cannot absorb a host-only transform")
        required = {input_port.product_use.id for input_port in transform.inputs}
        if not required <= available:
            raise ValueError(
                "absorbed measurement transforms are not dependency closed"
            )
        available.update(
            product_use.id
            for output in transform.outputs
            for product_use in output.product_uses
        )


def _validate_absorbed_ids(
    *,
    kind: str,
    canonical_ids: tuple[str, ...],
    absorbed_ids: tuple[str, ...],
) -> set[str]:
    absorbed = set(absorbed_ids)
    if len(absorbed_ids) != len(absorbed):
        raise ValueError(f"absorbed domain {kind} ids must be unique")
    canonical_absorbed = tuple(item for item in canonical_ids if item in absorbed)
    if absorbed_ids != canonical_absorbed:
        raise ValueError(
            f"absorbed domain {kind}s must be known and follow typed order"
        )
    return absorbed


def _canonical_absorbed_ids(
    canonical_ids: Sequence[str], selected_ids: Sequence[str]
) -> tuple[str, ...]:
    selected = set(selected_ids)
    if selected - set(canonical_ids):
        raise ValueError("domain compilation absorbed an unknown item")
    return tuple(item for item in canonical_ids if item in selected)


def _partition_region(
    region: tuple[int, ...],
    *,
    max_points: int,
    preferred_tile_size: int | None,
) -> tuple[tuple[int, ...], ...]:
    if preferred_tile_size is None or preferred_tile_size > max_points:
        return tuple(
            tuple(region[offset : offset + max_points])
            for offset in range(0, len(region), max_points)
        )
    blocks: list[tuple[int, ...]] = []
    offset = 0
    while offset < len(region):
        remaining = len(region) - offset
        if remaining <= max_points:
            blocks.append(tuple(region[offset:]))
            break
        limit = offset + max_points
        aligned_end = next(
            (
                end
                for end in range(limit, offset, -1)
                if (region[end - 1] + 1) % preferred_tile_size == 0
            ),
            limit,
        )
        blocks.append(tuple(region[offset:aligned_end]))
        offset = aligned_end
    return tuple(blocks)


def compiled_jobs(
    request: DomainCompileRequest,
    *,
    max_points: int,
    compile_artifact: Callable[[DomainResolvedInputs], object] | None = None,
    artifact_input_ids: Sequence[str] = (),
    absorbed_input_ids: Sequence[str] = (),
    absorbed_transform_ids: Sequence[str] = (),
) -> DomainCompilation:
    """Partition, resolve selected columns, and lower ordinary target jobs."""

    artifact_input_ids = tuple(artifact_input_ids)
    if len(artifact_input_ids) != len(set(artifact_input_ids)):
        raise ValueError("domain artifact input ids must be unique")
    absorbed_inputs = _canonical_absorbed_ids(
        tuple(input_value.id for input_value in request.inputs),
        (*absorbed_input_ids, *artifact_input_ids),
    )
    absorbed_transforms = _canonical_absorbed_ids(
        tuple(transform.id for transform in request.call.measurement_transforms),
        absorbed_transform_ids,
    )
    jobs: list[DomainCompiledJob] = []
    binder_input_ids: set[str] = set()
    for index, ordinals in enumerate(request.partition(max_points=max_points)):
        resolved_inputs = request.resolve_inputs(
            artifact_input_ids,
            ordinals,
            max_points=max_points,
        )
        binder_input_ids.update(resolved_inputs.binder_input_ids)
        jobs.append(
            DomainCompiledJob(
                id=f"job-{index}",
                point_ordinals=ordinals,
                artifact_factory=(
                    (lambda selected=ordinals: selected)
                    if compile_artifact is None
                    else (
                        lambda lower=compile_artifact, inputs=resolved_inputs: lower(
                            inputs
                        )
                    )
                ),
            )
        )
    compilation = DomainCompilation(
        jobs=tuple(jobs),
        absorbed_input_ids=absorbed_inputs,
        absorbed_transform_ids=absorbed_transforms,
        binder_input_ids=tuple(
            input_value.id
            for input_value in request.inputs
            if input_value.id in binder_input_ids
        ),
    )
    validate_domain_compilation(request, compilation)
    return compilation


__all__ = [
    "DomainCompilation",
    "DomainCompileRequest",
    "DomainCompileTemplate",
    "DomainCompiledJob",
    "DomainCompiler",
    "DomainInput",
    "DomainInputBinder",
    "DomainIterationDependent",
    "DomainIterationLayout",
    "DomainIterationLeaf",
    "DomainIterationNode",
    "DomainIterationOpaque",
    "DomainIterationProduct",
    "DomainIterationUnit",
    "DomainIterationZip",
    "DomainLiteral",
    "DomainPointAffine",
    "DomainPointAxis",
    "DomainResolvedInputs",
    "compiled_jobs",
    "validate_domain_compilation",
]
