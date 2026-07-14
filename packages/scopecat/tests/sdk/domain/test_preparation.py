from __future__ import annotations

import inspect
from importlib import import_module
from pathlib import Path
from typing import get_type_hints

import pytest

import scopecat as sc
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    link_verified_program,
    materialize_linked_points,
)
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.parameter import Quantity
from scopecat.sdk.domain import (
    DomainBatchContext,
    DomainEntryPointBinding,
    DomainExecutionOffer,
    DomainMappedEntry,
    DomainMappedResult,
    DomainMeasurementPlan,
    DomainPreparationBuilder,
    DomainResultMapping,
    DomainResultUseBinding,
    DomainTargetEntry,
)
from scopecat.sdk.domain.context import (
    make_domain_batch_context_internal,
    project_domain_plan_internal,
)
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
    DomainResourceClaim,
    DomainResultValue,
    DomainTargetArtifactIdentity,
)
from scopecat.sdk.domain.measurements import (
    DomainHostTransformBinding,
    DomainHostTransformImplementation,
    MeasurementTransformSemanticContract,
)
from scopecat.sdk.domain.runtime import (
    CorrelatedDomainFetch,
    DomainFetchCandidate,
    DomainFetchRequest,
    DomainReconcileReceipt,
    DomainReconcileRequest,
    DomainSubmitReceipt,
    DomainSubmitRequest,
)
from tests.testkit.authoring import load_config

type _Entry = DomainTargetEntry[str, str]
type _EntryPoint = DomainEntryPointBinding[str]
type _ResultUse = DomainResultUseBinding[str, str]


class _NoEffectsRuntime:
    def submit(
        self,
        request: DomainSubmitRequest[dict[str, str]],
    ) -> DomainSubmitReceipt:
        del request
        raise AssertionError("preparation must not submit")

    def fetch(
        self,
        request: DomainFetchRequest,
    ) -> DomainFetchCandidate[dict[str, str]]:
        del request
        raise AssertionError("preparation must not fetch")

    def reconcile(
        self,
        request: DomainReconcileRequest,
    ) -> DomainReconcileReceipt:
        del request
        raise AssertionError("preparation must not reconcile")


def _preparation_context(
    tmp_path: Path,
    *,
    namespace: str,
    shared_product_uses: bool = False,
) -> DomainBatchContext:
    count_type = sc.ScalarType(sc.IntType(minimum=0))
    count = sc.point(f"{namespace}_count", count_type)
    program = sc.domain_program(
        "program",
        dialect_id="test.preparation",
        dialect_version="1",
        body=object(),
        inputs={"count": count_type},
        results={
            "raw": ("raw", "v1"),
        },
    )
    call = sc.domain_call(
        "execute",
        program,
        inputs={"count": count},
        results={"raw": "raw"},
    )
    transform = sc.measurement_transform(
        "summarize",
        semantic=MeasurementTransformSemanticContract(
            id="test.summarize",
            version="1",
            portability="host_only",
        ),
        inputs={"raw": "raw"},
        outputs={"summary": "summary"},
    )
    module = (
        sc.module(f"test.sdk.preparation.{namespace}")
        .product("raw", "summary", unit="count", dtype="int64")
        .domain_calls(call)
        .measurement_transforms(transform)
        .build()
    )
    template = module.template(
        f"test.sdk.preparation.{namespace}",
        kind="domain_preparation",
    ).scan(count, (1, 3))
    if shared_product_uses:
        selected = (
            template.record_product("raw", record_id="raw-first")
            .record_product("raw", record_id="raw-second")
            .build()
        )
    else:
        selected = template.record_product("raw").record_product("summary").build()
    resolved = resolve_experiment(
        selected.bind(),
        config_profile=load_config(),
    )
    linked = link_verified_program(resolved.verified_program, resolved.environment)
    linked_points = materialize_linked_points(linked)
    projection = project_domain_plan_internal(linked_points)
    call_view = projection.view(linked_points).require_one_call(
        dialect_id="test.preparation"
    )
    offer = DomainExecutionOffer.for_call(
        call_view,
        max_points_per_batch=2,
    )
    batch = MaterializedLinkedPointBatch(linked_points, (0, 1))
    return make_domain_batch_context_internal(
        projection,
        batch,
        offer,
        adapter_id=f"test.adapter.{namespace}",
        batch_ordinal=0,
    )


def _valid_mapping_inputs(
    context: DomainBatchContext,
) -> tuple[tuple[_Entry, ...], tuple[_EntryPoint, ...], tuple[_ResultUse, ...]]:
    entries = tuple(
        DomainTargetEntry(
            f"entry-{point.ordinal}",
            (f"result-{point.ordinal}",),
        )
        for point in context.points
    )
    entry_points = tuple(
        DomainEntryPointBinding(entry.entry_address, point)
        for entry, point in zip(entries, context.points, strict=True)
    )
    results = tuple(
        DomainResultUseBinding(
            entry.entry_address,
            entry.result_addresses[0],
            product_use,
        )
        for entry in entries
        for product_use in context.direct_product_uses
    )
    return entries, entry_points, results


def test_map_measurements_closes_exact_direct_product_cover(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="direct")
    preparation = context.new_preparation()
    entries, entry_points, results = _valid_mapping_inputs(context)

    mapping = preparation.map_measurements(
        entries=entries,
        entry_points=entry_points,
        results=results,
    )

    assert isinstance(mapping, DomainResultMapping)
    assert mapping.context is context
    assert mapping.product_uses == context.direct_product_uses
    assert len(context.product_uses) == 3
    assert len(context.direct_product_uses) == 2
    assert mapping.target_entries == entries
    assert tuple(entry.point for entry in mapping.entries) == context.points
    assert all(
        mapped.point is point
        for mapped, point in zip(mapping.entries, context.points, strict=True)
    )
    assert tuple(result.result_address for result in mapping.results) == tuple(
        entry.result_addresses[0] for entry in entries
    )
    for result, point in zip(mapping.results, context.points, strict=True):
        assert result.point is point
        assert result.product_uses == context.direct_product_uses
        assert all(
            actual is expected
            for actual, expected in zip(
                result.product_uses,
                context.direct_product_uses,
                strict=True,
            )
        )
        assert mapping.result_for_address(result.result_address) is result
        assert mapping.result_for(point, context.direct_product_uses[0]) is result

    non_direct_use = next(
        product_use
        for product_use in context.product_uses
        if all(product_use is not direct for direct in context.direct_product_uses)
    )
    invalid_results = (
        DomainResultUseBinding(
            results[0].entry_address,
            results[0].result_address,
            non_direct_use,
        ),
        *results[1:],
    )
    with pytest.raises(ValueError, match="non-direct or foreign product use"):
        preparation.map_measurements(
            entries=entries,
            entry_points=entry_points,
            results=invalid_results,
        )


def test_map_measurements_rejects_foreign_point_and_product_use(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="owned")
    foreign = _preparation_context(tmp_path, namespace="foreign")
    preparation = context.new_preparation()
    entries, entry_points, results = _valid_mapping_inputs(context)

    foreign_point_bindings = (
        DomainEntryPointBinding(entries[0].entry_address, foreign.points[0]),
        *entry_points[1:],
    )
    with pytest.raises(ValueError, match="point outside this batch context"):
        preparation.map_measurements(
            entries=entries,
            entry_points=foreign_point_bindings,
            results=results,
        )

    foreign_results = (
        DomainResultUseBinding(
            results[0].entry_address,
            results[0].result_address,
            foreign.direct_product_uses[0],
        ),
        *results[1:],
    )
    with pytest.raises(ValueError, match="non-direct or foreign product use"):
        preparation.map_measurements(
            entries=entries,
            entry_points=entry_points,
            results=foreign_results,
        )


def test_public_mapping_lookups_require_exact_context_refs(tmp_path: Path) -> None:
    context = _preparation_context(tmp_path, namespace="lookup")
    foreign = _preparation_context(tmp_path, namespace="lookup")
    entries, entry_points, results = _valid_mapping_inputs(context)
    mapping = context.new_preparation().map_measurements(
        entries=tuple(reversed(entries)),
        entry_points=entry_points,
        results=results,
    )

    assert tuple(entry.entry_address for entry in mapping.target_entries) == tuple(
        entry.entry_address for entry in reversed(entries)
    )
    assert all(
        actual is expected
        for actual, expected in zip(
            mapping.target_entries,
            reversed(entries),
            strict=True,
        )
    )
    assert tuple(entry.point for entry in mapping.entries) == context.points

    with pytest.raises(KeyError, match="result address"):
        mapping.result_for_address("unknown-result")
    with pytest.raises(KeyError, match="logical output is not in"):
        mapping.result_for(foreign.points[0], context.direct_product_uses[0])
    with pytest.raises(KeyError, match="logical output is not in"):
        mapping.result_for(context.points[0], foreign.direct_product_uses[0])


def test_map_measurements_rejects_missing_and_duplicate_entry_or_result(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="exact-cover")
    preparation = context.new_preparation()
    entries, entry_points, results = _valid_mapping_inputs(context)

    with pytest.raises(ValueError, match="exactly cover materialized logical points"):
        preparation.map_measurements(
            entries=entries[:-1],
            entry_points=entry_points[:-1],
            results=results[:-1],
        )

    with pytest.raises(ValueError, match="entry addresses must be unique"):
        preparation.map_measurements(
            entries=(*entries, entries[0]),
            entry_points=entry_points,
            results=results,
        )

    with pytest.raises(ValueError, match="exactly cover every logical"):
        preparation.map_measurements(
            entries=entries,
            entry_points=entry_points,
            results=results[:-1],
        )

    with pytest.raises(ValueError, match="unique result/product-use edges"):
        preparation.map_measurements(
            entries=entries,
            entry_points=entry_points,
            results=(*results, results[0]),
        )


def test_map_measurements_fans_one_physical_result_out_to_two_uses_of_product(
    tmp_path: Path,
) -> None:
    context = _preparation_context(
        tmp_path,
        namespace="fanout",
        shared_product_uses=True,
    )
    preparation = context.new_preparation()
    entries, entry_points, results = _valid_mapping_inputs(context)

    assert len(context.direct_product_uses) == 2
    assert context.direct_product_uses[0].id != context.direct_product_uses[1].id
    assert (
        context.direct_product_uses[0].product is context.direct_product_uses[1].product
    )
    assert len(entries) == len(context.points)
    assert len(results) == 2 * len(entries)
    for entry in entries:
        selected = tuple(
            binding
            for binding in results
            if binding.entry_address == entry.entry_address
        )
        assert len(selected) == 2
        assert selected[0].result_address == selected[1].result_address

    incomplete_results = tuple(
        binding
        for binding in results
        if binding.product_use is context.direct_product_uses[0]
    )
    with pytest.raises(ValueError, match="exactly cover every logical"):
        preparation.map_measurements(
            entries=entries,
            entry_points=entry_points,
            results=incomplete_results,
        )

    mapping = preparation.map_measurements(
        entries=entries,
        entry_points=entry_points,
        results=results,
    )
    assert mapping.context is context
    assert mapping.product_uses == context.direct_product_uses
    for point in context.points:
        first = mapping.result_for(point, context.direct_product_uses[0])
        second = mapping.result_for(point, context.direct_product_uses[1])
        assert first is second
        assert first.point is point
        assert all(
            actual is expected
            for actual, expected in zip(
                first.product_uses,
                context.direct_product_uses,
                strict=True,
            )
        )


def test_measurement_plan_and_build_close_the_complete_public_sdk_declaration(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="complete-sdk")
    preparation = context.new_preparation()
    entries, entry_points, results = _valid_mapping_inputs(context)
    mapping = preparation.map_measurements(
        entries=entries,
        entry_points=entry_points,
        results=results,
    )
    [transform] = context.measurement_transforms
    [summary] = transform.outputs[0].product_uses
    binding = DomainHostTransformBinding(
        transform,
        DomainHostTransformImplementation(
            id="test.summarize.python",
            semantic_id=transform.semantic.id,
            semantic_version=transform.semantic.version,
            implementation_fingerprint="test.summarize.python.v1",
            validate_transform=lambda _candidate: None,
            kernel=lambda call: {"summary": Quantity(call.point.ordinal, "count")},
        ),
    )

    measurements = preparation.measurement_plan(
        mapping,
        host_transforms=(binding,),
    )
    invocation = DomainInvocationSpec(
        invocation_id="test.complete-sdk.invocation",
        target=DomainTargetArtifactIdentity(
            target_id="test.target",
            compiler_id="test.compiler",
            capability_fingerprint="test.capabilities.v1",
            artifact_id="test.artifact",
            artifact_fingerprint="test.artifact.v1",
        ),
        adapter_intent={"mode": "test"},
        payload={"job": "test"},
    )

    def reject_realization(
        fetched: CorrelatedDomainFetch[dict[str, str]],
    ) -> tuple[DomainResultValue[str], ...]:
        del fetched
        raise AssertionError("preparation must not realize")

    prepared = preparation.build(
        measurements=measurements,
        invocation=invocation,
        runtime=_NoEffectsRuntime(),
        realize=reject_realization,
        resource_claims=(DomainResourceClaim("target", "test.target"),),
    )

    assert isinstance(measurements, DomainMeasurementPlan)
    assert measurements.context is context
    assert measurements.mapping is mapping
    assert measurements.source_product_uses == context.direct_product_uses
    assert measurements.derived_product_uses == (summary,)
    assert measurements.product_uses == context.product_uses
    assert measurements.host_transforms == (binding,)
    assert isinstance(prepared, PreparedDomainExecution)
    assert prepared.context is context
    assert prepared.direct_product_uses == context.direct_product_uses
    assert prepared.product_uses == context.product_uses
    for internal_name in (
        "invocation",
        "runtime",
        "realize",
        "source_fragment",
        "transforms",
        "resource_claims",
        "projection",
    ):
        assert not hasattr(prepared, internal_name)


def test_measurement_plan_requires_exact_derived_output_coverage(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="derived-cover")
    preparation = context.new_preparation()
    entries, entry_points, results = _valid_mapping_inputs(context)
    mapping = preparation.map_measurements(
        entries=entries,
        entry_points=entry_points,
        results=results,
    )

    with pytest.raises(ValueError, match="exactly cover authored transforms"):
        preparation.measurement_plan(mapping)


def test_public_mapping_builder_boundaries_do_not_expose_compiler_types() -> None:
    public_callables = (
        DomainPreparationBuilder.map_measurements,
        DomainPreparationBuilder.measurement_plan,
        DomainPreparationBuilder.build,
        DomainResultMapping.result_for_address,
        DomainResultMapping.result_for,
    )
    public_types = (
        DomainTargetEntry,
        DomainEntryPointBinding,
        DomainResultUseBinding,
        DomainMappedEntry,
        DomainMappedResult,
        DomainResultMapping,
        DomainMeasurementPlan,
        PreparedDomainExecution,
    )

    rendered: list[str] = []
    mapping_type_params = {
        type_param.__name__: type_param
        for type_param in DomainResultMapping.__type_params__
    }
    for callable_ in public_callables:
        rendered.append(str(inspect.signature(callable_)))
        module_globals = vars(import_module(callable_.__module__))
        rendered.extend(
            repr(annotation)
            for annotation in get_type_hints(
                callable_,
                globalns=module_globals,
                localns=mapping_type_params,
            ).values()
        )
    for public_type in public_types:
        rendered.append(str(inspect.signature(public_type)))
        public_hints = {
            name: annotation
            for name, annotation in get_type_hints(public_type).items()
            if not name.startswith("_")
        }
        rendered.extend(repr(annotation) for annotation in public_hints.values())
        assert public_type.__module__ in {
            "scopecat.sdk.domain.preparation",
            "scopecat.sdk.domain.execution",
        }

    public_contract = "\n".join(rendered)
    assert "scopecat.compiler" not in public_contract
    assert "ClosedDomain" not in public_contract
    assert "Bound" not in public_contract
    assert "ExecutionResourceClaim" not in public_contract
    assert "ProductUseId" not in public_contract
    assert not hasattr(DomainResultMapping, "native_internal")
