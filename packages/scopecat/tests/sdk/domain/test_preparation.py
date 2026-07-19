from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.compiler.linking.linked import (
    LinkedPointMaterializer,
    link_verified_program,
)
from scopecat.compiler.typed.domain_results import domain_result_closure
from scopecat.kernel.errors import ProviderContractError
from scopecat.planning.authoring import resolve_experiment
from scopecat.records.parameter import Quantity
from scopecat.sdk.domain import (
    DomainBatchContext,
    DomainResultBinding,
    DomainResultMapping,
)
from scopecat.sdk.domain._bridge import (
    make_domain_batch_context,
    make_domain_compile_request,
)
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.invocation import DomainOutputValue, seal_domain_output_values
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
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
    DomainSubmitReceipt,
    DomainSubmitRequest,
)
from tests.testkit.authoring import load_config

type _ResultBinding = DomainResultBinding[str]


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
        .measurement_transforms(transform)
        .build()
    )
    execution = sc.domain_execution(
        program,
        inputs={"count": count},
        results={"raw": module.products["raw"]},
    )
    template = (
        module.domain(execution)
        .template(
            f"test.sdk.preparation.{namespace}",
            kind="domain_preparation",
        )
        .scan(count, (1, 3))
    )
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
    materializer = LinkedPointMaterializer(linked)
    linked_points = materializer.materialize()
    closure = domain_result_closure(linked.program, execution.id)
    request = make_domain_compile_request(
        linked,
        execution.id,
        closure,
        ((0, 1),),
        lambda input_ids, ordinals, max_points: materializer.bind_domain_inputs(
            execution.id,
            input_ids,
            ordinals,
            max_points=max_points,
        ),
    )
    return make_domain_batch_context(
        request,
        linked_points,
        (0, 1),
        batch_ordinal=0,
    )


def _valid_mapping_inputs(
    context: DomainBatchContext,
) -> tuple[_ResultBinding, ...]:
    return tuple(
        DomainResultBinding(
            f"result-{point.ordinal}",
            point,
            product_use,
        )
        for point in context.points
        for product_use in context.direct_product_uses
    )


def test_map_measurements_closes_exact_direct_product_cover(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="direct")
    preparation = context.new_preparation()
    results = _valid_mapping_inputs(context)

    mapping = preparation.map_measurements(results=results)

    assert isinstance(mapping, DomainResultMapping)
    assert mapping.context is context
    assert mapping.product_uses == context.direct_product_uses
    assert len(context.product_uses) == 3
    assert len(context.direct_product_uses) == 2
    assert tuple(result.point for result in mapping.results) == context.points
    assert tuple(result.result_address for result in mapping.results) == (
        "result-0",
        "result-1",
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
        DomainResultBinding(
            results[0].result_address,
            results[0].point,
            non_direct_use,
        ),
        *results[1:],
    )
    with pytest.raises(ValueError, match="non-direct or foreign product use"):
        preparation.map_measurements(results=invalid_results)


def test_result_values_project_directly_to_canonical_candidates(tmp_path: Path) -> None:
    context = _preparation_context(tmp_path, namespace="values")
    results = _valid_mapping_inputs(context)
    mapping = context.new_preparation().map_measurements(results=results)
    values = tuple(
        DomainOutputValue(
            result.result_address,
            Quantity(value=index, unit="count"),
        )
        for index, result in enumerate(mapping.results)
    )

    candidates = seal_domain_output_values(mapping, tuple(reversed(values)))

    assert tuple(
        (candidate.logical_point_id, candidate.product_use_id)
        for candidate in candidates
    ) == tuple(
        (result.logical_point_id, use_id)
        for result in mapping.results
        for use_id in result.product_use_ids
    )
    with pytest.raises(ProviderContractError) as caught:
        seal_domain_output_values(mapping, values[:-1])
    assert {problem.code for problem in caught.value.problems} == {
        "domain_output_missing_result"
    }


def test_map_measurements_rejects_foreign_point_and_product_use(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="owned")
    foreign = _preparation_context(tmp_path, namespace="foreign")
    preparation = context.new_preparation()
    results = _valid_mapping_inputs(context)

    foreign_point_bindings = (
        DomainResultBinding(
            results[0].result_address,
            foreign.points[0],
            results[0].product_use,
        ),
        *results[1:],
    )
    with pytest.raises(ValueError, match="point outside this batch context"):
        preparation.map_measurements(results=foreign_point_bindings)

    foreign_results = (
        DomainResultBinding(
            results[0].result_address,
            results[0].point,
            foreign.direct_product_uses[0],
        ),
        *results[1:],
    )
    with pytest.raises(ValueError, match="non-direct or foreign product use"):
        preparation.map_measurements(results=foreign_results)


def test_public_mapping_lookups_require_exact_context_refs(tmp_path: Path) -> None:
    context = _preparation_context(tmp_path, namespace="lookup")
    foreign = _preparation_context(tmp_path, namespace="lookup")
    results = _valid_mapping_inputs(context)
    mapping = context.new_preparation().map_measurements(
        results=tuple(reversed(results)),
    )

    assert tuple(result.point for result in mapping.results) == context.points

    with pytest.raises(KeyError, match="result address"):
        mapping.result_for_address("unknown-result")
    with pytest.raises(KeyError, match="logical output is not in"):
        mapping.result_for(foreign.points[0], context.direct_product_uses[0])
    with pytest.raises(KeyError, match="logical output is not in"):
        mapping.result_for(context.points[0], foreign.direct_product_uses[0])


def test_map_measurements_rejects_missing_and_duplicate_logical_output(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="exact-cover")
    preparation = context.new_preparation()
    results = _valid_mapping_inputs(context)

    with pytest.raises(ValueError, match="exactly cover every logical"):
        preparation.map_measurements(results=results[:-1])

    with pytest.raises(ValueError, match="unique point/product-use outputs"):
        preparation.map_measurements(results=(*results, results[0]))


def test_map_measurements_fans_one_physical_result_out_to_two_uses_of_product(
    tmp_path: Path,
) -> None:
    context = _preparation_context(
        tmp_path,
        namespace="fanout",
        shared_product_uses=True,
    )
    preparation = context.new_preparation()
    results = _valid_mapping_inputs(context)

    assert len(context.direct_product_uses) == 2
    assert context.direct_product_uses[0].id != context.direct_product_uses[1].id
    assert (
        context.direct_product_uses[0].product is context.direct_product_uses[1].product
    )
    assert len(results) == 2 * len(context.points)
    for point in context.points:
        selected = tuple(binding for binding in results if binding.point is point)
        assert len(selected) == 2
        assert selected[0].result_address == selected[1].result_address

    split_results = tuple(
        DomainResultBinding(
            f"result-{binding.point.ordinal}-{index}",
            binding.point,
            binding.product_use,
        )
        for index, binding in enumerate(results)
    )
    with pytest.raises(ValueError, match="cannot be split across locations"):
        preparation.map_measurements(results=split_results)

    incomplete_results = tuple(
        binding
        for binding in results
        if binding.product_use is context.direct_product_uses[0]
    )
    with pytest.raises(ValueError, match="exactly cover every logical"):
        preparation.map_measurements(results=incomplete_results)

    mapping = preparation.map_measurements(results=results)
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
    results = _valid_mapping_inputs(context)
    mapping = preparation.map_measurements(results=results)
    [transform] = context.measurement_transforms
    binding = DomainHostTransformBinding(
        transform,
        DomainHostTransformImplementation(
            id="test.summarize.python",
            semantic_id=transform.semantic.id,
            semantic_version=transform.semantic.version,
            implementation_fingerprint="test.summarize.python.v1",
            validate_transform=lambda _candidate: None,
            kernel=lambda call: {
                "summary": tuple(
                    Quantity(point.ordinal, "count") for point in call.points
                )
            },
        ),
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
        target_intent={"mode": "test"},
        payload={"job": "test"},
    )

    def reject_realization(
        fetched: CorrelatedDomainFetch[dict[str, str]],
    ) -> tuple[DomainResultValue[str], ...]:
        del fetched
        raise AssertionError("preparation must not realize")

    prepared = preparation.build(
        mapping=mapping,
        host_transforms=(binding,),
        invocation=invocation,
        runtime=_NoEffectsRuntime(),
        realize=reject_realization,
    )

    assert isinstance(prepared, PreparedDomainExecution)


def test_measurement_plan_requires_exact_derived_output_coverage(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="derived-cover")
    preparation = context.new_preparation()
    results = _valid_mapping_inputs(context)
    mapping = preparation.map_measurements(results=results)

    with pytest.raises(ValueError, match="exactly cover residual transforms"):
        preparation.build(
            mapping=mapping,
            invocation=DomainInvocationSpec(
                invocation_id="test.missing-transform.invocation",
                target=DomainTargetArtifactIdentity(
                    target_id="test.target",
                    compiler_id="test.compiler",
                    capability_fingerprint="test.capabilities.v1",
                    artifact_id="test.artifact",
                    artifact_fingerprint="test.artifact.v1",
                ),
                target_intent={"mode": "test"},
                payload={"job": "test"},
            ),
            runtime=_NoEffectsRuntime(),
            realize=lambda _fetched: (),
        )
