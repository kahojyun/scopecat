"""Pure, bounded domain lowering over typed residual experiment semantics.

The SDK receives owned normal forms and a read-only exact iteration
projection. The accepted configuration selects and reserves one complete
target footprint, ``compile`` chooses jobs and absorption claims without
external effects, and ``prepare`` closes one selected job over its runtime
context. Separating these phases allows symbolic target specialization without
acquiring live resources.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Protocol, cast

from scopecat.compiler.relations.point_domain import point_axis_linear_value
from scopecat.compiler.relations.scalar_eval import CellValue, eval_binary
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.records.parameter import Quantity
from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.view import DomainCallView

type DomainAffineNumber = int | float


@dataclass(frozen=True, slots=True)
class DomainPointLinearValues:
    """A constant-space exact linear sequence for one known point axis."""

    center: Quantity
    span: Quantity
    count: int

    def __len__(self) -> int:
        return self.count

    def __getitem__(self, index: int) -> Quantity:
        return point_axis_linear_value(self.center, self.span, self.count, index)


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
    values: tuple[object, ...] | DomainPointLinearValues
    repeat_each: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.values, DomainPointLinearValues):
            object.__setattr__(self, "values", deepcopy(tuple(self.values)))

    def values_at(self, ordinals: Sequence[int]) -> tuple[object, ...]:
        """Select axis values without materializing domain input expressions."""

        return tuple(
            self.values[(ordinal // self.repeat_each) % len(self.values)]
            for ordinal in ordinals
        )


@dataclass(frozen=True, slots=True)
class DomainIterationLayout:
    """SDK-owned known axes and preferred capacity-alignment size."""

    axes: tuple[DomainPointAxis, ...] = ()
    preferred_tile_size: int | None = None

    def __post_init__(self) -> None:
        axes = tuple(self.axes)
        axis_ids = tuple(axis.id for axis in axes)
        if len(axis_ids) != len(set(axis_ids)):
            raise ValueError("domain point axis ids must be unique")
        if self.preferred_tile_size is not None and self.preferred_tile_size < 0:
            raise ValueError("domain preferred tile size must be nonnegative")
        object.__setattr__(self, "axes", axes)
        if self.preferred_tile_size == 0:
            object.__setattr__(self, "preferred_tile_size", None)

    def point_axis(self, name: str) -> DomainPointAxis | None:
        return next((axis for axis in self.axes if axis.id == name), None)

    def partition_by_axes(
        self,
        axis_ids: Sequence[str],
        ordinals: Sequence[int],
    ) -> tuple[tuple[int, ...], ...] | None:
        """Partition selected ordinals by exact values of the requested axes.

        ``None`` means at least one requested axis has dynamic values. Empty
        support is one invariant coverage. Only adjacent equal projections are
        joined, so caller-supplied effect and capacity boundaries remain
        authoritative.
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

    def decode_collection[ItemT, CollectionT](
        self,
        name: str,
        decode: Callable[[Sequence[ItemT]], CollectionT],
    ) -> tuple[CollectionT, ...]:
        """Decode one collection-valued input independently at every point.

        Collection values cross the generic domain boundary as ``object``;
        keeping that cast here lets domain compilers retain typed parameter
        models without repeating transport details.
        """

        return tuple(
            decode(cast("Sequence[ItemT]", value)) for value in self.input(name)
        )


@dataclass(frozen=True, slots=True)
class DomainCompiledInputs:
    """Program and compiler-only columns resolved for one target artifact."""

    program: DomainResolvedInputs
    compiler: DomainResolvedInputs

    def __post_init__(self) -> None:
        if self.program.ordinals != self.compiler.ordinals:
            raise ValueError("compiled domain input point coverage must match")

    @property
    def ordinals(self) -> tuple[int, ...]:
        return self.program.ordinals


type DomainInputBinder = Callable[
    [Sequence[str], Sequence[int], int],
    tuple[tuple[str, tuple[object, ...]], ...],
]


@dataclass(frozen=True, slots=True)
class DomainCompileTemplate:
    """Static domain target projection shared by every coverage request."""

    call: DomainCallView
    program_inputs: tuple[DomainInput, ...]
    compiler_inputs: tuple[DomainInput, ...]
    iteration_layout: DomainIterationLayout | None = None

    def bind_coverage(
        self,
        barrier_regions: Sequence[Sequence[int]],
        program_input_binder: DomainInputBinder,
        compiler_input_binder: DomainInputBinder,
    ) -> DomainCompileRequest:
        return DomainCompileRequest(
            call=self.call,
            program_inputs=self.program_inputs,
            compiler_inputs=self.compiler_inputs,
            barrier_regions=tuple(tuple(region) for region in barrier_regions),
            program_input_binder=program_input_binder,
            compiler_input_binder=compiler_input_binder,
            iteration_layout=self.iteration_layout,
        )


@dataclass(frozen=True, slots=True)
class DomainCompileRequest:
    """One symbolic point space and its bounded domain-call coverage.

    Barrier regions contain exact canonical ordinals and are authoritative:
    target partitions may refine but never cross them. Program inputs may
    remain residual at prepare time. Compiler inputs are always resolved into
    target artifacts, so both use independent bounded binder namespaces.
    """

    call: DomainCallView
    program_inputs: tuple[DomainInput, ...]
    compiler_inputs: tuple[DomainInput, ...]
    barrier_regions: tuple[tuple[int, ...], ...]
    program_input_binder: DomainInputBinder = field(repr=False, compare=False)
    compiler_input_binder: DomainInputBinder = field(repr=False, compare=False)
    iteration_layout: DomainIterationLayout | None = None

    def __post_init__(self) -> None:
        program_inputs = tuple(self.program_inputs)
        compiler_inputs = tuple(self.compiler_inputs)
        regions = tuple(tuple(region) for region in self.barrier_regions)
        _validate_input_order(
            "program",
            program_inputs,
            tuple(port.id for port in self.call.program.inputs),
        )
        _validate_input_order(
            "compiler",
            compiler_inputs,
            tuple(port.id for port in self.call.program.compiler_inputs),
        )
        selected_ordinals = tuple(ordinal for region in regions for ordinal in region)
        if any(
            following != preceding + 1
            for preceding, following in pairwise(selected_ordinals)
        ):
            msg = "domain barrier regions must select contiguous logical point ordinals"
            raise ValueError(msg)
        if any(not region for region in regions):
            raise ValueError("domain barrier regions must be non-empty")
        object.__setattr__(self, "program_inputs", program_inputs)
        object.__setattr__(self, "compiler_inputs", compiler_inputs)
        object.__setattr__(self, "barrier_regions", regions)

    def program_input(self, name: str) -> DomainInput:
        for input_value in self.program_inputs:
            if input_value.id == name:
                return input_value
        raise KeyError(name)

    def compiler_input(self, name: str) -> DomainInput:
        for input_value in self.compiler_inputs:
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

    def resolve_program_inputs(
        self,
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        *,
        max_points: int,
    ) -> DomainResolvedInputs:
        return self._resolve_inputs(
            self.program_inputs,
            self.program_input_binder,
            input_ids,
            ordinals,
            max_points=max_points,
        )

    def resolve_compiler_inputs(
        self,
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        *,
        max_points: int,
    ) -> DomainResolvedInputs:
        return self._resolve_inputs(
            self.compiler_inputs,
            self.compiler_input_binder,
            input_ids,
            ordinals,
            max_points=max_points,
        )

    def _resolve_inputs(
        self,
        available_inputs: tuple[DomainInput, ...],
        binder: DomainInputBinder,
        input_ids: Sequence[str],
        ordinals: Sequence[int],
        *,
        max_points: int,
    ) -> DomainResolvedInputs:
        """Resolve one input namespace from normal forms or its binder."""

        requested_input_ids = tuple(input_ids)
        requested_input_set = set(requested_input_ids)
        known_input_ids = tuple(input_value.id for input_value in available_inputs)
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
        by_id = {input_value.id: input_value for input_value in available_inputs}
        for input_id in selected_input_ids:
            input_value = by_id[input_id]
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
        bound = binder(tuple(unresolved), selected, max_points) if unresolved else ()
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


def _validate_input_order(
    kind: str,
    inputs: tuple[DomainInput, ...],
    expected_ids: tuple[str, ...],
) -> None:
    input_ids = tuple(input_value.id for input_value in inputs)
    if len(input_ids) != len(set(input_ids)):
        raise ValueError(f"domain {kind} input ids must be unique")
    if input_ids != expected_ids:
        raise ValueError(f"domain {kind} inputs must follow the complete port order")


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
    """Pure target lowering with absorption and opaque-binder evidence.

    Exact ordinal coverage preserves logical result identity. Absorption claims
    make target ownership explicit and determine the residual host work.
    """

    jobs: tuple[DomainCompiledJob, ...]
    absorbed_input_ids: tuple[str, ...] = ()
    absorbed_transform_ids: tuple[str, ...] = ()
    binder_input_ids: tuple[str, ...] = ()
    compiler_input_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        jobs = tuple(self.jobs)
        job_ids = tuple(job.id for job in jobs)
        absorbed_input_ids = tuple(self.absorbed_input_ids)
        absorbed_transform_ids = tuple(self.absorbed_transform_ids)
        binder_input_ids = tuple(self.binder_input_ids)
        compiler_input_ids = tuple(self.compiler_input_ids)
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("compiled domain job ids must be unique")
        if len(binder_input_ids) != len(set(binder_input_ids)):
            raise ValueError("compiled binder input ids must be unique")
        if len(compiler_input_ids) != len(set(compiler_input_ids)):
            raise ValueError("compiled compiler input ids must be unique")
        object.__setattr__(self, "jobs", jobs)
        object.__setattr__(self, "absorbed_input_ids", absorbed_input_ids)
        object.__setattr__(self, "absorbed_transform_ids", absorbed_transform_ids)
        object.__setattr__(self, "binder_input_ids", binder_input_ids)
        object.__setattr__(self, "compiler_input_ids", compiler_input_ids)


class DomainCompiler(Protocol):
    """One experiment system's pure compiler and runtime preparation boundary.

    Domain input normal forms and their binder come from accepted experiment
    semantics; parameter lookup relations within them reflect the accepted
    snapshot and any point-local overlays. Compiler implementations resolve
    through the request boundary rather than a mutable parameter registry,
    keeping check, preview, and run reproducible against the same semantics.

    The accepted system configuration selects one target and reserves its
    complete physical footprint for the run. ``supports`` and ``compile`` must
    not inspect live state or perform effects. ``prepare`` may close target
    artifacts and runtime bindings for a selected single-use job, but
    submission remains an interpreter effect.
    """

    @property
    def target_id(self) -> str: ...

    def supports(self, call: DomainCallView) -> bool: ...

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
    known_input_ids = tuple(input_value.id for input_value in request.program_inputs)
    binder_input_set = set(compilation.binder_input_ids)
    if compilation.binder_input_ids != tuple(
        input_id for input_id in known_input_ids if input_id in binder_input_set
    ):
        raise ValueError("compiled binder inputs must be known and follow typed order")
    if binder_input_set - set(compilation.absorbed_input_ids):
        raise ValueError("domain compiler concretized a residual input with the binder")
    known_compiler_input_ids = tuple(
        input_value.id for input_value in request.compiler_inputs
    )
    if compilation.compiler_input_ids != known_compiler_input_ids:
        raise ValueError("domain compiler must consume every compiler input in order")


def _validate_absorption(
    request: DomainCompileRequest,
    compilation: DomainCompilation,
) -> None:
    _validate_absorbed_ids(
        kind="input",
        canonical_ids=tuple(input_value.id for input_value in request.program_inputs),
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
    compile_artifact: Callable[[DomainCompiledInputs], object] | None = None,
    artifact_input_ids: Sequence[str] = (),
    absorbed_input_ids: Sequence[str] = (),
    absorbed_transform_ids: Sequence[str] = (),
) -> DomainCompilation:
    """Partition, resolve selected columns, and lower ordinary target jobs."""

    artifact_input_ids = tuple(artifact_input_ids)
    if len(artifact_input_ids) != len(set(artifact_input_ids)):
        raise ValueError("domain artifact input ids must be unique")
    absorbed_inputs = _canonical_absorbed_ids(
        tuple(input_value.id for input_value in request.program_inputs),
        (*absorbed_input_ids, *artifact_input_ids),
    )
    absorbed_transforms = _canonical_absorbed_ids(
        tuple(transform.id for transform in request.call.measurement_transforms),
        absorbed_transform_ids,
    )
    jobs: list[DomainCompiledJob] = []
    binder_input_ids: set[str] = set()
    compiler_input_ids = tuple(
        input_value.id for input_value in request.compiler_inputs
    )
    if compiler_input_ids and compile_artifact is None:
        raise ValueError("domain compiler inputs require an artifact compiler")
    for index, ordinals in enumerate(request.partition(max_points=max_points)):
        resolved_program_inputs = request.resolve_program_inputs(
            artifact_input_ids,
            ordinals,
            max_points=max_points,
        )
        resolved_compiler_inputs = request.resolve_compiler_inputs(
            compiler_input_ids,
            ordinals,
            max_points=max_points,
        )
        binder_input_ids.update(resolved_program_inputs.binder_input_ids)
        resolved_inputs = DomainCompiledInputs(
            program=resolved_program_inputs,
            compiler=resolved_compiler_inputs,
        )
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
            for input_value in request.program_inputs
            if input_value.id in binder_input_ids
        ),
        compiler_input_ids=compiler_input_ids,
    )
    validate_domain_compilation(request, compilation)
    return compilation


__all__ = [
    "DomainCompilation",
    "DomainCompileRequest",
    "DomainCompileTemplate",
    "DomainCompiledInputs",
    "DomainCompiledJob",
    "DomainCompiler",
    "DomainInput",
    "DomainInputBinder",
    "DomainIterationLayout",
    "DomainLiteral",
    "DomainPointAffine",
    "DomainPointAxis",
    "DomainPointLinearValues",
    "DomainResolvedInputs",
    "compiled_jobs",
    "validate_domain_compilation",
]
