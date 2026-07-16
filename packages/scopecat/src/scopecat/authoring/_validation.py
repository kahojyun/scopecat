"""Config-free validation for experiment templates and invocations.

This module deliberately depends only on source authoring handles.  It keeps
template-shape and closed-literal checks ahead of config validation and the
config-dependent assembly linker.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Protocol

from scopecat.authoring._module_handles import ExperimentModule
from scopecat.authoring._module_ir import ModuleIR
from scopecat.authoring._problems import authoring_problem as problem
from scopecat.authoring._record_intents import RecordSelection
from scopecat.authoring._scan_intents import (
    ParameterScanIntent,
    PointScanIntent,
    Scan,
    ScanGroupIntent,
    iter_scan_leaves,
    scan_point_id,
)
from scopecat.authoring._value_refs import (
    ValueRef,
    internal_value_ref_availability,
    internal_value_ref_input_id,
)
from scopecat.authoring.domain import DomainExecution
from scopecat.compiler.semantic.availability import (
    ValueAvailabilityError,
    ValueStage,
    require_value_availability,
)
from scopecat.kernel.errors import CheckFailed
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemPhase,
    model_location,
)
from scopecat.kernel.product_identity import ProductId
from scopecat.kernel.value_type_compatibility import is_assignable
from scopecat.kernel.value_types import ValueType
from scopecat.kernel.value_validation import ValueValidationError, validate_literal


class TemplateInputDescription(Protocol):
    """The fields needed from the public ``InputDescription`` value."""

    @property
    def id(self) -> str: ...

    @property
    def default(self) -> object: ...

    @property
    def has_default(self) -> bool: ...


def validate_template_definition(
    *,
    module: ExperimentModule,
    domain_execution: DomainExecution | None,
    inputs: Sequence[TemplateInputDescription],
    default_scans: Sequence[Scan],
    record_selections: Sequence[RecordSelection],
) -> None:
    """Validate one closed template definition without consulting config."""

    problems: list[Problem] = []
    input_types, input_type_problems = _template_input_types(
        module,
        default_scans,
    )
    problems.extend(input_type_problems)
    problems.extend(_validate_input_descriptions(inputs, input_types))
    problems.extend(_validate_default_scans(default_scans, input_types))
    problems.extend(_validate_record_selections(module, record_selections))
    problems.extend(_validate_domain_execution(module, domain_execution))
    _raise_problems(problems, phase=ProblemPhase.DEFINITION)


def validate_template_bound_inputs(
    *,
    module: ExperimentModule,
    descriptions: Sequence[TemplateInputDescription],
    default_scans: Sequence[Scan],
    inputs: Mapping[str, object],
) -> None:
    """Reject known invocation input errors while leaving missing values open."""

    input_types, type_problems = _template_input_types(module, default_scans)
    allowed = {description.id for description in descriptions} | {
        port.id for port in module.ir.interface.imports
    }
    unknown = sorted(set(inputs) - allowed)
    problems = list(type_problems)
    if unknown:
        problems.append(
            problem(
                "experiment_template_unknown_input",
                "experiment template received unknown input: " + ", ".join(unknown),
                "template",
                path=("inputs",),
            )
        )
    problems.extend(
        _literal_type_problems(
            inputs,
            input_types,
            location=model_location("inputs"),
        )
    )
    _raise_problems(problems)


def validate_invocation_scans(
    scans: Sequence[Scan],
) -> None:
    """Check invocation scan values before semantic or relation lowering."""

    problems = _scan_availability_problems(
        scans,
        location=model_location("scans"),
    )
    for index, scan in enumerate(scans):
        problems.extend(
            _scan_length_problems(
                scan,
                location=model_location("scans", index),
            )[1]
        )
    _raise_problems(problems)


def _template_input_types(
    module: ExperimentModule,
    default_scans: Sequence[Scan],
) -> tuple[dict[str, ValueType], list[Problem]]:
    selected = {port.id: port.value_type for port in module.ir.interface.imports}
    problems: list[Problem] = []

    for scan in default_scans:
        for leaf in iter_scan_leaves(scan):
            for input_id, value_type in _direct_scan_input_types(leaf):
                existing = selected.get(input_id)
                if existing is None or is_assignable(value_type, existing):
                    selected[input_id] = value_type
                elif not is_assignable(existing, value_type):
                    problems.append(
                        problem(
                            "module_input_type_conflict",
                            f"template input {input_id} has incompatible value types",
                            "inputs",
                            path=(input_id,),
                        )
                    )
    return selected, problems


def _direct_scan_input_types(
    scan: PointScanIntent | ParameterScanIntent,
) -> tuple[tuple[str, ValueType], ...]:
    selected: list[tuple[str, ValueType]] = []
    values: tuple[object, ...]
    if isinstance(scan, PointScanIntent):
        values = () if scan.center is None else (scan.center,)
        if scan.implicit_center:
            selected.append((scan.point_id, scan.target.value_type))
    else:
        values = tuple(value for _name, value in scan.key)
    for value in values:
        if not isinstance(value, ValueRef):
            continue
        input_id = internal_value_ref_input_id(value)
        if input_id is not None:
            selected.append((input_id, value.value_type))
    return tuple(selected)


def _validate_input_descriptions(
    descriptions: Sequence[TemplateInputDescription],
    input_types: Mapping[str, ValueType],
) -> list[Problem]:
    problems: list[Problem] = []
    duplicate_ids = _duplicates(description.id for description in descriptions)
    if duplicate_ids:
        problems.append(
            problem(
                "experiment_template_input_duplicate",
                "experiment template defines duplicate inputs: "
                + ", ".join(duplicate_ids),
                "template",
                path=("inputs",),
            )
        )
    defaults = {
        description.id: description.default
        for description in descriptions
        if description.has_default and description.id not in duplicate_ids
    }
    problems.extend(
        _literal_type_problems(
            defaults,
            input_types,
            location=model_location("template", "inputs"),
            path_suffix=("default",),
        )
    )
    return problems


def _literal_type_problems(
    values: Mapping[str, object],
    input_types: Mapping[str, ValueType],
    *,
    location: ModelLocation,
    path_suffix: tuple[str | int, ...] = (),
) -> list[Problem]:
    problems: list[Problem] = []
    for input_id in sorted(set(values) & set(input_types)):
        value_location = model_location(
            location.root,
            *location.path,
            input_id,
            *path_suffix,
        )
        try:
            validate_literal(
                input_types[input_id],
                values[input_id],
                path=(value_location.root, *value_location.path),
            )
        except ValueValidationError as error:
            problems.append(
                problem(
                    "module_input_type_mismatch",
                    str(error),
                    value_location.root,
                    path=value_location.path,
                )
            )
    return problems


def _validate_default_scans(
    scans: Sequence[Scan],
    input_types: Mapping[str, ValueType],
) -> list[Problem]:
    problems: list[Problem] = []
    axis_ids = [
        scan_point_id(leaf) for scan in scans for leaf in iter_scan_leaves(scan)
    ]
    duplicate_axes = _duplicates(axis_ids)
    if duplicate_axes:
        problems.append(
            problem(
                "scan_axis_duplicate",
                "duplicate scan axis: " + ", ".join(duplicate_axes),
                "template",
                path=("default_scans",),
            )
        )

    problems.extend(
        _scan_availability_problems(
            scans,
            location=model_location("template", "default_scans"),
        )
    )

    for index, scan in enumerate(scans):
        problems.extend(
            _scan_length_problems(
                scan,
                location=model_location("template", "default_scans", index),
            )[1]
        )
        for leaf in iter_scan_leaves(scan):
            expected = input_types.get(scan_point_id(leaf))
            if expected is None or is_assignable(leaf.target.value_type, expected):
                continue
            input_id = scan_point_id(leaf)
            problems.append(
                problem(
                    "module_input_type_mismatch",
                    f"scan {input_id!r} has a value type incompatible with "
                    "the exposed module input",
                    "template",
                    path=("default_scans", input_id),
                )
            )
    return problems


def _scan_availability_problems(
    scans: Sequence[Scan],
    *,
    location: ModelLocation,
) -> list[Problem]:
    problems: list[Problem] = []
    for index, scan in enumerate(scans):
        _scan_value_availability_problems(
            scan,
            location=model_location(location.root, *location.path, index),
            problems=problems,
        )
    return problems


def _scan_value_availability_problems(
    scan: Scan,
    *,
    location: ModelLocation,
    problems: list[Problem],
) -> None:
    if isinstance(scan, ScanGroupIntent):
        for index, child in enumerate(scan.scans):
            _scan_value_availability_problems(
                child,
                location=model_location(
                    location.root,
                    *location.path,
                    "scans",
                    index,
                ),
                problems=problems,
            )
        return
    if isinstance(scan, PointScanIntent):
        values = () if scan.center is None else (("center", scan.center),)
        context = "scan center"
    elif isinstance(scan, ParameterScanIntent):
        values = scan.key
        context = "parameter scan key"
    else:
        return
    for value_id, value in values:
        if not isinstance(value, ValueRef):
            continue
        value_location = model_location(
            location.root,
            *location.path,
            value_id,
        )
        try:
            require_value_availability(
                internal_value_ref_availability(value),
                stages=(ValueStage.PLAN,),
                context=context,
                location=value_location,
            )
        except ValueAvailabilityError as error:
            problems.append(
                problem(
                    error.code,
                    str(error),
                    error.location.root,
                    path=error.location.path,
                )
            )


def _scan_length_problems(
    scan: Scan,
    *,
    location: ModelLocation,
) -> tuple[int, list[Problem]]:
    if isinstance(scan, PointScanIntent):
        return (
            len(scan.point_values) if scan.point_values else scan.point_count or 0,
            [],
        )
    if isinstance(scan, ParameterScanIntent):
        return len(scan.values), []
    if not isinstance(scan, ScanGroupIntent):
        return 0, []

    problems: list[Problem] = []
    lengths: list[int] = []
    for index, child in enumerate(scan.scans):
        length, child_problems = _scan_length_problems(
            child,
            location=model_location(
                location.root,
                *location.path,
                "scans",
                index,
            ),
        )
        lengths.append(length)
        problems.extend(child_problems)
    if scan.kind == "zip":
        if len(set(lengths)) != 1:
            problems.append(
                problem(
                    "scan_zip_length_mismatch",
                    "zip scan group requires scans with equal length; got "
                    + ", ".join(str(length) for length in lengths),
                    location.root,
                    path=location.path,
                )
            )
        return (lengths[0] if lengths else 0), problems
    length = 1
    for child_length in lengths:
        length *= child_length
    return length, problems


def _validate_record_selections(
    module: ExperimentModule,
    selections: Sequence[RecordSelection],
) -> list[Problem]:
    problems: list[Problem] = []
    products = module.ir.interface.products
    product_ids = [product.symbol_id for product in products]
    record_ids = _module_record_ids(module.ir)
    duplicate_products = {
        product_id for product_id in product_ids if product_ids.count(product_id) > 1
    }
    if duplicate_products:
        problems.append(
            problem(
                "module_product_duplicate",
                "experiment assembly defines duplicate products: "
                + ", ".join(sorted(item.qualified_name for item in duplicate_products)),
                "products",
            )
        )

    selected_product_ids = [selection.product_id for selection in selections]
    unknown_products = set(selected_product_ids) - set(product_ids)
    if unknown_products:
        problems.append(
            problem(
                "module_product_unknown",
                "experiment selects unknown products: "
                + ", ".join(sorted(item.qualified_name for item in unknown_products)),
                "records",
            )
        )
    product_origins_by_id: dict[ProductId, list[tuple[object, ...]]] = {}
    for product in products:
        product_origins_by_id.setdefault(product.symbol_id, []).append(
            product.target_origin
        )
    for selection in selections:
        if selection.product_origin is None:
            continue
        matching = product_origins_by_id.get(selection.product_id, ())
        if selection.product_origin in matching:
            continue
        if matching:
            problems.append(
                problem(
                    "module_product_foreign_instance",
                    "experiment selects product "
                    f"{selection.product_id.qualified_name!r} from "
                    "another module instance",
                    "records",
                )
            )
    selected_record_ids = [
        selection.record_id or selection.product_id.qualified_name
        for selection in selections
    ]
    duplicate_records = _duplicates((*record_ids, *selected_record_ids))
    if duplicate_records:
        problems.append(
            problem(
                "module_record_duplicate",
                "experiment assembly defines duplicate records: "
                + ", ".join(duplicate_records),
                "records",
            )
        )
    return problems


def _validate_domain_execution(
    module: ExperimentModule,
    execution: DomainExecution | None,
) -> list[Problem]:
    if execution is None:
        return []
    products_by_id: dict[ProductId, list[tuple[object, ...]]] = {}
    for product in module.ir.interface.products:
        products_by_id.setdefault(product.symbol_id, []).append(product.target_origin)
    problems: list[Problem] = []
    for result_id, product in execution.result_bindings:
        origins = products_by_id.get(product.product_id)
        if origins is None:
            problems.append(
                problem(
                    "domain_execution_product_unknown",
                    f"domain result {result_id!r} binds unknown product {product.id!r}",
                    "domain_execution",
                    path=("results", result_id),
                )
            )
        elif product.origin not in origins:
            problems.append(
                problem(
                    "domain_execution_product_foreign_instance",
                    f"domain result {result_id!r} binds product {product.id!r} "
                    "from another module instance",
                    "domain_execution",
                    path=("results", result_id),
                )
            )
    return problems


def _module_record_ids(module: ModuleIR) -> list[str]:
    record_ids: list[str] = []
    for instance in module.body.instances:
        record_ids.extend(_module_record_ids(instance.module))
    record_ids.extend(record.id for record in module.body.records)
    return record_ids


def _duplicates(values: Iterable[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def _raise_problems(
    problems: list[Problem],
    *,
    phase: ProblemPhase = ProblemPhase.AUTHORING,
) -> None:
    if problems:
        raise CheckFailed(
            [problem.model_copy(update={"phase": phase}) for problem in problems]
        )


__all__ = [
    "validate_invocation_scans",
    "validate_template_bound_inputs",
    "validate_template_definition",
]
