"""Pure adapter proofs for one closed domain-program invocation.

This public module is the narrow target-integration seam between Scopecat's
transient compiler and a domain package. It closes logical identity mappings
and target-owned realization policy before effects, then accepts exact
correlated measurement values afterward. Runtime submission and fetch are
defined separately in :mod:`scopecat.sdk.domain.runtime`.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal, Protocol, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from scopecat.compiler.typed.products import ProductDef
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import CheckFailed, ProviderContractError
from scopecat.kernel.point_identity import LogicalPointId
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)
from scopecat.kernel.product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
)
from scopecat.measurements.contracts import (
    measurement_value_contract_issues,
    validated_measurement_value_copy,
)
from scopecat.measurements.values import (
    MeasurementValueCandidate,
    MeasurementValueCatalog,
)
from scopecat.records.measurement import MeasurementValue


class DomainResultContract[ResultAddressT: Hashable](Protocol):
    @property
    def result_address(self) -> ResultAddressT: ...

    @property
    def logical_point_id(self) -> LogicalPointId: ...

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]: ...

    @property
    def product_id(self) -> ProductId: ...

    @property
    def product(self) -> ProductDef: ...


class DomainResultMappingContract[ResultAddressT: Hashable](Protocol):
    @property
    def catalog(self) -> MeasurementValueCatalog: ...

    @property
    def selected_product_use_ids(self) -> tuple[ProductUseId, ...]: ...

    @property
    def selected_product_uses(self) -> tuple[ProductUse, ...]: ...

    @property
    def results(
        self,
    ) -> tuple[DomainResultContract[ResultAddressT], ...]: ...

    @property
    def contract_fingerprint(self) -> str: ...

    def product_for_use(self, product_use_id: ProductUseId) -> ProductDef: ...

    def result_for_address(
        self, result_address: ResultAddressT
    ) -> DomainResultContract[ResultAddressT]: ...


@dataclass(frozen=True, slots=True)
class DomainOutputValue[ResultAddressT: Hashable]:
    """Adapter candidate relating one opaque result address to one value.

    Logical point, product-use, and product identity are deliberately absent.
    They are recovered from a closed result mapping when the complete output
    inventory is accepted.
    """

    result_address: ResultAddressT
    value: MeasurementValue


class DomainInvocationIntent(BaseModel):
    """Durable, payload-free identity of one executable domain invocation."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        revalidate_instances="always",
    )

    schema_version: Literal["scopecat.sdk.domain.invocation_intent.v1"] = (
        "scopecat.sdk.domain.invocation_intent.v1"
    )
    invocation_id: str
    target_id: str
    compiler_id: str
    capability_fingerprint: str
    artifact_id: str
    artifact_fingerprint: str
    result_contract_fingerprint: str
    target_intent_fingerprint: str
    intent_fingerprint: str

    @field_validator(
        "invocation_id",
        "target_id",
        "compiler_id",
        "capability_fingerprint",
        "artifact_id",
        "artifact_fingerprint",
        "result_contract_fingerprint",
        "target_intent_fingerprint",
        "intent_fingerprint",
    )
    @classmethod
    def validate_required_text(cls, value: str) -> str:
        if not value:
            msg = "domain invocation identity fields must be non-empty"
            raise ValueError(msg)
        return value

    @model_validator(mode="after")
    def validate_intent_fingerprint(self) -> DomainInvocationIntent:
        expected = _domain_invocation_intent_fingerprint(
            invocation_id=self.invocation_id,
            target_id=self.target_id,
            compiler_id=self.compiler_id,
            capability_fingerprint=self.capability_fingerprint,
            artifact_id=self.artifact_id,
            artifact_fingerprint=self.artifact_fingerprint,
            result_contract_fingerprint=self.result_contract_fingerprint,
            target_intent_fingerprint=self.target_intent_fingerprint,
        )
        if self.intent_fingerprint != expected:
            msg = "domain invocation fingerprint does not cover its complete intent"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True)
class ClosedDomainInvocation[
    ResultAddressT: Hashable,
    PayloadT,
]:
    """One target-selected invocation ready for effects.

    ``payload`` is deliberately transient and adapter-owned.  Durable host
    evidence uses only :attr:`intent`; the adapter payload owns any selected
    carrier or value policy independently of the exact retained result mapping.
    """

    intent: DomainInvocationIntent
    result_mapping: DomainResultMappingContract[ResultAddressT] = field(repr=False)
    payload: PayloadT = field(repr=False)

    def __post_init__(self) -> None:
        if (
            self.intent.result_contract_fingerprint
            != self.result_mapping.contract_fingerprint
        ):
            msg = "domain invocation intent does not cover its output contract"
            raise ValueError(msg)


def close_domain_invocation[
    ResultAddressT: Hashable,
    PayloadT,
](
    result_mapping: DomainResultMappingContract[ResultAddressT],
    *,
    invocation_id: str,
    target_id: str,
    compiler_id: str,
    capability_fingerprint: str,
    artifact_id: str,
    artifact_fingerprint: str,
    target_intent: object,
    payload: PayloadT,
) -> ClosedDomainInvocation[ResultAddressT, PayloadT]:
    """Close stable target and output facts around an opaque target payload."""

    result_contract_fingerprint = result_mapping.contract_fingerprint
    target_intent_fingerprint = stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.domain_target_intent.v1",
                "value": target_intent,
            }
        )
    )
    intent_fingerprint = _domain_invocation_intent_fingerprint(
        invocation_id=invocation_id,
        target_id=target_id,
        compiler_id=compiler_id,
        capability_fingerprint=capability_fingerprint,
        artifact_id=artifact_id,
        artifact_fingerprint=artifact_fingerprint,
        result_contract_fingerprint=result_contract_fingerprint,
        target_intent_fingerprint=target_intent_fingerprint,
    )
    intent = DomainInvocationIntent(
        invocation_id=invocation_id,
        target_id=target_id,
        compiler_id=compiler_id,
        capability_fingerprint=capability_fingerprint,
        artifact_id=artifact_id,
        artifact_fingerprint=artifact_fingerprint,
        result_contract_fingerprint=result_contract_fingerprint,
        target_intent_fingerprint=target_intent_fingerprint,
        intent_fingerprint=intent_fingerprint,
    )
    return ClosedDomainInvocation(
        intent,
        result_mapping,
        payload,
    )


def _domain_measurement_output_selection_problems[
    ResultAddressT: Hashable,
](
    mapping: DomainResultMappingContract[ResultAddressT],
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    for use_index, product_use in enumerate(mapping.selected_product_uses):
        product = mapping.product_for_use(product_use.id)
        identity_details = {
            "product_use_id": product_use.id.value,
            "product_id": product.id.qualified_name,
        }
        if product.kind != "observable":
            problems.append(
                _domain_output_selection_problem(
                    "domain_output_product_kind_unsupported",
                    "domain measurement output closure supports observable "
                    f"products only, got {product.kind!r}",
                    path=("product_uses", use_index, "product", "kind"),
                    details={
                        **identity_details,
                        "expected": "observable",
                        "actual": product.kind,
                    },
                )
            )
        if not product.axes and product.dtype in {"bool", "string"}:
            problems.append(
                _domain_output_selection_problem(
                    "domain_output_scalar_dtype_unsupported",
                    "domain measurement output closure has no scalar carrier for "
                    f"dtype {product.dtype!r}",
                    path=("product_uses", use_index, "product", "dtype"),
                    details={
                        **identity_details,
                        "actual": product.dtype,
                        "supported_scalar_dtypes": [
                            "float64",
                            "int64",
                            "complex128",
                        ],
                    },
                )
            )
    return tuple(problems)


def seal_domain_output_values[
    ResultAddressT: Hashable,
](
    mapping: DomainResultMappingContract[ResultAddressT],
    values: Sequence[DomainOutputValue[ResultAddressT]],
) -> tuple[MeasurementValueCandidate, ...]:
    """Accept exact observable-value coverage against retained contracts.

    The adapter supplies only opaque result addresses and measurement values.
    Point, product-use, and product identity are derived from ``mapping``.  Any
    coverage or value-contract problem rejects the complete candidate set; no
    partial accepted proof is returned. This first carrier supports observable
    products only; artifact and other product kinds require distinct payload
    closures rather than overloading ``MeasurementValue``.
    """

    selection_problems = _domain_measurement_output_selection_problems(mapping)
    if selection_problems:
        raise CheckFailed(selection_problems)
    selected = tuple(values)

    expected_addresses = {result.result_address for result in mapping.results}
    by_address: dict[ResultAddressT, DomainOutputValue[ResultAddressT]] = {}
    first_index_by_address: dict[ResultAddressT, int] = {}
    problems: list[Problem] = []
    for candidate_index, candidate in enumerate(selected):
        if candidate.result_address in by_address:
            problems.append(
                _domain_output_problem(
                    "domain_output_duplicate_result",
                    "domain output candidates repeat result address "
                    f"{candidate.result_address!r}",
                    path=("candidates", candidate_index, "result_address"),
                    details={
                        "candidate_index": candidate_index,
                        "first_candidate_index": first_index_by_address[
                            candidate.result_address
                        ],
                    },
                )
            )
            continue
        by_address[candidate.result_address] = candidate
        first_index_by_address[candidate.result_address] = candidate_index
        if candidate.result_address not in expected_addresses:
            problems.append(
                _domain_output_problem(
                    "domain_output_unexpected_result",
                    "domain output candidate references an unmapped result address "
                    f"{candidate.result_address!r}",
                    path=("candidates", candidate_index, "result_address"),
                    details={"candidate_index": candidate_index},
                )
            )

    for result_index, result in enumerate(mapping.results):
        candidate = by_address.get(result.result_address)
        identity_details = _domain_output_identity_details(result)
        if candidate is None:
            problems.append(
                _domain_output_problem(
                    "domain_output_missing_result",
                    "domain output candidates are missing the value for "
                    f"point {result.logical_point_id.value!r}, product uses "
                    f"{tuple(use_id.value for use_id in result.product_use_ids)!r}",
                    path=("results", result_index, "value"),
                    details=identity_details,
                )
            )
            continue
        product = result.product
        for issue in measurement_value_contract_issues(
            candidate.value,
            expected_dtype=product.dtype,
            expected_unit=product.unit,
            expected_shape=tuple(axis.size for axis in product.axes),
        ):
            issue_code = issue.code.value
            field_path: tuple[str | int, ...]
            if issue_code == "dtype_mismatch":
                problem_code = "domain_output_dtype_mismatch"
                field_path = ("dtype",)
            elif issue_code == "unit_mismatch":
                problem_code = "domain_output_unit_mismatch"
                field_path = ("unit",)
            elif issue_code == "shape_mismatch":
                problem_code = "domain_output_shape_mismatch"
                field_path = ("shape",)
            elif issue_code == "array_structure_mismatch":
                problem_code = "domain_output_shape_mismatch"
                field_path = issue.path
            else:
                problem_code = "domain_output_value_mismatch"
                field_path = issue.path
            problems.append(
                _domain_output_problem(
                    problem_code,
                    "domain output value does not satisfy product "
                    f"{result.product_id.qualified_name!r}: "
                    f"{issue_code.replace('_', ' ')}; expected "
                    f"{issue.expected!r}, actual {issue.actual!r}",
                    path=("results", result_index, *field_path),
                    details={
                        **identity_details,
                        "contract_issue": issue_code,
                        "expected": _problem_detail(issue.expected),
                        "actual": _problem_detail(issue.actual),
                        "value_path": list(issue.path),
                    },
                )
            )
    if problems:
        raise ProviderContractError(problems)

    return tuple(
        MeasurementValueCandidate(
            result.logical_point_id,
            product_use_id,
            validated_measurement_value_copy(by_address[result.result_address].value),
        )
        for result in mapping.results
        for product_use_id in result.product_use_ids
    )


def _domain_invocation_intent_fingerprint(
    *,
    invocation_id: str,
    target_id: str,
    compiler_id: str,
    capability_fingerprint: str,
    artifact_id: str,
    artifact_fingerprint: str,
    result_contract_fingerprint: str,
    target_intent_fingerprint: str,
) -> str:
    return stable_content_hash(
        {
            "schema": "scopecat.sdk.domain.invocation_intent_identity.v1",
            "invocation_id": invocation_id,
            "target_id": target_id,
            "compiler_id": compiler_id,
            "capability_fingerprint": capability_fingerprint,
            "artifact_id": artifact_id,
            "artifact_fingerprint": artifact_fingerprint,
            "result_contract_fingerprint": result_contract_fingerprint,
            "target_intent_fingerprint": target_intent_fingerprint,
        }
    )


def _domain_output_identity_details[
    ResultAddressT: Hashable,
](
    result: DomainResultContract[ResultAddressT],
) -> dict[str, object]:
    return {
        "logical_point_id": result.logical_point_id.value,
        "product_use_ids": [use_id.value for use_id in result.product_use_ids],
        "product_id": result.product_id.qualified_name,
    }


def _domain_output_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object] | None = None,
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.PROVIDER_CONTRACT,
        phase=ProblemPhase.EXECUTION,
        location=model_location("domain_output_values", *path),
        details=details,
    )


def _domain_output_selection_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    details: Mapping[str, object],
) -> Problem:
    return blocking_problem(
        code,
        message,
        category=ProblemCategory.UNAVAILABLE,
        phase=ProblemPhase.PLANNING,
        location=model_location("domain_output_values", *path),
        details=details,
    )


def _problem_detail(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, tuple | list):
        selected = cast("tuple[object, ...] | list[object]", value)
        return [_problem_detail(item) for item in selected]
    if isinstance(value, Mapping):
        selected_mapping = cast("Mapping[object, object]", value)
        return {
            str(key): _problem_detail(item) for key, item in selected_mapping.items()
        }
    return repr(value)


__all__ = [
    "ClosedDomainInvocation",
    "DomainInvocationIntent",
    "DomainOutputValue",
    "ProductDef",
    "ProductId",
    "ProductUse",
    "ProductUseId",
    "close_domain_invocation",
    "seal_domain_output_values",
]
