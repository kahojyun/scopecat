"""Pure, bounded domain lowering over typed residual experiment semantics."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Protocol, cast

from scopecat.sdk.domain.context import DomainBatchContext
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.view import DomainCallView


@dataclass(frozen=True, slots=True)
class DomainIterationLayout:
    """Preferred capacity-alignment size derived from the point layout."""

    preferred_tile_size: int | None = None

    def __post_init__(self) -> None:
        if self.preferred_tile_size is not None and self.preferred_tile_size < 0:
            raise ValueError("domain preferred tile size must be nonnegative")
        if self.preferred_tile_size == 0:
            object.__setattr__(self, "preferred_tile_size", None)


@dataclass(frozen=True, slots=True)
class DomainInput:
    """One program or compiler input available through its binder."""

    id: str

    def __post_init__(self) -> None:
        if not self.id:
            msg = "domain input id must be non-empty"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class DomainResolvedInputs:
    """Input columns resolved by a bounded binder."""

    ordinals: tuple[int, ...]
    columns: tuple[tuple[str, tuple[object, ...]], ...]

    def __post_init__(self) -> None:
        ordinals = tuple(self.ordinals)
        columns = tuple((name, tuple(values)) for name, values in self.columns)
        names = tuple(name for name, _values in columns)
        if len(names) != len(set(names)):
            raise ValueError("resolved domain input ids must be unique")
        if any(len(values) != len(ordinals) for _name, values in columns):
            raise ValueError("resolved domain input columns must match point count")
        object.__setattr__(self, "ordinals", ordinals)
        object.__setattr__(self, "columns", columns)

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
        """Resolve one input namespace through its binder."""

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
        bound = (
            binder(selected_input_ids, selected, max_points)
            if selected_input_ids
            else ()
        )
        if tuple(name for name, _values in bound) != selected_input_ids:
            raise ValueError("domain input binder must return exactly selected inputs")
        if any(len(values) != len(selected) for _name, values in bound):
            msg = "domain input binder columns must match the selected point count"
            raise ValueError(msg)
        return DomainResolvedInputs(
            ordinals=selected,
            columns=bound,
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
    """One immutable compiled artifact assigned to exact logical point ordinals."""

    id: str
    point_ordinals: tuple[int, ...]
    artifact: object = field(repr=False)

    def __post_init__(self) -> None:
        ordinals = tuple(self.point_ordinals)
        if not self.id or not ordinals:
            raise ValueError("compiled domain job id and points must be non-empty")
        if ordinals != tuple(sorted(set(ordinals))):
            msg = "compiled domain job ordinals must be unique and canonical"
            raise ValueError(msg)
        object.__setattr__(self, "point_ordinals", ordinals)


@dataclass(frozen=True, slots=True)
class DomainCompilation:
    """Pure target lowering with explicit input absorption.

    Exact ordinal coverage preserves logical result identity. Input absorption
    claims make target ownership explicit and determine residual runtime inputs.
    """

    jobs: tuple[DomainCompiledJob, ...]
    absorbed_input_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        jobs = tuple(self.jobs)
        job_ids = tuple(job.id for job in jobs)
        absorbed_input_ids = tuple(self.absorbed_input_ids)
        if len(job_ids) != len(set(job_ids)):
            raise ValueError("compiled domain job ids must be unique")
        object.__setattr__(self, "jobs", jobs)
        object.__setattr__(self, "absorbed_input_ids", absorbed_input_ids)


class DomainCompiler(Protocol):
    """One experiment system's pure compiler and runtime preparation boundary.

    Domain input binders come from accepted experiment semantics and reflect
    the accepted snapshot plus point-local overlays. Compiler implementations
    resolve through the request boundary rather than a mutable parameter
    registry, keeping check, preview, and run reproducible.

    The accepted system configuration selects one target and reserves its
    complete physical footprint for the run. ``compile`` must be total for that
    target and must not inspect live state or perform effects. ``prepare`` uses
    the resulting immutable artifact to close result and runtime bindings;
    submission remains an interpreter effect.
    """

    @property
    def target_id(self) -> str: ...

    @property
    def target_kind(self) -> str: ...

    def compile(self, request: DomainCompileRequest) -> DomainCompilation: ...

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
    _validate_absorbed_ids(
        kind="input",
        canonical_ids=tuple(input_value.id for input_value in request.program_inputs),
        absorbed_ids=compilation.absorbed_input_ids,
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
) -> DomainCompilation:
    """Partition, resolve columns, and compile immutable artifacts eagerly."""

    artifact_input_ids = tuple(artifact_input_ids)
    if len(artifact_input_ids) != len(set(artifact_input_ids)):
        raise ValueError("domain artifact input ids must be unique")
    absorbed_inputs = _canonical_absorbed_ids(
        tuple(input_value.id for input_value in request.program_inputs),
        (*absorbed_input_ids, *artifact_input_ids),
    )
    jobs: list[DomainCompiledJob] = []
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
        resolved_inputs = DomainCompiledInputs(
            program=resolved_program_inputs,
            compiler=resolved_compiler_inputs,
        )
        jobs.append(
            DomainCompiledJob(
                id=f"job-{index}",
                point_ordinals=ordinals,
                artifact=(
                    ordinals
                    if compile_artifact is None
                    else compile_artifact(resolved_inputs)
                ),
            )
        )
    compilation = DomainCompilation(
        jobs=tuple(jobs),
        absorbed_input_ids=absorbed_inputs,
    )
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
    "DomainResolvedInputs",
    "compiled_jobs",
    "validate_domain_compilation",
]
