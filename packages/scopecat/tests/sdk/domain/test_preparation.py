from __future__ import annotations

from pathlib import Path

import pytest

import scopecat as sc
from scopecat.kernel.errors import ProviderContractError
from scopecat.kernel.measurement_values import MeasurementDType
from scopecat.measurements.results import MeasurementScalar
from scopecat.planning.domain_bridge import (
    make_domain_batch_request,
    make_domain_call_view,
)
from scopecat.planning.domain_results import domain_result_product_use_ids
from scopecat.planning.point_materialization import (
    materialize_bound_points,
)
from scopecat.program.domain import domain_program
from scopecat.program.products import ModuleProductDecl, ProductValueSpec
from scopecat.sdk.domain import (
    DomainBatchRequest,
    DomainPreparationBuilder,
    DomainResultBinding,
    DomainResultMapping,
)
from scopecat.sdk.domain.execution import PreparedDomainExecution
from scopecat.sdk.domain.invocation import DomainOutputValue, seal_domain_output_values
from scopecat.sdk.domain.job import (
    DomainInvocationSpec,
    DomainResultValue,
)
from scopecat.sdk.domain.runtime import (
    DomainFetchReceipt,
    DomainFetchResult,
    DomainSubmitReceipt,
)
from tests.testkit.authoring import bind_invocation, load_config
from tests.testkit.domain import domain_call

type _ResultBinding = DomainResultBinding[str]


class _NoEffectsRuntime:
    def submit(
        self,
        submission_key: str,
        payload: dict[str, str],
    ) -> DomainSubmitReceipt:
        del submission_key, payload
        raise AssertionError("preparation must not submit")

    def fetch(
        self,
        submission_key: str,
        job_id: str,
    ) -> DomainFetchReceipt | DomainFetchResult[dict[str, str]]:
        del submission_key, job_id
        raise AssertionError("preparation must not fetch")


def _preparation_context(
    tmp_path: Path,
    *,
    namespace: str,
    shared_product_uses: bool = False,
    dtype: MeasurementDType = "int64",
    unit: str | None = "count",
) -> DomainBatchRequest:
    count_type = sc.ScalarType(sc.IntType(minimum=0))
    count = sc.coordinate(f"{namespace}_count", count_type)
    program = domain_program(
        "program",
        dialect_id="test.preparation",
        dialect_version="1",
        body=object(),
        inputs={"count": count_type},
        results={
            "raw": ("raw", "v1"),
        },
    )

    authored_call = domain_call(
        program,
        inputs={"count": count},
        products={
            "raw": ModuleProductDecl(
                "raw",
                value_spec=ProductValueSpec(unit=unit, dtype=dtype),
            )
        },
    )

    @sc.experiment(
        id=f"test.sdk.preparation.{namespace}",
        kind="domain_preparation",
    )
    def selected(experiment: sc.ExperimentContext) -> None:
        results = experiment.use(authored_call)
        experiment.grid(sc.axis(count, (1, 3)))
        experiment.record(
            results.raw,
            record_id="raw-first" if shared_product_uses else "raw",
        )
        if shared_product_uses:
            experiment.record(
                results.raw,
                record_id="raw-second",
            )

    resolved = bind_invocation(
        selected.bind(),
        config_profile=load_config(),
    )
    bound = resolved
    bound_points = materialize_bound_points(bound)
    execution = bound.program.program.domain_executions[0]
    execution_id = execution.id
    product_use_ids = domain_result_product_use_ids(bound.bindings, execution)
    call_view = make_domain_call_view(
        bound,
        execution_id,
        product_use_ids,
    )
    return make_domain_batch_request(
        call_view,
        bound_points,
        (0, 1),
        batch_ordinal=0,
    )


def _valid_mapping_inputs(
    context: DomainBatchRequest,
) -> tuple[_ResultBinding, ...]:
    return tuple(
        DomainResultBinding(
            f"result-{point.ordinal}",
            point,
            product_use,
        )
        for point in context.points
        for product_use in context.product_uses
    )


def test_map_measurements_closes_exact_product_cover(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="direct")
    preparation = DomainPreparationBuilder(context)
    results = _valid_mapping_inputs(context)

    mapping = preparation.map_measurements(results=results)

    assert isinstance(mapping, DomainResultMapping)
    assert mapping.context is context
    assert len(context.product_uses) == 1
    assert tuple(result.point for result in mapping.results) == context.points
    assert tuple(result.result_address for result in mapping.results) == (
        "result-0",
        "result-1",
    )
    for result, point in zip(mapping.results, context.points, strict=True):
        assert result.point is point
        assert result.product_uses == context.product_uses
        assert all(
            actual is expected
            for actual, expected in zip(
                result.product_uses,
                context.product_uses,
                strict=True,
            )
        )


def test_result_values_project_directly_to_canonical_candidates(tmp_path: Path) -> None:
    context = _preparation_context(tmp_path, namespace="values")
    results = _valid_mapping_inputs(context)
    mapping = DomainPreparationBuilder(context).map_measurements(results=results)
    values = tuple(
        DomainOutputValue(
            result.result_address,
            MeasurementScalar.create(dtype="int64", value=index, unit="count"),
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


@pytest.mark.parametrize(
    ("dtype", "value"),
    (("bool", True), ("string", "ready")),
)
def test_result_values_accept_every_scalar_dtype(
    tmp_path: Path,
    dtype: MeasurementDType,
    value: bool | str,
) -> None:
    context = _preparation_context(
        tmp_path,
        namespace=f"scalar-{dtype}",
        dtype=dtype,
        unit=None,
    )
    mapping = DomainPreparationBuilder(context).map_measurements(
        results=_valid_mapping_inputs(context)
    )
    values = tuple(
        DomainOutputValue(
            result.result_address,
            MeasurementScalar.create(dtype=dtype, value=value),
        )
        for result in mapping.results
    )

    candidates = seal_domain_output_values(mapping, values)

    assert [candidate.value for candidate in candidates] == [
        MeasurementScalar.create(dtype=dtype, value=value),
        MeasurementScalar.create(dtype=dtype, value=value),
    ]


def test_map_measurements_rejects_foreign_point_and_product_use(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="owned")
    foreign = _preparation_context(tmp_path, namespace="foreign")
    preparation = DomainPreparationBuilder(context)
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
            foreign.product_uses[0],
        ),
        *results[1:],
    )
    with pytest.raises(ValueError, match="foreign product use"):
        preparation.map_measurements(results=foreign_results)


def test_map_measurements_rejects_missing_and_duplicate_logical_output(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="exact-cover")
    preparation = DomainPreparationBuilder(context)
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
    preparation = DomainPreparationBuilder(context)
    results = _valid_mapping_inputs(context)

    assert len(context.product_uses) == 2
    assert context.product_uses[0].id != context.product_uses[1].id
    assert context.product_uses[0].product is context.product_uses[1].product
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
        binding for binding in results if binding.product_use is context.product_uses[0]
    )
    with pytest.raises(ValueError, match="exactly cover every logical"):
        preparation.map_measurements(results=incomplete_results)

    mapping = preparation.map_measurements(results=results)
    assert mapping.context is context
    for result, point in zip(mapping.results, context.points, strict=True):
        assert result.point is point
        assert all(
            actual is expected
            for actual, expected in zip(
                result.product_uses,
                context.product_uses,
                strict=True,
            )
        )


def test_measurement_plan_and_build_close_the_complete_public_sdk_declaration(
    tmp_path: Path,
) -> None:
    context = _preparation_context(tmp_path, namespace="complete-sdk")
    preparation = DomainPreparationBuilder(context)
    results = _valid_mapping_inputs(context)
    mapping = preparation.map_measurements(results=results)

    invocation = DomainInvocationSpec(
        invocation_id="test.complete-sdk.invocation",
        target_id="test.target",
        compiler_id="test.compiler",
        capability_fingerprint="test.interfaces.v1",
        artifact_id="test.artifact",
        artifact_fingerprint="test.artifact.v1",
        target_intent={"mode": "test"},
        payload={"job": "test"},
    )

    def reject_realization(
        fetched: DomainFetchResult[dict[str, str]],
    ) -> tuple[DomainResultValue[str], ...]:
        del fetched
        raise AssertionError("preparation must not realize")

    prepared = preparation.build(
        mapping=mapping,
        invocation=invocation,
        runtime=_NoEffectsRuntime(),
        realize=reject_realization,
    )

    assert isinstance(prepared, PreparedDomainExecution)
