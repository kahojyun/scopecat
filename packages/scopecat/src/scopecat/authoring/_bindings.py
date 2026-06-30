from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from scopecat.authoring._templates import ExperimentAuthoringContext
from scopecat.authoring.expressions import (
    BindingSpec,
    ExperimentAsset,
    Expression,
)
from scopecat.authoring.expressions import (
    bind as spec_bind,
)
from scopecat.authoring.expressions import (
    bind_asset as spec_bind_asset,
)
from scopecat.models.parameter import Quantity


@dataclass(frozen=True)
class ResourceSelector:
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResourceRole:
    id: str
    selector: ResourceSelector
    resource_id: str | None = None


@dataclass(frozen=True)
class BindingIntent:
    role_path: str
    value: Expression | Quantity | float

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        resource_ids: Mapping[str, str],
    ) -> BindingSpec:
        role_id, capability_id, field_path = _parse_role_path(ctx, self.role_path)
        resource_id = resource_ids.get(role_id)
        if resource_id is None:
            ctx.raise_diagnostic(
                "recipe_unknown_resource_role",
                f"binding references unknown resource role {role_id}",
                "bindings",
            )
        ctx.require_binding_capability(resource_id, capability_id)
        return spec_bind(
            resource_id,
            capability_id,
            field_path,
            self.value,
        )


@dataclass(frozen=True)
class AssetBindingIntent:
    role_path: str
    asset: ExperimentAsset | str

    def build(
        self,
        ctx: ExperimentAuthoringContext,
        resource_ids: Mapping[str, str],
    ) -> BindingSpec:
        role_id, capability_id, field_path = _parse_role_path(ctx, self.role_path)
        resource_id = resource_ids.get(role_id)
        if resource_id is None:
            ctx.raise_diagnostic(
                "recipe_unknown_resource_role",
                f"binding references unknown resource role {role_id}",
                "bindings",
            )
        ctx.require_binding_capability(resource_id, capability_id)
        return spec_bind_asset(
            resource_id,
            capability_id,
            field_path,
            self.asset,
        )


ExperimentBindingIntent = BindingIntent | AssetBindingIntent


def requires(*capabilities: str) -> ResourceSelector:
    return ResourceSelector(capabilities=tuple(capabilities))


def resource_role(
    id: str,  # noqa: A002
    selector: ResourceSelector,
    *,
    resource_id: str | None = None,
) -> ResourceRole:
    return ResourceRole(id=id, selector=selector, resource_id=resource_id)


def bind(
    role_path: str,
    value: Expression | Quantity | float,
) -> BindingIntent:
    return BindingIntent(role_path=role_path, value=value)


def asset_binding(
    role_path: str,
    asset: ExperimentAsset | str,
) -> AssetBindingIntent:
    return AssetBindingIntent(role_path=role_path, asset=asset)


def resolve_resource_roles(
    ctx: ExperimentAuthoringContext,
    roles: Sequence[ResourceRole],
) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for role in roles:
        if role.resource_id is not None:
            ctx.require_resource(role.resource_id)
            for capability in role.selector.capabilities:
                ctx.require_capability(role.resource_id, capability)
            resolved[role.id] = role.resource_id
            continue
        candidates = [
            instrument.id
            for instrument in ctx.config.instrument_registry.instruments
            if all(
                capability in instrument.capabilities
                for capability in role.selector.capabilities
            )
        ]
        if not candidates:
            ctx.raise_diagnostic(
                "recipe_resource_role_not_found",
                f"no resource satisfies role {role.id}",
                f"resources.{role.id}",
            )
        if len(candidates) > 1:
            ctx.raise_diagnostic(
                "recipe_resource_role_ambiguous",
                f"resource role {role.id} matches multiple resources: "
                f"{', '.join(candidates)}",
                f"resources.{role.id}",
            )
        resolved[role.id] = candidates[0]
    return resolved


def _parse_role_path(
    ctx: ExperimentAuthoringContext,
    role_path: str,
) -> tuple[str, str, str]:
    parts = role_path.split(".")
    if len(parts) < 3:
        ctx.raise_diagnostic(
            "recipe_binding_path_invalid",
            "binding path must be '<role>.<capability>.<field>'",
            "bindings",
        )
    return parts[0], parts[1], ".".join(parts[2:])
