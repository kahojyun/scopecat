"""Producer-neutral host assembly for point-local measurement product values.

Static fragment ownership is selected before effects. Runtime fragments then
close exact ``point x product-use`` value inventories against that selection,
and assembly removes source-specific addresses while preserving logical
identity and value contracts.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import cast

from pydantic import JsonValue

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.compiler.linking.linked import (
    MaterializedLinkedPointBatch,
    MaterializedLinkedPoints,
    MaterializedLinkedPointSet,
)
from scopecat.compiler.typed.point_domain import LogicalPointId, MaterializedPoint
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
from scopecat.kernel.product_identity import ProductId, ProductUse, ProductUseId
from scopecat.measurements.contracts import (
    measurement_value_contract_issues,
    validated_measurement_value_copy,
)
from scopecat.records.measurement import (
    ComplexQuantity,
    MeasurementArray,
    MeasurementValue,
)
from scopecat.records.parameter import Quantity
from scopecat.sdk.domain.invocation import (
    ClosedDomainOutputValues,
    SelectedDomainMeasurementOutputs,
)


@dataclass(frozen=True, slots=True)
class ProductValueFragmentDef:
    """Pre-effect ownership declaration for one producer-neutral fragment."""

    id: str
    product_use_ids: tuple[ProductUseId, ...]

    def __post_init__(self) -> None:
        if not self.id:
            msg = "measurement value fragment id must be non-empty"
            raise ValueError(msg)
        selected = tuple(self.product_use_ids)
        if any(
            not isinstance(cast("object", use_id), ProductUseId) for use_id in selected
        ):
            msg = "measurement value fragment uses require ProductUseId values"
            raise TypeError(msg)
        object.__setattr__(self, "product_use_ids", selected)


@dataclass(frozen=True, slots=True, init=False)
class SelectedMeasurementValueFragment:
    """Canonical fragment ownership sealed by an assembly selection."""

    id: str
    product_use_ids: tuple[ProductUseId, ...]
    contract_fingerprint: str

    def __init__(
        self,
        fragment_id: str,
        product_use_ids: tuple[ProductUseId, ...],
        contract_fingerprint: str,
    ) -> None:
        object.__setattr__(self, "id", fragment_id)
        object.__setattr__(self, "product_use_ids", product_use_ids)
        object.__setattr__(self, "contract_fingerprint", contract_fingerprint)


@dataclass(frozen=True, slots=True, init=False)
class SelectedMeasurementValueAssembly:
    """Exact, disjoint pre-effect cover of required logical product uses."""

    _linked_points: MaterializedLinkedPointSet = field(repr=False)
    product_use_ids: tuple[ProductUseId, ...]
    fragments: tuple[SelectedMeasurementValueFragment, ...]
    linked_contract_fingerprint: str
    contract_fingerprint: str
    _fragment_by_id: Mapping[str, SelectedMeasurementValueFragment] = field(
        repr=False,
        compare=False,
        hash=False,
    )
    _use_by_id: Mapping[ProductUseId, ProductUse] = field(
        repr=False,
        compare=False,
        hash=False,
    )
    _product_by_use_id: Mapping[ProductUseId, ProductDef] = field(
        repr=False,
        compare=False,
        hash=False,
    )
    _point_by_id: Mapping[LogicalPointId, MaterializedPoint] = field(
        repr=False,
        compare=False,
        hash=False,
    )

    def __init__(
        self,
        linked_points: MaterializedLinkedPointSet,
        product_use_ids: tuple[ProductUseId, ...],
        fragments: tuple[SelectedMeasurementValueFragment, ...],
        linked_contract_fingerprint: str,
        contract_fingerprint: str,
        use_by_id: Mapping[ProductUseId, ProductUse],
        product_by_use_id: Mapping[ProductUseId, ProductDef],
        point_by_id: Mapping[LogicalPointId, MaterializedPoint],
    ) -> None:
        object.__setattr__(self, "_linked_points", linked_points)
        object.__setattr__(self, "product_use_ids", product_use_ids)
        object.__setattr__(self, "fragments", fragments)
        object.__setattr__(
            self,
            "linked_contract_fingerprint",
            linked_contract_fingerprint,
        )
        object.__setattr__(self, "contract_fingerprint", contract_fingerprint)
        object.__setattr__(
            self,
            "_fragment_by_id",
            MappingProxyType({fragment.id: fragment for fragment in fragments}),
        )
        object.__setattr__(
            self,
            "_use_by_id",
            MappingProxyType(dict(use_by_id)),
        )
        object.__setattr__(
            self,
            "_product_by_use_id",
            MappingProxyType(
                {
                    use_id: product.model_copy(deep=True)
                    for use_id, product in product_by_use_id.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "_point_by_id",
            MappingProxyType(dict(point_by_id)),
        )

    @property
    def linked_points(self) -> MaterializedLinkedPointSet:
        return self._linked_points

    def fragment(self, fragment_id: str) -> SelectedMeasurementValueFragment:
        try:
            return self._fragment_by_id[fragment_id]
        except KeyError as error:
            msg = f"measurement value fragment {fragment_id!r} is not selected"
            raise KeyError(msg) from error

    def product_use(self, product_use_id: ProductUseId) -> ProductUse:
        try:
            return self._use_by_id[product_use_id]
        except KeyError as error:
            msg = f"product use {product_use_id.value!r} is not selected"
            raise KeyError(msg) from error

    def product_for_use(self, product_use_id: ProductUseId) -> ProductDef:
        try:
            return self._product_by_use_id[product_use_id].model_copy(deep=True)
        except KeyError as error:
            msg = f"product use {product_use_id.value!r} is not selected"
            raise KeyError(msg) from error

    def point(self, logical_point_id: LogicalPointId) -> MaterializedPoint:
        try:
            return self._point_by_id[logical_point_id]
        except KeyError as error:
            msg = f"logical point {logical_point_id.value!r} is not selected"
            raise KeyError(msg) from error


@dataclass(frozen=True, slots=True, init=False)
class BoundDomainMeasurementValueFragment[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
]:
    """Pre-effect proof that one domain mapping can discharge a fragment."""

    selection: SelectedMeasurementValueAssembly = field(repr=False)
    fragment_id: str
    domain_outputs: SelectedDomainMeasurementOutputs[
        EntryAddressT,
        ResultAddressT,
    ] = field(repr=False)
    result_contract_fingerprint: str

    def __init__(
        self,
        selection: SelectedMeasurementValueAssembly,
        fragment_id: str,
        domain_outputs: SelectedDomainMeasurementOutputs[
            EntryAddressT,
            ResultAddressT,
        ],
        result_contract_fingerprint: str,
    ) -> None:
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "fragment_id", fragment_id)
        object.__setattr__(self, "domain_outputs", domain_outputs)
        object.__setattr__(
            self,
            "result_contract_fingerprint",
            result_contract_fingerprint,
        )


@dataclass(frozen=True, slots=True)
class MeasurementValueCandidate:
    """Producer candidate keyed only by logical point and product-use identity."""

    logical_point_id: LogicalPointId
    product_use_id: ProductUseId
    value: MeasurementValue

    def __post_init__(self) -> None:
        if not isinstance(cast("object", self.logical_point_id), LogicalPointId):
            msg = "measurement value candidates require a LogicalPointId"
            raise TypeError(msg)
        if not isinstance(cast("object", self.product_use_id), ProductUseId):
            msg = "measurement value candidates require a ProductUseId"
            raise TypeError(msg)
        if not _is_measurement_value(cast("object", self.value)):
            msg = "measurement value candidates require a MeasurementValue"
            raise TypeError(msg)


@dataclass(frozen=True, slots=True, init=False)
class ClosedMeasurementProductValue:
    """One checked host value with producer-neutral logical identity."""

    fragment_id: str = field(compare=False)
    point: MaterializedPoint = field(repr=False)
    product_use: ProductUse = field(repr=False)
    _product: ProductDef = field(repr=False)
    _value: MeasurementValue = field(repr=False)

    def __init__(
        self,
        fragment_id: str,
        point: MaterializedPoint,
        product_use: ProductUse,
        product: ProductDef,
        value: MeasurementValue,
    ) -> None:
        object.__setattr__(self, "fragment_id", fragment_id)
        object.__setattr__(self, "point", point)
        object.__setattr__(self, "product_use", product_use)
        object.__setattr__(self, "_product", product.model_copy(deep=True))
        object.__setattr__(self, "_value", validated_measurement_value_copy(value))

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
        return self._product.model_copy(deep=True)

    @property
    def value(self) -> MeasurementValue:
        return validated_measurement_value_copy(self._value)


@dataclass(frozen=True, slots=True, init=False)
class ClosedMeasurementValueFragment:
    """Exact runtime values for one preselected fragment."""

    selection: SelectedMeasurementValueAssembly = field(repr=False)
    fragment_id: str
    fragment_contract_fingerprint: str
    values: tuple[ClosedMeasurementProductValue, ...]

    def __init__(
        self,
        selection: SelectedMeasurementValueAssembly,
        fragment_id: str,
        fragment_contract_fingerprint: str,
        values: tuple[ClosedMeasurementProductValue, ...],
    ) -> None:
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "fragment_id", fragment_id)
        object.__setattr__(
            self,
            "fragment_contract_fingerprint",
            fragment_contract_fingerprint,
        )
        object.__setattr__(self, "values", values)

    def value_for_output(
        self,
        logical_point_id: LogicalPointId,
        product_use_id: ProductUseId,
    ) -> ClosedMeasurementProductValue:
        """Return one closed value by producer-neutral logical identity."""

        for value in self.values:
            if (
                value.logical_point_id == logical_point_id
                and value.product_use_id == product_use_id
            ):
                return value
        msg = (
            f"closed measurement fragment {self.fragment_id!r} has no output for "
            f"point {logical_point_id.value!r}, use {product_use_id.value!r}"
        )
        raise KeyError(msg)


@dataclass(frozen=True, slots=True, init=False)
class ClosedMeasurementProductValues:
    """Canonical producer-neutral values for every required point/use pair."""

    selection: SelectedMeasurementValueAssembly = field(repr=False)
    values: tuple[ClosedMeasurementProductValue, ...]
    _by_output: Mapping[
        tuple[LogicalPointId, ProductUseId],
        ClosedMeasurementProductValue,
    ] = field(repr=False, compare=False, hash=False)

    def __init__(
        self,
        selection: SelectedMeasurementValueAssembly,
        values: tuple[ClosedMeasurementProductValue, ...],
    ) -> None:
        by_output = {
            (value.logical_point_id, value.product_use_id): value for value in values
        }
        object.__setattr__(self, "selection", selection)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "_by_output", MappingProxyType(by_output))

    @property
    def product_use_ids(self) -> tuple[ProductUseId, ...]:
        return self.selection.product_use_ids

    def value_for_output(
        self,
        logical_point_id: LogicalPointId,
        product_use_id: ProductUseId,
    ) -> ClosedMeasurementProductValue:
        try:
            return self._by_output[(logical_point_id, product_use_id)]
        except KeyError as error:
            msg = (
                "assembled measurement values have no output for point "
                f"{logical_point_id.value!r}, use {product_use_id.value!r}"
            )
            raise KeyError(msg) from error


def select_measurement_value_assembly(
    linked_points: MaterializedLinkedPointSet,
    *,
    required_product_use_ids: Sequence[ProductUseId],
    fragment_defs: Sequence[ProductValueFragmentDef],
) -> SelectedMeasurementValueAssembly:
    """Seal an exact, disjoint fragment cover before any producer effect."""

    if not isinstance(
        cast("object", linked_points),
        MaterializedLinkedPoints | MaterializedLinkedPointBatch,
    ):
        msg = "measurement value assembly requires materialized linked points"
        raise TypeError(msg)
    required = tuple(required_product_use_ids)
    if any(not isinstance(cast("object", use_id), ProductUseId) for use_id in required):
        msg = "required measurement values require ProductUseId values"
        raise TypeError(msg)
    definitions = tuple(fragment_defs)
    if any(
        not isinstance(cast("object", definition), ProductValueFragmentDef)
        for definition in definitions
    ):
        msg = "measurement value assembly requires ProductValueFragmentDef values"
        raise TypeError(msg)

    all_uses, product_by_use_id = _measurement_product_inventory(linked_points)
    all_use_by_id = {use.id: use for use in all_uses}
    all_use_index = {use.id: index for index, use in enumerate(all_uses)}
    required_set = set(required)
    problems: list[Problem] = []

    for use_id, count in Counter(required).items():
        if count > 1:
            problems.append(
                _selection_problem(
                    "measurement_value_required_use_duplicate",
                    f"required product use {use_id.value!r} is repeated",
                    path=("required_product_use_ids",),
                    category=ProblemCategory.CONFLICT,
                )
            )
    for index, use_id in enumerate(required):
        if use_id not in all_use_by_id:
            problems.append(
                _selection_problem(
                    "measurement_value_required_use_unknown",
                    f"required product use {use_id.value!r} is not in the plan",
                    path=("required_product_use_ids", index),
                    category=ProblemCategory.NOT_FOUND,
                )
            )

    for use_id in required_set & set(all_use_by_id):
        product = product_by_use_id[use_id]
        problems.extend(_carrier_selection_problems(use_id, product))

    fragment_id_counts = Counter(definition.id for definition in definitions)
    for fragment_id, count in fragment_id_counts.items():
        if count > 1:
            problems.append(
                _selection_problem(
                    "measurement_value_fragment_id_duplicate",
                    f"measurement value fragment id {fragment_id!r} is repeated",
                    path=("fragment_defs",),
                    category=ProblemCategory.CONFLICT,
                )
            )

    owner_by_use: dict[ProductUseId, tuple[str, int]] = {}
    canonical_by_definition: list[
        tuple[ProductValueFragmentDef, tuple[ProductUseId, ...]]
    ] = []
    for definition_index, definition in enumerate(definitions):
        selected_ids = tuple(definition.product_use_ids)
        for use_id, count in Counter(selected_ids).items():
            if count > 1:
                problems.append(
                    _selection_problem(
                        "measurement_value_fragment_use_duplicate",
                        f"fragment {definition.id!r} repeats use {use_id.value!r}",
                        path=("fragment_defs", definition_index, "product_use_ids"),
                        category=ProblemCategory.CONFLICT,
                    )
                )
        for use_index, use_id in enumerate(selected_ids):
            if use_id not in all_use_by_id:
                problems.append(
                    _selection_problem(
                        "measurement_value_fragment_use_unknown",
                        f"fragment {definition.id!r} owns unknown use {use_id.value!r}",
                        path=(
                            "fragment_defs",
                            definition_index,
                            "product_use_ids",
                            use_index,
                        ),
                        category=ProblemCategory.NOT_FOUND,
                    )
                )
                continue
            if use_id not in required_set:
                problems.append(
                    _selection_problem(
                        "measurement_value_fragment_use_unexpected",
                        f"fragment {definition.id!r} owns unrequired use "
                        f"{use_id.value!r}",
                        path=(
                            "fragment_defs",
                            definition_index,
                            "product_use_ids",
                            use_index,
                        ),
                        category=ProblemCategory.CONFLICT,
                    )
                )
            existing = owner_by_use.get(use_id)
            if existing is not None and existing[0] != definition.id:
                problems.append(
                    _selection_problem(
                        "measurement_value_fragment_overlap",
                        f"product use {use_id.value!r} is owned by fragments "
                        f"{existing[0]!r} and {definition.id!r}",
                        path=(
                            "fragment_defs",
                            definition_index,
                            "product_use_ids",
                            use_index,
                        ),
                        category=ProblemCategory.CONFLICT,
                    )
                )
            elif existing is None:
                owner_by_use[use_id] = (definition.id, definition_index)
        canonical_ids = tuple(use.id for use in all_uses if use.id in set(selected_ids))
        canonical_by_definition.append((definition, canonical_ids))

    for use_id in required:
        if use_id in all_use_by_id and use_id not in owner_by_use:
            problems.append(
                _selection_problem(
                    "measurement_value_fragment_coverage_missing",
                    f"required product use {use_id.value!r} has no fragment owner",
                    path=("required_product_use_ids",),
                    category=ProblemCategory.NOT_FOUND,
                )
            )
    if problems:
        raise CheckFailed(problems)

    canonical_required = tuple(use.id for use in all_uses if use.id in required_set)
    linked_fingerprint = measurement_value_contract_fingerprint(linked_points)
    selected_fragments = tuple(
        sorted(
            (
                SelectedMeasurementValueFragment(
                    definition.id,
                    canonical_ids,
                    _fragment_contract_fingerprint(
                        linked_fingerprint,
                        definition.id,
                        canonical_ids,
                    ),
                )
                for definition, canonical_ids in canonical_by_definition
            ),
            key=lambda fragment: (
                min(
                    (all_use_index[use_id] for use_id in fragment.product_use_ids),
                    default=len(all_use_index),
                ),
                fragment.id,
            ),
        )
    )
    assembly_fingerprint = _assembly_contract_fingerprint(
        linked_fingerprint,
        canonical_required,
        selected_fragments,
    )
    return SelectedMeasurementValueAssembly(
        linked_points,
        canonical_required,
        selected_fragments,
        linked_fingerprint,
        assembly_fingerprint,
        {use_id: all_use_by_id[use_id] for use_id in canonical_required},
        {use_id: product_by_use_id[use_id] for use_id in canonical_required},
        {point.logical_id: point for point in linked_points.point_domain.points},
    )


def seal_measurement_value_fragment(
    selection: SelectedMeasurementValueAssembly,
    fragment_id: str,
    candidates: Sequence[MeasurementValueCandidate],
) -> ClosedMeasurementValueFragment:
    """Close exact runtime values for one preselected producer fragment."""

    selected = require_measurement_value_assembly(selection)
    fragment = selected.fragment(fragment_id)
    supplied = tuple(candidates)
    if any(
        not isinstance(cast("object", candidate), MeasurementValueCandidate)
        for candidate in supplied
    ):
        msg = "measurement value fragment requires MeasurementValueCandidate values"
        raise TypeError(msg)

    points = selected.linked_points.point_domain.points
    expected_keys = {
        (point.logical_id, use_id)
        for point in points
        for use_id in fragment.product_use_ids
    }
    point_ids = {point.logical_id for point in points}
    owned_use_ids = set(fragment.product_use_ids)
    by_key: dict[
        tuple[LogicalPointId, ProductUseId],
        MeasurementValueCandidate,
    ] = {}
    first_index: dict[tuple[LogicalPointId, ProductUseId], int] = {}
    problems: list[Problem] = []
    for candidate_index, candidate in enumerate(supplied):
        key = (candidate.logical_point_id, candidate.product_use_id)
        if key in by_key:
            problems.append(
                _value_problem(
                    "measurement_value_fragment_duplicate",
                    "measurement value fragment repeats one logical point/use",
                    path=("candidates", candidate_index),
                    details={"first_candidate_index": first_index[key]},
                )
            )
            continue
        by_key[key] = candidate
        first_index[key] = candidate_index
        if candidate.logical_point_id not in point_ids:
            problems.append(
                _value_problem(
                    "measurement_value_fragment_point_unknown",
                    "measurement value fragment references a foreign logical point",
                    path=("candidates", candidate_index, "logical_point_id"),
                )
            )
        if candidate.product_use_id not in owned_use_ids:
            problems.append(
                _value_problem(
                    "measurement_value_fragment_use_unknown",
                    "measurement value fragment references a use it does not own",
                    path=("candidates", candidate_index, "product_use_id"),
                )
            )
        if key not in expected_keys:
            continue
        product = selected.product_for_use(candidate.product_use_id)
        problems.extend(
            _measurement_contract_problems(
                candidate.value,
                product=product,
                candidate_index=candidate_index,
                logical_point_id=candidate.logical_point_id,
                product_use_id=candidate.product_use_id,
            )
        )

    for point in points:
        for use_id in fragment.product_use_ids:
            if (point.logical_id, use_id) in by_key:
                continue
            problems.append(
                _value_problem(
                    "measurement_value_fragment_output_missing",
                    "measurement value fragment is missing one logical point/use",
                    path=("outputs", point.logical_ordinal, use_id.value),
                    details={
                        "logical_point_id": point.logical_id.value,
                        "product_use_id": use_id.value,
                    },
                )
            )
    if problems:
        raise ProviderContractError(problems)

    values = tuple(
        ClosedMeasurementProductValue(
            fragment.id,
            point,
            selected.product_use(use_id),
            selected.product_for_use(use_id),
            by_key[(point.logical_id, use_id)].value,
        )
        for point in points
        for use_id in fragment.product_use_ids
    )
    return ClosedMeasurementValueFragment(
        selected,
        fragment.id,
        fragment.contract_fingerprint,
        values,
    )


def bind_domain_output_fragment[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    selection: SelectedMeasurementValueAssembly,
    fragment_id: str,
    domain_outputs: SelectedDomainMeasurementOutputs[
        EntryAddressT,
        ResultAddressT,
    ],
) -> BoundDomainMeasurementValueFragment[EntryAddressT, ResultAddressT]:
    """Bind a real domain result/carrier proof to one fragment before effects."""

    selected = require_measurement_value_assembly(selection)
    if not isinstance(
        cast("object", domain_outputs),
        SelectedDomainMeasurementOutputs,
    ):
        msg = "domain fragment binding requires SelectedDomainMeasurementOutputs"
        raise TypeError(msg)
    normalized_outputs = domain_outputs
    fragment = selected.fragment(fragment_id)
    problems: list[Problem] = []
    if (
        measurement_value_contract_fingerprint(normalized_outputs.mapping.linked_points)
        != selected.linked_contract_fingerprint
    ):
        problems.append(
            _selection_problem(
                "domain_measurement_fragment_contract_mismatch",
                "domain output selection belongs to a different logical contract",
                path=("fragments", fragment_id, "domain_outputs"),
                category=ProblemCategory.CONFLICT,
            )
        )
    if (
        tuple(normalized_outputs.mapping.selected_product_use_ids)
        != fragment.product_use_ids
    ):
        problems.append(
            _selection_problem(
                "domain_measurement_fragment_ownership_mismatch",
                "domain output selection does not exactly own this fragment",
                path=("fragments", fragment_id, "product_use_ids"),
                category=ProblemCategory.CONFLICT,
            )
        )
    if problems:
        raise CheckFailed(problems)
    result_fingerprint = normalized_outputs.mapping.contract_fingerprint
    return BoundDomainMeasurementValueFragment(
        selected,
        fragment.id,
        normalized_outputs,
        result_fingerprint,
    )


def domain_output_fragment[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    binding: BoundDomainMeasurementValueFragment[
        EntryAddressT,
        ResultAddressT,
    ],
    outputs: ClosedDomainOutputValues[EntryAddressT, ResultAddressT],
) -> ClosedMeasurementValueFragment:
    """Adapt bound, closed domain values into the producer-neutral data plane."""

    bound = _require_bound_domain_fragment(binding)
    if not isinstance(cast("object", outputs), ClosedDomainOutputValues):
        msg = "domain measurement ingress requires ClosedDomainOutputValues"
        raise TypeError(msg)
    if outputs.mapping.contract_fingerprint != bound.result_contract_fingerprint:
        raise ProviderContractError(
            (
                _value_problem(
                    "domain_measurement_fragment_result_contract_mismatch",
                    "closed domain values do not belong to the bound result contract",
                    path=("domain_outputs",),
                ),
            )
        )
    return seal_measurement_value_fragment(
        bound.selection,
        bound.fragment_id,
        tuple(
            MeasurementValueCandidate(
                logical_point_id=output.logical_point_id,
                product_use_id=output.product_use_id,
                value=output.value,
            )
            for output in outputs.outputs
        ),
    )


def assemble_measurement_values(
    selection: SelectedMeasurementValueAssembly,
    fragments: Sequence[ClosedMeasurementValueFragment],
) -> ClosedMeasurementProductValues:
    """Assemble selected fragments in canonical point/linked-use order."""

    selected = require_measurement_value_assembly(selection)
    supplied = tuple(fragments)
    if any(
        not isinstance(cast("object", fragment), ClosedMeasurementValueFragment)
        for fragment in supplied
    ):
        msg = "measurement value assembly requires closed fragments"
        raise TypeError(msg)

    expected_by_id = {fragment.id: fragment for fragment in selected.fragments}
    by_id: dict[str, ClosedMeasurementValueFragment] = {}
    problems: list[Problem] = []
    for fragment_index, fragment in enumerate(supplied):
        if fragment.fragment_id in by_id:
            problems.append(
                _value_problem(
                    "measurement_value_fragment_repeated",
                    f"closed fragment {fragment.fragment_id!r} is repeated",
                    path=("fragments", fragment_index),
                )
            )
            continue
        by_id[fragment.fragment_id] = fragment
        if fragment.fragment_id not in expected_by_id:
            problems.append(
                _value_problem(
                    "measurement_value_fragment_unexpected",
                    f"closed fragment {fragment.fragment_id!r} is not selected",
                    path=("fragments", fragment_index),
                )
            )

    closed_by_id: dict[str, ClosedMeasurementValueFragment] = {}
    for expected in selected.fragments:
        fragment = by_id.get(expected.id)
        if fragment is None:
            problems.append(
                _value_problem(
                    "measurement_value_fragment_missing",
                    f"selected fragment {expected.id!r} has no runtime values",
                    path=("fragments", expected.id),
                )
            )
            continue
        if (
            fragment.selection.contract_fingerprint != selected.contract_fingerprint
            or fragment.fragment_contract_fingerprint != expected.contract_fingerprint
        ):
            problems.append(
                _value_problem(
                    "measurement_value_fragment_contract_mismatch",
                    f"closed fragment {expected.id!r} belongs to another selection",
                    path=("fragments", expected.id),
                )
            )
            continue
        closed_by_id[expected.id] = fragment
    if problems:
        raise ProviderContractError(problems)

    value_by_key = {
        (value.logical_point_id, value.product_use_id): value
        for fragment in closed_by_id.values()
        for value in fragment.values
    }
    values = tuple(
        value_by_key[(point.logical_id, use_id)]
        for point in selected.linked_points.point_domain.points
        for use_id in selected.product_use_ids
    )
    return ClosedMeasurementProductValues(
        selected,
        values,
    )


def _require_bound_domain_fragment[
    EntryAddressT: Hashable,
    ResultAddressT: Hashable,
](
    binding: BoundDomainMeasurementValueFragment[
        EntryAddressT,
        ResultAddressT,
    ],
) -> BoundDomainMeasurementValueFragment[EntryAddressT, ResultAddressT]:
    if not isinstance(
        cast("object", binding),
        BoundDomainMeasurementValueFragment,
    ):
        msg = "domain measurement ingress requires a bound domain fragment"
        raise TypeError(msg)
    return binding


def require_assembled_measurement_values(
    values: ClosedMeasurementProductValues,
) -> ClosedMeasurementProductValues:
    """Require the closed stage produced by measurement value assembly."""

    if not isinstance(cast("object", values), ClosedMeasurementProductValues):
        msg = "measurement projection requires ClosedMeasurementProductValues"
        raise TypeError(msg)
    return values


def require_measurement_value_fragment(
    fragment: ClosedMeasurementValueFragment,
) -> ClosedMeasurementValueFragment:
    """Require the closed stage produced by measurement fragment sealing."""

    if not isinstance(cast("object", fragment), ClosedMeasurementValueFragment):
        msg = "measurement fragments require ClosedMeasurementValueFragment"
        raise TypeError(msg)
    return fragment


def require_measurement_value_assembly(
    selection: SelectedMeasurementValueAssembly,
) -> SelectedMeasurementValueAssembly:
    """Require the selected stage produced by measurement value selection."""

    if not isinstance(cast("object", selection), SelectedMeasurementValueAssembly):
        msg = "measurement values require SelectedMeasurementValueAssembly"
        raise TypeError(msg)
    return selection


def _measurement_product_inventory(
    linked_points: MaterializedLinkedPointSet,
) -> tuple[tuple[ProductUse, ...], dict[ProductUseId, ProductDef]]:
    linked_plan = linked_points.linked_plan
    uses = tuple(linked_plan.product_uses)
    products_by_id = {product.id: product for product in linked_plan.product_defs}
    try:
        products = {
            use.id: products_by_id[use.product_id].model_copy(deep=True) for use in uses
        }
    except KeyError as error:
        msg = "measurement value assembly requires a closed product graph"
        raise ValueError(msg) from error
    return uses, products


def measurement_value_contract_fingerprint(
    linked_points: MaterializedLinkedPointSet,
) -> str:
    """Identify one transient point/use/product contract independent of objects."""

    uses, products = _measurement_product_inventory(linked_points)
    return stable_content_hash(
        content_fingerprint(
            {
                "schema": "scopecat.measurement_value_contract.v1",
                "points": [
                    {
                        "logical_point_id": point.logical_id.value,
                        "row": point.row,
                        "row_key": point.row_key,
                    }
                    for point in linked_points.point_domain.points
                ],
                "product_uses": [
                    {
                        "product_use_id": use.id.value,
                        "product_id": use.product_id.qualified_name,
                        "product": products[use.id],
                    }
                    for use in uses
                ],
            }
        )
    )


def _fragment_contract_fingerprint(
    linked_fingerprint: str,
    fragment_id: str,
    product_use_ids: Sequence[ProductUseId],
) -> str:
    return stable_content_hash(
        {
            "schema": "scopecat.measurement_value_fragment_contract.v1",
            "linked_contract_fingerprint": linked_fingerprint,
            "fragment_id": fragment_id,
            "product_use_ids": [use_id.value for use_id in product_use_ids],
        }
    )


def _assembly_contract_fingerprint(
    linked_fingerprint: str,
    product_use_ids: Sequence[ProductUseId],
    fragments: Sequence[SelectedMeasurementValueFragment],
) -> str:
    return stable_content_hash(
        {
            "schema": "scopecat.measurement_value_assembly_contract.v1",
            "linked_contract_fingerprint": linked_fingerprint,
            "product_use_ids": [use_id.value for use_id in product_use_ids],
            "fragments": [
                {
                    "id": fragment.id,
                    "contract_fingerprint": fragment.contract_fingerprint,
                }
                for fragment in fragments
            ],
        }
    )


def _carrier_selection_problems(
    use_id: ProductUseId,
    product: ProductDef,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    details = {
        "product_use_id": use_id.value,
        "product_id": product.id.qualified_name,
    }
    if product.kind != "observable":
        problems.append(
            _selection_problem(
                "measurement_value_product_kind_unsupported",
                f"measurement value assembly cannot carry {product.kind!r} products",
                path=("product_uses", use_id.value, "product", "kind"),
                details={**details, "actual": product.kind},
            )
        )
    if not product.axes and product.dtype in {"bool", "string"}:
        problems.append(
            _selection_problem(
                "measurement_value_scalar_dtype_unsupported",
                f"measurement value assembly has no scalar {product.dtype!r} carrier",
                path=("product_uses", use_id.value, "product", "dtype"),
                details={**details, "actual": product.dtype},
            )
        )
    return tuple(problems)


def _measurement_contract_problems(
    value: MeasurementValue,
    *,
    product: ProductDef,
    candidate_index: int,
    logical_point_id: LogicalPointId,
    product_use_id: ProductUseId,
) -> tuple[Problem, ...]:
    problems: list[Problem] = []
    for issue in measurement_value_contract_issues(
        value,
        expected_dtype=product.dtype,
        expected_unit=product.unit,
        expected_shape=tuple(axis.size for axis in product.axes),
    ):
        problems.append(
            _value_problem(
                f"measurement_value_{issue.code.value}",
                "measurement value does not satisfy its logical product contract",
                path=("candidates", candidate_index, *issue.path),
                details={
                    "logical_point_id": logical_point_id.value,
                    "product_use_id": product_use_id.value,
                    "product_id": product.id.qualified_name,
                    "expected": _problem_detail(issue.expected),
                    "actual": _problem_detail(issue.actual),
                },
            )
        )
    return tuple(problems)


def _selection_problem(
    code: str,
    message: str,
    *,
    path: tuple[str | int, ...],
    category: ProblemCategory = ProblemCategory.INVALID_INPUT,
    details: Mapping[str, object] | None = None,
) -> Problem:
    return compiler_problem(
        code,
        message,
        model_location("measurement_value_assembly", *path),
        category=category,
        details=details,
    )


def _value_problem(
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
        location=model_location("measurement_value_fragment", *path),
        details=details,
    )


def _problem_detail(value: object) -> JsonValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, tuple):
        selected = cast("tuple[object, ...]", value)
        return [_problem_detail(item) for item in selected]
    return repr(value)


def _is_measurement_value(value: object) -> bool:
    return isinstance(value, Quantity | ComplexQuantity | MeasurementArray)


__all__ = [
    "BoundDomainMeasurementValueFragment",
    "ClosedMeasurementProductValue",
    "ClosedMeasurementProductValues",
    "ClosedMeasurementValueFragment",
    "MeasurementValueCandidate",
    "ProductValueFragmentDef",
    "SelectedMeasurementValueAssembly",
    "SelectedMeasurementValueFragment",
    "assemble_measurement_values",
    "bind_domain_output_fragment",
    "domain_output_fragment",
    "measurement_value_contract_fingerprint",
    "require_assembled_measurement_values",
    "require_measurement_value_assembly",
    "require_measurement_value_fragment",
    "seal_measurement_value_fragment",
    "select_measurement_value_assembly",
]
