"""Pure adapter proofs for domain-program result identity and values.

This public module is the narrow target-integration seam between Scopecat's
transient compiler and a domain package. It closes logical identity mappings
before target effects and can accept exact correlated measurement values
afterward, but deliberately does not define a runtime protocol, resource
claims, retries, persistence, or a general domain-program representation.
"""

from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from scopecat._compiler.linked import (
    LinkedPlan,
    MaterializedLinkedPoints,
    materialize_linked_points,
)
from scopecat._compiler.point_domain import (
    LogicalPointId,
    MaterializedPoint,
    MaterializedPointDomain,
)
from scopecat._compiler.products import ProductDef
from scopecat._measurement_value_contract import (
    measurement_value_contract_issues,
    validated_measurement_value_copy,
)
from scopecat._product_identity import (
    ProductId,
    ProductUse,
    ProductUseId,
)
from scopecat.errors import CheckFailed, ProviderContractError
from scopecat.models.measurement import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementValue,
)
from scopecat.models.parameter import Quantity
from scopecat.problems import (
    Problem,
    ProblemCategory,
    ProblemPhase,
    blocking_problem,
    model_location,
)

_CLOSED_DOMAIN_RESULT_MAPPING_TOKEN = object()
_CLOSED_DOMAIN_RESULT_TOKEN = object()
_CLOSED_DOMAIN_ENTRY_TOKEN = object()
_CLOSED_DOMAIN_OUTPUT_VALUE_TOKEN = object()
_CLOSED_DOMAIN_OUTPUT_VALUES_TOKEN = object()
_SELECTED_DOMAIN_MEASUREMENT_OUTPUTS_TOKEN = object()


@dataclass(frozen=True, slots=True)
class AdapterEntryResults[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """One adapter entry and its complete ordered result-address inventory."""

    entry_address: EntryAddressT
    result_addresses: tuple[ResultAddressT, ...] = ()

    def __post_init__(self) -> None:
        _require_hashable(self.entry_address, label="adapter entry address")
        selected = tuple(self.result_addresses)
        _require_unique_hashable(
            selected,
            label="adapter result addresses",
            item_label="adapter result address",
        )
        object.__setattr__(self, "result_addresses", selected)


@dataclass(frozen=True, slots=True)
class EntryPointBinding[EntryAddressT: Hashable]:
    """Adapter-declared edge from one entry to an existing logical point."""

    entry_address: EntryAddressT
    logical_point_id: LogicalPointId

    def __post_init__(self) -> None:
        _require_hashable(self.entry_address, label="adapter entry address")
        if not isinstance(cast("object", self.logical_point_id), LogicalPointId):
            msg = "entry-point bindings require a LogicalPointId"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class ResultUseBinding[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """Adapter-declared edge from one entry result to a logical product use."""

    entry_address: EntryAddressT
    result_address: ResultAddressT
    product_use_id: ProductUseId

    def __post_init__(self) -> None:
        _require_hashable(self.entry_address, label="adapter entry address")
        _require_hashable(self.result_address, label="adapter result address")
        if not isinstance(cast("object", self.product_use_id), ProductUseId):
            msg = "result-use bindings require a ProductUseId"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True)
class DomainOutputValue[ResultAddressT: Hashable]:
    """Adapter candidate relating one opaque result address to one value.

    Logical point, product-use, and product identity are deliberately absent.
    They are recovered from a sealed result mapping when the complete output
    inventory is accepted.
    """

    result_address: ResultAddressT
    value: MeasurementValue

    def __post_init__(self) -> None:
        _require_hashable(self.result_address, label="domain output result address")
        if not _is_measurement_value(cast("object", self.value)):
            msg = "domain output values require a MeasurementValue"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True, init=False)
class ClosedDomainResult[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """One checked target result with its exact logical output contract."""

    entry_address: EntryAddressT
    result_address: ResultAddressT
    point: MaterializedPoint = field(repr=False)
    product_use: ProductUse = field(repr=False)
    _product: ProductDef = field(repr=False)

    def __init__(
        self,
        entry_address: EntryAddressT,
        result_address: ResultAddressT,
        point: MaterializedPoint,
        product_use: ProductUse,
        product: ProductDef,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _CLOSED_DOMAIN_RESULT_TOKEN:
            msg = "ClosedDomainResult can only be created by result mapping sealing"
            raise TypeError(msg)
        if product_use.product_id != product.id:
            msg = "closed domain results must retain their exact product contract"
            raise ValueError(msg)
        object.__setattr__(self, "entry_address", entry_address)
        object.__setattr__(self, "result_address", result_address)
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "product_use", product_use)
        object.__setattr__(self, "_product", product.model_copy(deep=True))

    @property
    def logical_point_id(self) -> LogicalPointId:
        return self.point.logical_id

    @property
    def product_use_id(self) -> ProductUseId:
        return self.product_use.id

    @property
    def product_id(self) -> ProductId:
        return self._product.id

    @property
    def product(self) -> ProductDef:
        """Return a defensive copy of the retained logical product contract."""

        return self._product.model_copy(deep=True)


@dataclass(frozen=True, slots=True, init=False)
class ClosedDomainOutputValue[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """One accepted measurement value retaining its exact mapped result."""

    result: ClosedDomainResult[EntryAddressT, ResultAddressT] = field(repr=False)
    _value: MeasurementValue = field(repr=False)

    def __init__(
        self,
        result: ClosedDomainResult[EntryAddressT, ResultAddressT],
        value: MeasurementValue,
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _CLOSED_DOMAIN_OUTPUT_VALUE_TOKEN:
            msg = (
                "ClosedDomainOutputValue can only be created by "
                "seal_domain_output_values"
            )
            raise TypeError(msg)
        if not isinstance(cast("object", result), ClosedDomainResult):
            msg = "closed domain output values require a ClosedDomainResult"
            raise TypeError(msg)
        if not _is_measurement_value(cast("object", value)):
            msg = "closed domain output values require a MeasurementValue"
            raise TypeError(msg)
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
    def product_use_id(self) -> ProductUseId:
        return self.result.product_use_id

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
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _CLOSED_DOMAIN_ENTRY_TOKEN:
            msg = "ClosedDomainEntry can only be created by result mapping sealing"
            raise TypeError(msg)
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
    """Exact, construction-controlled mapping of adapter work to core outputs.

    Entries and results are exposed in canonical ``point x product-use`` order;
    ``adapter_entries`` separately preserves the adapter's own ordering.  The
    proof covers the linked plan's complete logical product-use inventory.
    """

    linked_points: MaterializedLinkedPoints
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

    def __init__(
        self,
        linked_points: MaterializedLinkedPoints,
        adapter_entries: tuple[AdapterEntryResults[EntryAddressT, ResultAddressT], ...],
        entries: tuple[ClosedDomainEntry[EntryAddressT, ResultAddressT], ...],
        results: tuple[ClosedDomainResult[EntryAddressT, ResultAddressT], ...],
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _CLOSED_DOMAIN_RESULT_MAPPING_TOKEN:
            msg = (
                "ClosedDomainResultMapping can only be created by "
                "seal_domain_result_mapping"
            )
            raise TypeError(msg)
        entry_by_address = {entry.entry_address: entry for entry in entries}
        entry_by_point = {entry.logical_point_id: entry for entry in entries}
        result_by_address = {result.result_address: result for result in results}
        result_by_output = {
            (result.logical_point_id, result.product_use_id): result
            for result in results
        }
        if (
            len(entry_by_address) != len(entries)
            or len(entry_by_point) != len(entries)
            or len(result_by_address) != len(results)
            or len(result_by_output) != len(results)
        ):
            msg = "closed domain result mappings require unique identities"
            raise ValueError(msg)
        object.__setattr__(self, "linked_points", linked_points)
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

    def entry_for_address(
        self,
        entry_address: EntryAddressT,
    ) -> ClosedDomainEntry[EntryAddressT, ResultAddressT]:
        try:
            return self._entry_by_address[entry_address]
        except KeyError as error:
            msg = f"adapter entry address {entry_address!r} is not in this mapping"
            raise KeyError(msg) from error

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
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _SELECTED_DOMAIN_MEASUREMENT_OUTPUTS_TOKEN:
            msg = (
                "SelectedDomainMeasurementOutputs can only be created by "
                "select_domain_measurement_outputs"
            )
            raise TypeError(msg)
        if not isinstance(cast("object", mapping), ClosedDomainResultMapping):
            msg = "domain measurement output selection requires a result mapping"
            raise TypeError(msg)
        object.__setattr__(self, "mapping", mapping)


@dataclass(frozen=True, slots=True, init=False)
class ClosedDomainOutputValues[EntryAddressT: Hashable, ResultAddressT: Hashable]:
    """Accepted observable values in canonical point/product-use order."""

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
        *,
        _token: object | None = None,
    ) -> None:
        if _token is not _CLOSED_DOMAIN_OUTPUT_VALUES_TOKEN:
            msg = (
                "ClosedDomainOutputValues can only be created by "
                "seal_domain_output_values"
            )
            raise TypeError(msg)
        if not isinstance(cast("object", selection), SelectedDomainMeasurementOutputs):
            msg = "closed domain output values require a selected measurement carrier"
            raise TypeError(msg)
        mapping = selection.mapping
        selected = tuple(outputs)
        if len(selected) != len(mapping.results) or any(
            output.result is not result
            for output, result in zip(selected, mapping.results, strict=True)
        ):
            msg = "closed domain output values must retain exact mapped results"
            raise ValueError(msg)
        by_address = {output.result_address: output for output in selected}
        by_output = {
            (output.logical_point_id, output.product_use_id): output
            for output in selected
        }
        if len(by_address) != len(selected) or len(by_output) != len(selected):
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


def seal_domain_result_mapping[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    linked_points: MaterializedLinkedPoints,
    adapter_entries: Sequence[AdapterEntryResults[EntryAddressT, ResultAddressT]],
    entry_bindings: Sequence[EntryPointBinding[EntryAddressT]],
    result_bindings: Sequence[ResultUseBinding[EntryAddressT, ResultAddressT]],
) -> ClosedDomainResultMapping[EntryAddressT, ResultAddressT]:
    """Close exact adapter entry/result coverage against one linked point plan."""

    if not isinstance(cast("object", linked_points), MaterializedLinkedPoints):
        msg = "domain result mapping requires MaterializedLinkedPoints"
        raise TypeError(msg)
    selected_adapter_entries = tuple(adapter_entries)
    if any(
        not isinstance(cast("object", entry), AdapterEntryResults)
        for entry in selected_adapter_entries
    ):
        msg = "adapter entry inventory requires AdapterEntryResults"
        raise TypeError(msg)
    selected_entry_bindings = tuple(entry_bindings)
    if any(
        not isinstance(cast("object", binding), EntryPointBinding)
        for binding in selected_entry_bindings
    ):
        msg = "entry mapping requires EntryPointBinding"
        raise TypeError(msg)
    selected_result_bindings = tuple(result_bindings)
    if any(
        not isinstance(cast("object", binding), ResultUseBinding)
        for binding in selected_result_bindings
    ):
        msg = "result mapping requires ResultUseBinding"
        raise TypeError(msg)

    adapter_entries_by_address = _index_adapter_entries(selected_adapter_entries)
    point_bindings_by_entry = _close_entry_bindings(
        linked_points,
        adapter_entries_by_address,
        selected_entry_bindings,
    )
    binding_by_result = _close_result_inventory(
        adapter_entries_by_address,
        selected_result_bindings,
    )
    uses, products_by_id = _closed_product_inventory(linked_points)
    use_by_id = {use.id: use for use in uses}
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
        for use in uses
    }
    bindings_by_output: dict[
        tuple[LogicalPointId, ProductUseId],
        ResultUseBinding[EntryAddressT, ResultAddressT],
    ] = {}
    for binding in binding_by_result.values():
        point_binding = point_bindings_by_entry[binding.entry_address]
        output_address = (point_binding.logical_point_id, binding.product_use_id)
        if binding.product_use_id not in use_by_id:
            msg = (
                "adapter result references unknown product use "
                f"{binding.product_use_id.value!r}"
            )
            raise ValueError(msg)
        if output_address in bindings_by_output:
            msg = "adapter results must map each logical point/product use once"
            raise ValueError(msg)
        bindings_by_output[output_address] = binding
    if set(bindings_by_output) != expected_outputs:
        msg = "adapter results must exactly cover every logical point/product use"
        raise ValueError(msg)

    closed_results: list[ClosedDomainResult[EntryAddressT, ResultAddressT]] = []
    closed_entries: list[ClosedDomainEntry[EntryAddressT, ResultAddressT]] = []
    for point in linked_points.point_domain.points:
        entry_address = entry_by_point[point.logical_id]
        entry_results: list[ClosedDomainResult[EntryAddressT, ResultAddressT]] = []
        for use in uses:
            binding = bindings_by_output[(point.logical_id, use.id)]
            result = ClosedDomainResult(
                entry_address=entry_address,
                result_address=binding.result_address,
                point=point_by_id[point.logical_id],
                product_use=use,
                product=products_by_id[use.product_id],
                _token=_CLOSED_DOMAIN_RESULT_TOKEN,
            )
            entry_results.append(result)
            closed_results.append(result)
        closed_entries.append(
            ClosedDomainEntry(
                entry_address=entry_address,
                point=point,
                results=tuple(entry_results),
                _token=_CLOSED_DOMAIN_ENTRY_TOKEN,
            )
        )
    return ClosedDomainResultMapping(
        linked_points,
        selected_adapter_entries,
        tuple(closed_entries),
        tuple(closed_results),
        _token=_CLOSED_DOMAIN_RESULT_MAPPING_TOKEN,
    )


def select_domain_measurement_outputs[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    mapping: ClosedDomainResultMapping[EntryAddressT, ResultAddressT],
) -> SelectedDomainMeasurementOutputs[EntryAddressT, ResultAddressT]:
    """Select representable observable carriers before any adapter effect."""

    if not isinstance(cast("object", mapping), ClosedDomainResultMapping):
        msg = "domain measurement output selection requires a result mapping"
        raise TypeError(msg)
    problems: list[Problem] = []
    for result_index, result in enumerate(mapping.results):
        product = result.product
        identity_details = _domain_output_identity_details(result)
        if product.kind != "observable":
            problems.append(
                _domain_output_selection_problem(
                    "domain_output_product_kind_unsupported",
                    "domain measurement output closure supports observable "
                    f"products only, got {product.kind!r}",
                    path=("results", result_index, "product", "kind"),
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
                    path=("results", result_index, "product", "dtype"),
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
    if problems:
        raise CheckFailed(problems)
    return SelectedDomainMeasurementOutputs(
        mapping,
        _token=_SELECTED_DOMAIN_MEASUREMENT_OUTPUTS_TOKEN,
    )


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

    if not isinstance(cast("object", selection), SelectedDomainMeasurementOutputs):
        msg = "domain output value sealing requires selected measurement outputs"
        raise TypeError(msg)
    mapping = selection.mapping
    selected = tuple(values)
    if any(
        not isinstance(cast("object", value), DomainOutputValue) for value in selected
    ):
        msg = "domain output value sealing requires DomainOutputValue candidates"
        raise TypeError(msg)

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
                    f"point {result.logical_point_id.value!r}, product use "
                    f"{result.product_use_id.value!r}",
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
            _token=_CLOSED_DOMAIN_OUTPUT_VALUE_TOKEN,
        )
        for result in mapping.results
    )
    return ClosedDomainOutputValues(
        selection,
        outputs,
        _token=_CLOSED_DOMAIN_OUTPUT_VALUES_TOKEN,
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
    linked_points: MaterializedLinkedPoints,
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
) -> dict[ResultAddressT, ResultUseBinding[EntryAddressT, ResultAddressT]]:
    by_result = {binding.result_address: binding for binding in bindings}
    if len(by_result) != len(bindings):
        msg = "result-use bindings require unique adapter result addresses"
        raise ValueError(msg)
    expected_parent_by_result = {
        result_address: entry.entry_address
        for entry in adapter_entries.values()
        for result_address in entry.result_addresses
    }
    if set(by_result) != set(expected_parent_by_result):
        msg = "result-use bindings must exactly cover adapter result addresses"
        raise ValueError(msg)
    for result_address, binding in by_result.items():
        if binding.entry_address != expected_parent_by_result[result_address]:
            msg = "result-use binding does not belong to its adapter entry"
            raise ValueError(msg)
    return by_result


def _closed_product_inventory(
    linked_points: MaterializedLinkedPoints,
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


def _require_hashable(value: object, *, label: str) -> None:
    try:
        hash(value)
    except TypeError as error:
        msg = f"{label} must be hashable"
        raise TypeError(msg) from error


def _require_unique_hashable(
    values: Sequence[object],
    *,
    label: str,
    item_label: str,
) -> None:
    for value in values:
        _require_hashable(value, label=item_label)
    if len(set(values)) != len(values):
        msg = f"{label} must be unique"
        raise ValueError(msg)


def _is_measurement_value(value: object) -> bool:
    return isinstance(value, Quantity | ComplexQuantity | MeasurementArray)


def _copy_measurement_value(value: MeasurementValue) -> MeasurementValue:
    return validated_measurement_value_copy(value)


def _domain_output_identity_details[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    result: ClosedDomainResult[EntryAddressT, ResultAddressT],
) -> dict[str, object]:
    return {
        "logical_point_id": result.logical_point_id.value,
        "product_use_id": result.product_use_id.value,
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
    "ClosedDomainOutputValue",
    "ClosedDomainOutputValues",
    "ClosedDomainResult",
    "ClosedDomainResultMapping",
    "DomainOutputValue",
    "EntryPointBinding",
    "LinkedPlan",
    "LogicalPointId",
    "MaterializedLinkedPoints",
    "MaterializedPoint",
    "MaterializedPointDomain",
    "ProductDef",
    "ProductId",
    "ProductUse",
    "ProductUseId",
    "ResultUseBinding",
    "SelectedDomainMeasurementOutputs",
    "materialize_linked_points",
    "seal_domain_output_values",
    "seal_domain_result_mapping",
    "select_domain_measurement_outputs",
]
