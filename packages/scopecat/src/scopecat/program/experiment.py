"""Immutable root program owned by an experiment definition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from scopecat.kernel.frozen import freeze_json_mapping
from scopecat.program.module import (
    ModuleBodyIR,
    ModuleInterfaceIR,
    ModuleProductExport,
    ModulePythonImplementation,
)
from scopecat.program.value_refs import empty_frozen_mapping
from scopecat.program.values import MetadataValue


@dataclass(frozen=True, slots=True)
class ExperimentProgram:
    """One experiment's root occurrences and effects.

    Unlike :class:`ModuleDef`, this root is not reusable, invocable, or named as
    a module. Its inputs are bound by the enclosing experiment definition and
    it may consume experiment coordinates and parameter expressions directly.
    """

    interface: ModuleInterfaceIR
    body: ModuleBodyIR
    python_implementations: tuple[ModulePythonImplementation, ...] = ()
    metadata: Mapping[str, MetadataValue] = field(default_factory=empty_frozen_mapping)

    def __post_init__(self) -> None:
        product_ids = tuple(product.qualified_id for product in self.products)
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("experiment program contains duplicate product ids")
        object.__setattr__(self, "metadata", freeze_json_mapping(self.metadata))

    @property
    def products(self) -> tuple[ModuleProductExport, ...]:
        return self.body.exposed_products
