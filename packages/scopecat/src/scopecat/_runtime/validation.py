"""Runtime graph and instrument contract validation."""

from __future__ import annotations

from scopecat._runtime.graph import RuntimeGraph
from scopecat.diagnostics import Diagnostic, DiagnosticSeverity
from scopecat.experiments import ProductBinding
from scopecat.instruments.sdk import (
    InstrumentDescription,
    InstrumentDriver,
    InstrumentStateCommand,
    InstrumentStateCommandField,
    ProductDescription,
    validate_state_command,
)
from scopecat.models.artifact import CommandPayload
from scopecat.results import MeasurementValue
from scopecat.units import compatible_units


def runtime_graph_diagnostics(graph: RuntimeGraph) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for diagnostic in graph.diagnostics:
        diagnostics.append(Diagnostic.model_validate(diagnostic))
    return diagnostics


def validate_runtime_graph_instruments(
    *,
    graph: RuntimeGraph,
    instruments_by_id: dict[str, InstrumentDriver],
    descriptions: list[InstrumentDescription],
    payloads: dict[str, CommandPayload],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    description_by_id = {
        description.instrument_id: description for description in descriptions
    }
    resource_ids = sorted(
        {
            resource.resource_id
            for point in graph.points
            for resource in point.desired_state
        }
        | {
            binding.instrument_id
            for binding in _point_product_bindings(graph)
            if binding.instrument_id is not None
        }
    )
    missing_resource_ids: set[str] = set()
    for resource_id in resource_ids:
        if resource_id not in instruments_by_id:
            missing_resource_ids.add(resource_id)
            diagnostics.append(
                _diagnostic(
                    "error",
                    "missing_instrument",
                    f"no instrument provided for resource {resource_id}",
                    "desired_state_plan.resource_ids",
                )
            )
        elif resource_id not in description_by_id:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "missing_instrument_description",
                    f"instrument {resource_id} did not provide a description",
                    "instruments",
                )
            )
    for point in graph.points:
        for resource in point.desired_state:
            description = description_by_id.get(resource.resource_id)
            if description is None:
                continue
            diagnostics.extend(
                validate_state_command(
                    command=InstrumentStateCommand(
                        instrument_id=resource.resource_id,
                        fields=[
                            InstrumentStateCommandField(
                                resource_id=resource.resource_id,
                                capability_id=resource.capability_id,
                                field_path=field.field_path,
                                value=field.value,
                            )
                            for field in resource.fields
                        ],
                    ),
                    description=description,
                    payloads=payloads,
                )
            )
    diagnostics.extend(
        _validate_product_bindings(
            graph=graph,
            instruments_by_id=instruments_by_id,
            description_by_id=description_by_id,
            reported_missing_instrument_ids=missing_resource_ids,
        )
    )
    return diagnostics


def validate_point_outputs(
    *,
    point_index: int,
    expected_output_ids: set[str],
    observables: dict[str, MeasurementValue],
    diagnostics: list[Diagnostic],
) -> None:
    for output_id in sorted(expected_output_ids - set(observables)):
        diagnostics.append(
            _diagnostic(
                "error",
                "instrument_missing_output",
                f"point {point_index} is missing observable {output_id}",
                f"points.{point_index}.outputs.{output_id}",
            )
        )


def _validate_product_bindings(
    *,
    graph: RuntimeGraph,
    instruments_by_id: dict[str, InstrumentDriver],
    description_by_id: dict[str, InstrumentDescription],
    reported_missing_instrument_ids: set[str],
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for binding in _point_product_bindings(graph):
        if binding.instrument_id is None:
            descriptions = list(description_by_id.values())
            if not descriptions:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "missing_instrument",
                        f"no instrument provided for product {binding.product_key}",
                        f"product_bindings.{binding.record_id}",
                    )
                )
                continue
        else:
            if binding.instrument_id not in instruments_by_id:
                if binding.instrument_id in reported_missing_instrument_ids:
                    continue
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "missing_instrument",
                        f"no instrument provided for resource {binding.instrument_id}",
                        f"product_bindings.{binding.record_id}.instrument_id",
                    )
                )
                continue
            description = description_by_id.get(binding.instrument_id)
            if description is None:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "missing_instrument_description",
                        f"instrument {binding.instrument_id} did not provide "
                        "a description",
                        "instruments",
                    )
                )
                continue
            descriptions = [description]
        for description in descriptions:
            product_description = _find_product_description(
                description=description,
                capability_id=binding.capability,
                product_key=binding.product_key,
            )
            if product_description is None:
                diagnostics.append(
                    _diagnostic(
                        "error",
                        "instrument_product_unsupported",
                        f"instrument {description.instrument_id} does not support "
                        f"product {binding.product_key}",
                        f"product_bindings.{binding.record_id}.product_key",
                    )
                )
                continue
            diagnostics.extend(
                _validate_product_contract(
                    binding=binding,
                    product=product_description,
                    instrument_id=description.instrument_id,
                )
            )
    return diagnostics


def _point_product_bindings(graph: RuntimeGraph) -> list[ProductBinding]:
    return [
        product
        for point in graph.points
        for instruction in point.collect
        for product in instruction.products
    ]


def _find_product_description(
    *,
    description: InstrumentDescription,
    capability_id: str | None,
    product_key: str,
) -> ProductDescription | None:
    for capability in description.capabilities:
        if capability_id is not None and capability.id != capability_id:
            continue
        for product in capability.products:
            if product.key == product_key:
                return product
    return None


def _validate_product_contract(
    *,
    binding: ProductBinding,
    product: ProductDescription,
    instrument_id: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    path = f"product_bindings.{binding.record_id}.product_key"
    if binding.kind != product.kind:
        diagnostics.append(
            _diagnostic(
                "error",
                "instrument_product_kind_mismatch",
                f"instrument {instrument_id} product {binding.product_key} kind "
                f"{product.kind!r} does not match requested {binding.kind!r}",
                path,
            )
        )
    if binding.dtype != product.dtype:
        diagnostics.append(
            _diagnostic(
                "error",
                "instrument_product_dtype_mismatch",
                f"instrument {instrument_id} product {binding.product_key} dtype "
                f"{product.dtype!r} does not match requested {binding.dtype!r}",
                path,
            )
        )
    if (
        binding.unit is not None
        and product.unit is not None
        and not compatible_units(binding.unit, product.unit)
    ):
        diagnostics.append(
            _diagnostic(
                "error",
                "instrument_product_unit_mismatch",
                f"instrument {instrument_id} product {binding.product_key} unit "
                f"{product.unit!r} is not compatible with requested {binding.unit!r}",
                path,
            )
        )
    diagnostics.extend(
        _validate_product_axes(
            binding=binding,
            product=product,
            instrument_id=instrument_id,
            path=path,
        )
    )
    return diagnostics


def _validate_product_axes(
    *,
    binding: ProductBinding,
    product: ProductDescription,
    instrument_id: str,
    path: str,
) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    if len(binding.axes) != len(product.axes):
        return [
            _diagnostic(
                "error",
                "instrument_product_axes_mismatch",
                f"instrument {instrument_id} product {binding.product_key} axes "
                f"do not match requested axes",
                path,
            )
        ]
    for index, (requested, declared) in enumerate(
        zip(binding.axes, product.axes, strict=True)
    ):
        axis_path = f"{path}.axes.{index}"
        if requested.id != declared.id or requested.kind != declared.kind:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "instrument_product_axis_mismatch",
                    f"instrument {instrument_id} product {binding.product_key} axis "
                    f"{declared.id!r} does not match requested {requested.id!r}",
                    axis_path,
                )
            )
        if declared.size is not None and requested.size != declared.size:
            diagnostics.append(
                _diagnostic(
                    "error",
                    "instrument_product_axis_size_mismatch",
                    f"instrument {instrument_id} product {binding.product_key} axis "
                    f"{declared.id!r} size {declared.size} does not match requested "
                    f"{requested.size}",
                    axis_path,
                )
            )
        if (
            requested.unit is not None
            and declared.unit is not None
            and not compatible_units(requested.unit, declared.unit)
        ):
            diagnostics.append(
                _diagnostic(
                    "error",
                    "instrument_product_axis_unit_mismatch",
                    f"instrument {instrument_id} product {binding.product_key} axis "
                    f"{declared.id!r} unit {declared.unit!r} is not compatible with "
                    f"requested {requested.unit!r}",
                    axis_path,
                )
            )
    return diagnostics


def _diagnostic(
    severity: DiagnosticSeverity, code: str, message: str, path: str | None = None
) -> Diagnostic:
    return Diagnostic(severity=severity, code=code, message=message, path=path)


__all__ = [
    "runtime_graph_diagnostics",
    "validate_point_outputs",
    "validate_runtime_graph_instruments",
]
