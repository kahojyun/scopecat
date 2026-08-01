"""Bind acquisition effects to local collection commands."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from pydantic import JsonValue

from scopecat.compiler.diagnostics import compiler_problem
from scopecat.execution.local.program import (
    CollectionResultBinding,
    CollectOperation,
)
from scopecat.kernel.content_identity import stable_content_hash
from scopecat.kernel.frozen import thaw_json_value
from scopecat.kernel.interface_identity import InterfaceId
from scopecat.kernel.problems import Problem, model_location
from scopecat.kernel.product_identity import ProductId, ProductUse
from scopecat.kernel.resource_identity import LogicalResourcePortId
from scopecat.measurements.products import ProductDef
from scopecat.planning.local_resources import (
    ResourceEntitySelection,
    bind_single_resource,
    collection_channel_bindings,
)
from scopecat.planning.routing import ResourceBindingError
from scopecat.program.logical import AcquireEffect
from scopecat.records.instrument import CommandChannelBinding
from scopecat.sdk.instruments.commands import (
    CollectAxisRequest,
    CollectCommand,
    CollectResultRequest,
)


def bind_collect(
    products: Sequence[ProductDef],
    product_uses: Sequence[ProductUse],
    acquire: AcquireEffect,
    resources: Mapping[LogicalResourcePortId, ResourceEntitySelection],
    *,
    point_uid: str,
    point_index: int,
    point_count: int,
    problems: list[Problem],
) -> CollectOperation | None:
    products_by_id = {product.id: product for product in products}
    uses_by_product: dict[ProductId, list[ProductUse]] = {}
    for use in product_uses:
        uses_by_product.setdefault(use.product_id, []).append(use)
    requested = tuple(
        result for result in acquire.results if result.product_id in uses_by_product
    )
    if not requested:
        return None
    try:
        instrument_id, entity_ids, channel_bindings = _bind_record_target(
            acquire.resource_port_id,
            interface_id=acquire.interface_id,
            resources=resources,
        )
    except ResourceBindingError as error:
        problems.append(
            compiler_problem(
                error.code,
                str(error),
                model_location(
                    "points",
                    point_index,
                    "acquisitions",
                    acquire.id.qualified_name,
                    "resource_port_id",
                ),
            )
        )
        return None
    selected = tuple(
        (
            result,
            products_by_id[result.product_id],
            tuple(use.id for use in uses_by_product[result.product_id]),
        )
        for result in requested
    )
    operation_id = "collect-" + stable_content_hash(
        {
            "kind": "scopecat.collect_operation.v1",
            "point_id": point_uid,
            "acquisition_id": acquire.id.qualified_name,
            "instrument_id": instrument_id,
        }
    )
    return CollectOperation(
        operation_id=operation_id,
        instrument_id=instrument_id,
        result_bindings=tuple(
            CollectionResultBinding(
                request_id=result.result_id,
                product_use_ids=product_use_ids,
            )
            for result, _product, product_use_ids in selected
        ),
        command=CollectCommand(
            command_id=operation_id,
            instrument_id=instrument_id,
            point_index=point_index,
            point_count=point_count,
            requests=[
                CollectResultRequest(
                    id=result.result_id,
                    interface_id=acquire.interface_id,
                    component_path=list(acquire.component_path),
                    acquisition_id=acquire.acquisition_id,
                    result_id=result.result_id,
                    unit=product.unit,
                    dtype=product.dtype,
                    dimensions=[
                        CollectAxisRequest(
                            id=axis.id,
                            kind=axis.kind,
                            size=axis.size,
                            unit=axis.unit,
                            metadata=cast(
                                "dict[str, JsonValue]",
                                thaw_json_value(axis.metadata),
                            ),
                        )
                        for axis in product.axes
                    ],
                    entity_ids=list(entity_ids),
                    channel_bindings=list(channel_bindings),
                    metadata=cast(
                        "dict[str, JsonValue]",
                        thaw_json_value(result.metadata),
                    ),
                )
                for result, product, _product_use_ids in selected
            ],
        ),
    )


def _bind_record_target(
    target: LogicalResourcePortId,
    *,
    interface_id: InterfaceId,
    resources: Mapping[LogicalResourcePortId, ResourceEntitySelection],
) -> tuple[str, tuple[str, ...], tuple[CommandChannelBinding, ...]]:
    binding = bind_single_resource(
        target,
        resources=resources,
        missing_code="record_resource_port_unbound",
    )
    channel_bindings = collection_channel_bindings(
        binding.channel_bindings,
        interface_id=interface_id,
    )
    return (
        binding.instrument_id,
        tuple(
            dict.fromkeys(
                (
                    *binding.entity_ids,
                    *(item.entity_id for item in channel_bindings),
                )
            )
        ),
        channel_bindings,
    )
