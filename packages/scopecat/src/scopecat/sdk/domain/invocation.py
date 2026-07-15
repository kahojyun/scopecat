"""Pure adapter proofs for one closed domain-program invocation.

This public module is the narrow target-integration seam between Scopecat's
transient compiler and a domain package. It closes logical identity mappings
and target-owned realization policy before effects, then accepts exact
correlated measurement values afterward.  Runtime submission, fetch, and
reconciliation are defined separately in :mod:`scopecat.sdk.domain.runtime`.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from scopecat.compiler.linking.linked import (
    LinkedPlan,
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    MaterializedLinkedPointSet,
    materialize_linked_points,
)
from scopecat.compiler.typed.point_domain import (
    LogicalPointId,
    MaterializedPoint,
    MaterializedPointDomain,
)
from scopecat.compiler.typed.products import ProductDef
from scopecat.kernel.content_identity import content_fingerprint, stable_content_hash
from scopecat.kernel.errors import CheckFailed, ProviderContractError
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
from scopecat.records.measurement import MeasurementValue


@dataclass(frozen=True, slots=True)
class AdapterEntryResults[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """One adapter entry and its complete ordered result-address inventory."""

    entry_address: EntryAddressT
    result_addresses: tuple[ResultAddressT, ...] = ()

    def __post_init__(self) -> None:
        if len(set(self.result_addresses)) != len(self.result_addresses):
            msg = "adapter result addresses must be unique"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class EntryPointBinding[EntryAddressT: Hashable]:
    """Adapter-declared edge from one entry to an existing logical point."""

    entry_address: EntryAddressT
    logical_point_id: LogicalPointId


@dataclass(frozen=True, slots=True)
class ResultUseBinding[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """Adapter-declared edge from one entry result to a logical product use."""

    entry_address: EntryAddressT
    result_address: ResultAddressT
    product_use_id: ProductUseId


@dataclass(frozen=True, slots=True)
class DomainOutputValue[ResultAddressT: Hashable]:
    """Adapter candidate relating one opaque result address to one value.

    Logical point, product-use, and product identity are deliberately absent.
    They are recovered from a closed result mapping when the complete output
    inventory is accepted.
    """

    result_address: ResultAddressT
    value: MeasurementValue


@dataclass(frozen=True, slots=True, init=False)
class ClosedDomainResult[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """One checked physical result and all of its logical output occurrences."""

    entry_address: EntryAddressT
    result_address: ResultAddressT
    point: MaterializedPoint = field(repr=False)
    product_uses: tuple[ProductUse, ...] = field(repr=False)
    _product: ProductDef = field(repr=False)

    def __init__(
        self,
        entry_address: EntryAddressT,
        result_address: ResultAddressT,
        point: MaterializedPoint,
        product_uses: tuple[ProductUse, ...],
        product: ProductDef,
    ) -> None:
        selected_uses = tuple(product_uses)
        if not selected_uses:
            msg = "closed domain results require at least one logical product use"
            raise ValueError(msg)
        if len({use.id for use in selected_uses}) != len(selected_uses):
            msg = "closed domain results require unique logical product uses"
            raise ValueError(msg)
        if any(use.product_id != product.id for use in selected_uses):
            msg = "closed domain results must retain their exact product contract"
            raise ValueError(msg)
        object.__setattr__(self, "entry_address", entry_address)
        object.__setattr__(self, "result_address", result_address)
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "product_uses", selected_uses)
        object.__setattr__(self, "_product", deepcopy(product))

    @property
    def logical_point_id(self) -> LogicalPointId:
        return self.point.logical_id

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]:
        """Return every logical occurrence discharged by this physical result."""

        return tuple(use.id for use in self.product_uses)

    @property
    def product_id(self) -> ProductId:
        return self._product.id

    @property
    def product(self) -> ProductDef:
        """Return a defensive copy of the retained logical product contract."""

        return deepcopy(self._product)


@dataclass(frozen=True, slots=True, init=False)
class ClosedDomainOutputValue[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """One accepted measurement value retaining its exact mapped result."""

    result: ClosedDomainResult[EntryAddressT, ResultAddressT] = field(repr=False)
    _value: MeasurementValue = field(repr=False)

    def __init__(
        self,
        result: ClosedDomainResult[EntryAddressT, ResultAddressT],
        value: MeasurementValue,
    ) -> None:
        object.__setattr__(self, "result", result)
        object.__setattr__(self, "_value", _copy_measurement_value(value))

    @property
    def entry_address(self) -> EntryAddressT:
        return self.result.entry_address

    @property
    def result_address(self) -> ResultAddressT:
        return self.result.result_address

    @property
    def logical_point_id(self) -> LogicalPointId:
        return self.result.logical_point_id

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]:
        return self.result.product_use_ids

    @property
    def product_id(self) -> ProductId:
        return self.result.product_id

    @property
    def product(self) -> ProductDef:
        return self.result.product

    @property
    def value(self) -> MeasurementValue:
        """Return a defensive copy of the accepted measurement value."""

        return _copy_measurement_value(self._value)


@dataclass(frozen=True, slots=True, init=False)
class ClosedDomainEntry[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """One checked adapter entry in canonical logical-point order."""

    entry_address: EntryAddressT
    point: MaterializedPoint = field(repr=False)
    results: tuple[ClosedDomainResult[EntryAddressT, ResultAddressT], ...]

    def __init__(
        self,
        entry_address: EntryAddressT,
        point: MaterializedPoint,
        results: tuple[ClosedDomainResult[EntryAddressT, ResultAddressT], ...],
    ) -> None:
        if any(
            result.entry_address != entry_address
            or result.logical_point_id != point.logical_id
            for result in results
        ):
            msg = "closed domain entry results must belong to their entry and point"
            raise ValueError(msg)
        object.__setattr__(self, "entry_address", entry_address)
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "results", results)

    @property
    def logical_point_id(self) -> LogicalPointId:
        return self.point.logical_id


@dataclass(frozen=True, slots=True, init=False)
class ClosedDomainResultMapping[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """Exact canonical mapping of adapter work to core outputs.

    Entries are exposed in canonical point order and physical results are
    ordered by the first linked product use they discharge. ``adapter_entries``
    separately preserves the adapter's own ordering. One physical result may
    discharge several uses of the same logical product, but every selected
    point/use pair still has exactly one owner.
    """

    linked_points: MaterializedLinkedPointSet
    selected_product_use_ids: tuple[ProductUseId, ...]
    selected_product_uses: tuple[ProductUse, ...] = field(repr=False)
    adapter_entries: tuple[AdapterEntryResults[EntryAddressT, ResultAddressT], ...]
    entries: tuple[ClosedDomainEntry[EntryAddressT, ResultAddressT], ...]
    results: tuple[ClosedDomainResult[EntryAddressT, ResultAddressT], ...]
    _entry_by_address: Mapping[
        EntryAddressT, ClosedDomainEntry[EntryAddressT, ResultAddressT]
    ] = field(repr=False, compare=False, hash=False)
    _entry_by_point: Mapping[
        LogicalPointId, ClosedDomainEntry[EntryAddressT, ResultAddressT]
    ] = field(repr=False, compare=False, hash=False)
    _result_by_address: Mapping[
        ResultAddressT, ClosedDomainResult[EntryAddressT, ResultAddressT]
    ] = field(repr=False, compare=False, hash=False)
    _result_by_output: Mapping[
        tuple[LogicalPointId, ProductUseId],
        ClosedDomainResult[EntryAddressT, ResultAddressT],
    ] = field(repr=False, compare=False, hash=False)
    _product_by_id: Mapping[ProductId, ProductDef] = field(
        repr=False,
        compare=False,
        hash=False,
    )
    _contract_fingerprint: str = field(
        repr=False,
        compare=False,
        hash=False,
    )

    def __init__(
        self,
        linked_points: MaterializedLinkedPointSet,
        selected_product_use_ids: tuple[ProductUseId, ...],
        adapter_entries: tuple[AdapterEntryResults[EntryAddressT, ResultAddressT], ...],
        entries: tuple[ClosedDomainEntry[EntryAddressT, ResultAddressT], ...],
        results: tuple[ClosedDomainResult[EntryAddressT, ResultAddressT], ...],
    ) -> None:
        all_uses, products_by_id = _closed_product_inventory(linked_points)
        selected_uses = _canonical_selected_product_uses(
            all_uses,
            selected_product_use_ids,
        )
        canonical_use_ids = tuple(use.id for use in selected_uses)
        if selected_product_use_ids != canonical_use_ids:
            msg = "closed domain result mappings require canonical product-use order"
            raise ValueError(msg)
        expected_points = tuple(
            point.logical_id for point in linked_points.point_domain.points
        )
        if tuple(entry.logical_point_id for entry in entries) != expected_points:
            msg = "closed domain result mappings require canonical point order"
            raise ValueError(msg)
        if any(
            entry.point != point
            for entry, point in zip(
                entries,
                linked_points.point_domain.points,
                strict=True,
            )
        ):
            msg = "closed domain entries must retain their materialized points"
            raise ValueError(msg)
        expected_outputs = {
            (point_id, product_use_id)
            for point_id in expected_points
            for product_use_id in canonical_use_ids
        }
        use_by_id = {use.id: use for use in selected_uses}
        use_order = {use_id: index for index, use_id in enumerate(canonical_use_ids)}
        actual_outputs: list[tuple[LogicalPointId, ProductUseId]] = []
        for entry in entries:
            first_use_indices: list[int] = []
            result_product_ids: list[ProductId] = []
            for result in entry.results:
                if result.point != entry.point:
                    msg = "closed domain results must retain their materialized point"
                    raise ValueError(msg)
                expected_uses = tuple(
                    use_by_id[use_id]
                    for use_id in canonical_use_ids
                    if use_id in set(result.product_use_ids)
                )
                if result.product_uses != expected_uses:
                    msg = (
                        "closed domain results must retain canonical linked "
                        "product uses"
                    )
                    raise ValueError(msg)
                if not expected_uses:
                    msg = "closed domain results must retain selected product uses"
                    raise ValueError(msg)
                expected_product = products_by_id[expected_uses[0].product_id]
                if result.product != expected_product:
                    msg = (
                        "closed domain results must retain their linked output contract"
                    )
                    raise ValueError(msg)
                first_use_indices.append(use_order[expected_uses[0].id])
                result_product_ids.append(expected_product.id)
                actual_outputs.extend(
                    (entry.logical_point_id, use.id) for use in expected_uses
                )
            if first_use_indices != sorted(first_use_indices):
                msg = (
                    "closed domain results must follow canonical physical result order"
                )
                raise ValueError(msg)
            if len(result_product_ids) != len(set(result_product_ids)):
                msg = "one logical product result cannot be split across addresses"
                raise ValueError(msg)
        if len(actual_outputs) != len(expected_outputs) or set(actual_outputs) != (
            expected_outputs
        ):
            msg = (
                "closed domain results must exactly cover every selected "
                "logical point/product use"
            )
            raise ValueError(msg)
        if tuple(result for entry in entries for result in entry.results) != results:
            msg = "closed domain entries and result inventory must agree exactly"
            raise ValueError(msg)
        adapter_entries_by_address = _index_adapter_entries(adapter_entries)
        entry_by_address = {entry.entry_address: entry for entry in entries}
        entry_by_point = {entry.logical_point_id: entry for entry in entries}
        result_by_address = {result.result_address: result for result in results}
        result_by_output = {
            (result.logical_point_id, use_id): result
            for result in results
            for use_id in result.product_use_ids
        }
        if (
            len(entry_by_address) != len(entries)
            or len(entry_by_point) != len(entries)
            or len(result_by_address) != len(results)
            or len(result_by_output) != len(expected_outputs)
        ):
            msg = "closed domain result mappings require unique identities"
            raise ValueError(msg)
        if set(adapter_entries_by_address) != set(entry_by_address):
            msg = "closed domain entries must exactly cover adapter entries"
            raise ValueError(msg)
        expected_parent_by_result = {
            result_address: adapter_entry.entry_address
            for adapter_entry in adapter_entries
            for result_address in adapter_entry.result_addresses
        }
        if set(expected_parent_by_result) != set(result_by_address) or any(
            result.entry_address != expected_parent_by_result[result_address]
            for result_address, result in result_by_address.items()
        ):
            msg = "closed domain results must exactly cover adapter result addresses"
            raise ValueError(msg)
        object.__setattr__(self, "linked_points", linked_points)
        object.__setattr__(
            self,
            "selected_product_use_ids",
            canonical_use_ids,
        )
        object.__setattr__(self, "selected_product_uses", selected_uses)
        object.__setattr__(self, "adapter_entries", adapter_entries)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "results", results)
        object.__setattr__(
            self, "_entry_by_address", MappingProxyType(entry_by_address)
        )
        object.__setattr__(self, "_entry_by_point", MappingProxyType(entry_by_point))
        object.__setattr__(
            self, "_result_by_address", MappingProxyType(result_by_address)
        )
        object.__setattr__(
            self, "_result_by_output", MappingProxyType(result_by_output)
        )
        object.__setattr__(
            self,
            "_product_by_id",
            MappingProxyType(
                {
                    use.product_id: deepcopy(products_by_id[use.product_id])
                    for use in selected_uses
                }
            ),
        )
        object.__setattr__(
            self,
            "_contract_fingerprint",
            _domain_result_contract_fingerprint(self),
        )

    def product_for_use(self, product_use_id: ProductUseId) -> ProductDef:
        """Return the snapshotted product contract of one selected use."""

        selected = next(
            (use for use in self.selected_product_uses if use.id == product_use_id),
            None,
        )
        if selected is None:
            msg = f"product use {product_use_id.value!r} is not selected"
            raise KeyError(msg)
        return deepcopy(self._product_by_id[selected.product_id])

    def entry_for_address(
        self,
        entry_address: EntryAddressT,
    ) -> ClosedDomainEntry[EntryAddressT, ResultAddressT]:
        try:
            return self._entry_by_address[entry_address]
        except KeyError as error:
            msg = f"adapter entry address {entry_address!r} is not in this mapping"
            raise KeyError(msg) from error

    @property
    def contract_fingerprint(self) -> str:
        """Return the stable transient identity of this complete result contract."""

        return self._contract_fingerprint

    def entry_for_point(
        self,
        logical_point_id: LogicalPointId,
    ) -> ClosedDomainEntry[EntryAddressT, ResultAddressT]:
        try:
            return self._entry_by_point[logical_point_id]
        except KeyError as error:
            msg = f"logical point {logical_point_id.value!r} is not in this mapping"
            raise KeyError(msg) from error

    def result_for_address(
        self,
        result_address: ResultAddressT,
    ) -> ClosedDomainResult[EntryAddressT, ResultAddressT]:
        try:
            return self._result_by_address[result_address]
        except KeyError as error:
            msg = f"adapter result address {result_address!r} is not in this mapping"
            raise KeyError(msg) from error

    def result_for_output(
        self,
        logical_point_id: LogicalPointId,
        product_use_id: ProductUseId,
    ) -> ClosedDomainResult[EntryAddressT, ResultAddressT]:
        try:
            return self._result_by_output[(logical_point_id, product_use_id)]
        except KeyError as error:
            msg = (
                f"logical output ({logical_point_id.value!r}, "
                f"{product_use_id.value!r}) is not in this mapping"
            )
            raise KeyError(msg) from error


@dataclass(frozen=True, slots=True, init=False)
class SelectedDomainMeasurementOutputs[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
]:
    """Pre-effect proof that every mapped product has a measurement carrier."""

    mapping: ClosedDomainResultMapping[EntryAddressT, ResultAddressT] = field(
        repr=False
    )

    def __init__(
        self,
        mapping: ClosedDomainResultMapping[EntryAddressT, ResultAddressT],
    ) -> None:
        problems = _domain_measurement_output_selection_problems(mapping)
        if problems:
            raise CheckFailed(problems)
        object.__setattr__(self, "mapping", mapping)


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
    adapter_intent_fingerprint: str
    intent_fingerprint: str

    @field_validator(
        "invocation_id",
        "target_id",
        "compiler_id",
        "capability_fingerprint",
        "artifact_id",
        "artifact_fingerprint",
        "result_contract_fingerprint",
        "adapter_intent_fingerprint",
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
            adapter_intent_fingerprint=self.adapter_intent_fingerprint,
        )
        if self.intent_fingerprint != expected:
            msg = "domain invocation fingerprint does not cover its complete intent"
            raise ValueError(msg)
        return self


@dataclass(frozen=True, slots=True, init=False)
class ClosedDomainInvocation[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
    PayloadT,
]:
    """One target-selected invocation ready for effects.

    ``payload`` is deliberately transient and adapter-owned.  Durable host
    evidence uses only :attr:`intent`; the adapter payload owns any selected
    carrier or value policy independently of the exact retained result mapping.
    """

    intent: DomainInvocationIntent
    result_mapping: ClosedDomainResultMapping[
        EntryAddressT,
        ResultAddressT,
    ] = field(repr=False)
    payload: PayloadT = field(repr=False)

    def __init__(
        self,
        intent: DomainInvocationIntent,
        result_mapping: ClosedDomainResultMapping[
            EntryAddressT,
            ResultAddressT,
        ],
        payload: PayloadT,
    ) -> None:
        if intent.result_contract_fingerprint != result_mapping.contract_fingerprint:
            msg = "domain invocation intent does not cover its output contract"
            raise ValueError(msg)
        object.__setattr__(self, "intent", intent)
        object.__setattr__(self, "result_mapping", result_mapping)
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True, slots=True, init=False)
class ClosedDomainOutputValues[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """Accepted observable values in canonical physical-result order."""

    selection: SelectedDomainMeasurementOutputs[EntryAddressT, ResultAddressT] = field(
        repr=False
    )
    outputs: tuple[ClosedDomainOutputValue[EntryAddressT, ResultAddressT], ...]
    _by_address: Mapping[
        ResultAddressT,
        ClosedDomainOutputValue[EntryAddressT, ResultAddressT],
    ] = field(repr=False, compare=False, hash=False)
    _by_output: Mapping[
        tuple[LogicalPointId, ProductUseId],
        ClosedDomainOutputValue[EntryAddressT, ResultAddressT],
    ] = field(repr=False, compare=False, hash=False)

    def __init__(
        self,
        selection: SelectedDomainMeasurementOutputs[EntryAddressT, ResultAddressT],
        outputs: tuple[ClosedDomainOutputValue[EntryAddressT, ResultAddressT], ...],
    ) -> None:
        mapping = selection.mapping
        selected = outputs
        if len(selected) != len(mapping.results) or any(
            output.result is not result
            for output, result in zip(selected, mapping.results, strict=True)
        ):
            msg = "closed domain output values must retain exact mapped results"
            raise ValueError(msg)
        by_address = {output.result_address: output for output in selected}
        by_output = {
            (output.logical_point_id, product_use_id): output
            for output in selected
            for product_use_id in output.product_use_ids
        }
        expected_output_count = sum(len(output.product_use_ids) for output in selected)
        if len(by_address) != len(selected) or len(by_output) != expected_output_count:
            msg = "closed domain output values require unique logical identities"
            raise ValueError(msg)
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "outputs", selected)
        object.__setattr__(self, "_by_address", MappingProxyType(by_address))
        object.__setattr__(self, "_by_output", MappingProxyType(by_output))

    @property
    def mapping(
        self,
    ) -> ClosedDomainResultMapping[EntryAddressT, ResultAddressT]:
        return self.selection.mapping

    def output_for_address(
        self,
        result_address: ResultAddressT,
    ) -> ClosedDomainOutputValue[EntryAddressT, ResultAddressT]:
        try:
            return self._by_address[result_address]
        except KeyError as error:
            msg = f"domain result address {result_address!r} has no accepted value"
            raise KeyError(msg) from error

    def output_for_output(
        self,
        logical_point_id: LogicalPointId,
        product_use_id: ProductUseId,
    ) -> ClosedDomainOutputValue[EntryAddressT, ResultAddressT]:
        try:
            return self._by_output[(logical_point_id, product_use_id)]
        except KeyError as error:
            msg = (
                "logical output has no accepted value: "
                f"point={logical_point_id.value!r}, use={product_use_id.value!r}"
            )
            raise KeyError(msg) from error


def close_domain_invocation[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
    PayloadT,
](
    result_mapping: ClosedDomainResultMapping[
        EntryAddressT,
        ResultAddressT,
    ],
    *,
    invocation_id: str,
    target_id: str,
    compiler_id: str,
    capability_fingerprint: str,
    artifact_id: str,
    artifact_fingerprint: str,
    adapter_intent: object,
    payload: PayloadT,
) -> ClosedDomainInvocation[EntryAddressT, ResultAddressT, PayloadT]:
    """Close stable target and output facts around an opaque adapter payload."""

    result_contract_fingerprint = result_mapping.contract_fingerprint
    adapter_intent_fingerprint = stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.domain_adapter_intent.v1",
                "value": adapter_intent,
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
        adapter_intent_fingerprint=adapter_intent_fingerprint,
    )
    intent = DomainInvocationIntent(
        invocation_id=invocation_id,
        target_id=target_id,
        compiler_id=compiler_id,
        capability_fingerprint=capability_fingerprint,
        artifact_id=artifact_id,
        artifact_fingerprint=artifact_fingerprint,
        result_contract_fingerprint=result_contract_fingerprint,
        adapter_intent_fingerprint=adapter_intent_fingerprint,
        intent_fingerprint=intent_fingerprint,
    )
    return ClosedDomainInvocation(
        intent,
        result_mapping,
        payload,
    )


def seal_domain_result_mapping[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    linked_points: MaterializedLinkedPointSet,
    selected_product_use_ids: Sequence[ProductUseId],
    adapter_entries: Sequence[AdapterEntryResults[EntryAddressT, ResultAddressT]],
    entry_bindings: Sequence[EntryPointBinding[EntryAddressT]],
    result_bindings: Sequence[ResultUseBinding[EntryAddressT, ResultAddressT]],
) -> ClosedDomainResultMapping[EntryAddressT, ResultAddressT]:
    """Close exact adapter coverage for selected uses of one linked point plan."""

    all_uses, products_by_id = _closed_product_inventory(linked_points)
    selected_uses = _canonical_selected_product_uses(
        all_uses,
        tuple(selected_product_use_ids),
    )
    canonical_product_use_ids = tuple(use.id for use in selected_uses)
    selected_adapter_entries = tuple(adapter_entries)
    selected_entry_bindings = tuple(entry_bindings)
    selected_result_bindings = tuple(result_bindings)

    adapter_entries_by_address = _index_adapter_entries(selected_adapter_entries)
    point_bindings_by_entry = _close_entry_bindings(
        linked_points,
        adapter_entries_by_address,
        selected_entry_bindings,
    )
    bindings_by_result = _close_result_inventory(
        adapter_entries_by_address,
        selected_result_bindings,
    )
    all_use_by_id = {use.id: use for use in all_uses}
    selected_use_ids = set(canonical_product_use_ids)
    point_by_id = {
        point.logical_id: point for point in linked_points.point_domain.points
    }
    entry_by_point = {
        binding.logical_point_id: binding.entry_address
        for binding in point_bindings_by_entry.values()
    }

    expected_outputs = {
        (point.logical_id, use.id)
        for point in linked_points.point_domain.points
        for use in selected_uses
    }
    bindings_by_output: dict[
        tuple[LogicalPointId, ProductUseId],
        ResultUseBinding[EntryAddressT, ResultAddressT],
    ] = {}
    product_address_by_point: dict[
        tuple[LogicalPointId, ProductId], ResultAddressT
    ] = {}
    for result_address, result_bindings in bindings_by_result.items():
        product_ids: set[ProductId] = set()
        for binding in result_bindings:
            point_binding = point_bindings_by_entry[binding.entry_address]
            output_address = (point_binding.logical_point_id, binding.product_use_id)
            if binding.product_use_id not in all_use_by_id:
                msg = (
                    "adapter result references unknown product use "
                    f"{binding.product_use_id.value!r}"
                )
                raise ValueError(msg)
            if binding.product_use_id not in selected_use_ids:
                msg = (
                    "adapter result references unselected product use "
                    f"{binding.product_use_id.value!r}"
                )
                raise ValueError(msg)
            if output_address in bindings_by_output:
                msg = "adapter results must map each logical point/product use once"
                raise ValueError(msg)
            bindings_by_output[output_address] = binding
            product_ids.add(all_use_by_id[binding.product_use_id].product_id)
        if len(product_ids) != 1:
            msg = (
                "one adapter result address may fan out only within one "
                "logical product result"
            )
            raise ValueError(msg)
        product_id = next(iter(product_ids))
        first_binding = result_bindings[0]
        logical_point_id = point_bindings_by_entry[
            first_binding.entry_address
        ].logical_point_id
        product_key = (logical_point_id, product_id)
        existing_address = product_address_by_point.get(product_key)
        if existing_address is not None and existing_address != result_address:
            msg = "one logical product result cannot be split across addresses"
            raise ValueError(msg)
        product_address_by_point[product_key] = result_address
    if set(bindings_by_output) != expected_outputs:
        msg = (
            "adapter results must exactly cover every logical point and selected "
            "product use"
        )
        raise ValueError(msg)

    closed_results: list[ClosedDomainResult[EntryAddressT, ResultAddressT]] = []
    closed_entries: list[ClosedDomainEntry[EntryAddressT, ResultAddressT]] = []
    use_order = {use.id: index for index, use in enumerate(selected_uses)}
    for point in linked_points.point_domain.points:
        entry_address = entry_by_point[point.logical_id]
        entry_results: list[ClosedDomainResult[EntryAddressT, ResultAddressT]] = []
        adapter_entry = adapter_entries_by_address[entry_address]
        for result_address in adapter_entry.result_addresses:
            result_bindings = bindings_by_result[result_address]
            bound_use_ids = {binding.product_use_id for binding in result_bindings}
            result_uses = tuple(use for use in selected_uses if use.id in bound_use_ids)
            product = products_by_id[result_uses[0].product_id]
            result = ClosedDomainResult(
                entry_address=entry_address,
                result_address=result_address,
                point=point_by_id[point.logical_id],
                product_uses=result_uses,
                product=product,
            )
            entry_results.append(result)
        entry_results.sort(
            key=lambda result: min(
                use_order[use_id] for use_id in result.product_use_ids
            )
        )
        closed_results.extend(entry_results)
        closed_entries.append(
            ClosedDomainEntry(
                entry_address=entry_address,
                point=point,
                results=tuple(entry_results),
            )
        )
    return ClosedDomainResultMapping(
        linked_points,
        canonical_product_use_ids,
        selected_adapter_entries,
        tuple(closed_entries),
        tuple(closed_results),
    )


def select_domain_measurement_outputs[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    mapping: ClosedDomainResultMapping[EntryAddressT, ResultAddressT],
) -> SelectedDomainMeasurementOutputs[EntryAddressT, ResultAddressT]:
    """Select representable observable carriers before any adapter effect."""

    return SelectedDomainMeasurementOutputs(mapping)


def _domain_measurement_output_selection_problems[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    mapping: ClosedDomainResultMapping[EntryAddressT, ResultAddressT],
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
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    selection: SelectedDomainMeasurementOutputs[EntryAddressT, ResultAddressT],
    values: Sequence[DomainOutputValue[ResultAddressT]],
) -> ClosedDomainOutputValues[EntryAddressT, ResultAddressT]:
    """Accept exact observable-value coverage against retained contracts.

    The adapter supplies only opaque result addresses and measurement values.
    Point, product-use, and product identity are derived from ``mapping``.  Any
    coverage or value-contract problem rejects the complete candidate set; no
    partial accepted proof is returned. This first carrier supports observable
    products only; artifact and other product kinds require distinct payload
    closures rather than overloading ``MeasurementValue``.
    """

    mapping = selection.mapping
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

    outputs = tuple(
        ClosedDomainOutputValue(
            result,
            by_address[result.result_address].value,
        )
        for result in mapping.results
    )
    return ClosedDomainOutputValues(
        selection,
        outputs,
    )


def _index_adapter_entries[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    entries: tuple[AdapterEntryResults[EntryAddressT, ResultAddressT], ...],
) -> dict[EntryAddressT, AdapterEntryResults[EntryAddressT, ResultAddressT]]:
    by_address = {entry.entry_address: entry for entry in entries}
    if len(by_address) != len(entries):
        msg = "adapter entry addresses must be unique"
        raise ValueError(msg)
    all_results = [
        result_address for entry in entries for result_address in entry.result_addresses
    ]
    if len(set(all_results)) != len(all_results):
        msg = "adapter result addresses must be globally unique"
        raise ValueError(msg)
    return by_address


def _close_entry_bindings[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    linked_points: MaterializedLinkedPointSet,
    adapter_entries: Mapping[
        EntryAddressT, AdapterEntryResults[EntryAddressT, ResultAddressT]
    ],
    bindings: tuple[EntryPointBinding[EntryAddressT], ...],
) -> dict[EntryAddressT, EntryPointBinding[EntryAddressT]]:
    by_entry = {binding.entry_address: binding for binding in bindings}
    if len(by_entry) != len(bindings):
        msg = "entry-point bindings require unique adapter entries"
        raise ValueError(msg)
    if set(by_entry) != set(adapter_entries):
        msg = "entry-point bindings must exactly cover adapter entries"
        raise ValueError(msg)
    by_point = {binding.logical_point_id: binding for binding in bindings}
    if len(by_point) != len(bindings):
        msg = "entry-point bindings require unique logical points"
        raise ValueError(msg)
    expected_points = {point.logical_id for point in linked_points.point_domain.points}
    if set(by_point) != expected_points:
        msg = "entry-point bindings must exactly cover materialized logical points"
        raise ValueError(msg)
    return by_entry


def _close_result_inventory[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    adapter_entries: Mapping[
        EntryAddressT, AdapterEntryResults[EntryAddressT, ResultAddressT]
    ],
    bindings: tuple[ResultUseBinding[EntryAddressT, ResultAddressT], ...],
) -> dict[
    ResultAddressT,
    tuple[ResultUseBinding[EntryAddressT, ResultAddressT], ...],
]:
    edge_ids = tuple(
        (binding.result_address, binding.product_use_id) for binding in bindings
    )
    if len(set(edge_ids)) != len(edge_ids):
        msg = "result-use bindings require unique result/product-use edges"
        raise ValueError(msg)
    grouped: dict[
        ResultAddressT,
        list[ResultUseBinding[EntryAddressT, ResultAddressT]],
    ] = {}
    for binding in bindings:
        grouped.setdefault(binding.result_address, []).append(binding)
    expected_parent_by_result = {
        result_address: entry.entry_address
        for entry in adapter_entries.values()
        for result_address in entry.result_addresses
    }
    if set(grouped) != set(expected_parent_by_result):
        msg = "result-use bindings must exactly cover adapter result addresses"
        raise ValueError(msg)
    for result_address, selected in grouped.items():
        if any(
            binding.entry_address != expected_parent_by_result[result_address]
            for binding in selected
        ):
            msg = "result-use binding does not belong to its adapter entry"
            raise ValueError(msg)
    return {
        result_address: tuple(selected) for result_address, selected in grouped.items()
    }


def _closed_product_inventory(
    linked_points: MaterializedLinkedPointSet,
) -> tuple[tuple[ProductUse, ...], dict[ProductId, ProductDef]]:
    program = linked_points.linked_plan.program
    products_by_id = {product.id: product for product in program.product_defs}
    if len(products_by_id) != len(program.product_defs):
        msg = "linked domain mappings require unique product definitions"
        raise ValueError(msg)
    uses_by_id = {use.id: use for use in program.product_uses}
    if len(uses_by_id) != len(program.product_uses):
        msg = "linked domain mappings require unique product uses"
        raise ValueError(msg)
    if any(use.product_id not in products_by_id for use in program.product_uses):
        msg = "linked domain product uses must reference retained definitions"
        raise ValueError(msg)
    return program.product_uses, products_by_id


def _canonical_selected_product_uses(
    all_uses: tuple[ProductUse, ...],
    selected_product_use_ids: tuple[ProductUseId, ...],
) -> tuple[ProductUse, ...]:
    if len(set(selected_product_use_ids)) != len(selected_product_use_ids):
        msg = "selected product use IDs must be unique"
        raise ValueError(msg)
    known_ids = {use.id for use in all_uses}
    unknown_ids = tuple(
        product_use_id
        for product_use_id in selected_product_use_ids
        if product_use_id not in known_ids
    )
    if unknown_ids:
        rendered = ", ".join(
            repr(product_use_id.value) for product_use_id in unknown_ids
        )
        msg = f"selected product uses are not in the linked plan: {rendered}"
        raise ValueError(msg)
    selected_ids = set(selected_product_use_ids)
    return tuple(use for use in all_uses if use.id in selected_ids)


def _copy_measurement_value(value: MeasurementValue) -> MeasurementValue:
    return validated_measurement_value_copy(value)


def _domain_result_contract_fingerprint[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    mapping: ClosedDomainResultMapping[EntryAddressT, ResultAddressT],
) -> str:
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.domain_result_contract.v4",
                "entries": [
                    {
                        "entry_address": entry.entry_address,
                        "logical_point_id": entry.logical_point_id.value,
                    }
                    for entry in mapping.entries
                ],
                "selected_product_uses": [
                    {
                        "product_use_id": use.id.value,
                        "product": mapping.product_for_use(use.id),
                    }
                    for use in mapping.selected_product_uses
                ],
                "results": [
                    {
                        "entry_address": result.entry_address,
                        "result_address": result.result_address,
                        "logical_point_id": result.logical_point_id.value,
                        "product_use_ids": [
                            use_id.value for use_id in result.product_use_ids
                        ],
                        "product": result.product,
                    }
                    for result in mapping.results
                ],
            }
        )
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
    adapter_intent_fingerprint: str,
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
            "adapter_intent_fingerprint": adapter_intent_fingerprint,
        }
    )


def _domain_output_identity_details[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    result: ClosedDomainResult[EntryAddressT, ResultAddressT],
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
    "AdapterEntryResults",
    "ClosedDomainEntry",
    "ClosedDomainInvocation",
    "ClosedDomainOutputValue",
    "ClosedDomainOutputValues",
    "ClosedDomainResult",
    "ClosedDomainResultMapping",
    "DomainInvocationIntent",
    "DomainOutputValue",
    "EntryPointBinding",
    "LinkedPlan",
    "LogicalPointId",
    "MaterializedLinkedPointBatch",
    "MaterializedLinkedPointSet",
    "MaterializedLinkedPoints",
    "MaterializedPoint",
    "MaterializedPointDomain",
    "ProductDef",
    "ProductId",
    "ProductUse",
    "ProductUseId",
    "ResultUseBinding",
    "SelectedDomainMeasurementOutputs",
    "close_domain_invocation",
    "materialize_linked_points",
    "seal_domain_output_values",
    "seal_domain_result_mapping",
    "select_domain_measurement_outputs",
]
