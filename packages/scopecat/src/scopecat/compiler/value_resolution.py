"""Resolve canonical logical values with sparse binding-time overrides."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import cast, override

from scopecat.compiler.bound_facts import BoundProgramFacts
from scopecat.compiler.frontend.logical_verification import VerifiedLogicalProgram
from scopecat.kernel.graph_identity import ValueId
from scopecat.kernel.value_types import Array
from scopecat.program.expressions import (
    ArrayExpr,
    ComputeResultArrayExpr,
    ComputeResultScalarExpr,
    ScalarExpr,
)
from scopecat.program.table_values import TableSource
from scopecat.program.value_types import Table

type ProgramValue = ArrayExpr | ScalarExpr | TableSource


def logical_program_value(
    logical: VerifiedLogicalProgram,
    value_id: ValueId,
) -> ProgramValue:
    """Project one value from the canonical verified logical program."""

    operation = logical.operation_results.get(value_id)
    if operation is not None:
        if isinstance(operation.result_type, Array):
            return ComputeResultArrayExpr(
                value_id=value_id,
                value_type=operation.result_type,
            )
        return ComputeResultScalarExpr(
            value_id=value_id,
            value_type=operation.result_type,
        )
    scalar = logical.scalar_values.get(value_id)
    if scalar is not None:
        return scalar
    value_def = logical.value_defs[value_id]
    if isinstance(value_def.value_type, Array):
        return cast("ArrayExpr", value_def.source)
    if isinstance(value_def.value_type, Table):
        return cast("TableSource", value_def.source)
    raise AssertionError("verified value definition has an unsupported source")


def resolve_bound_value(
    logical: VerifiedLogicalProgram,
    bindings: BoundProgramFacts,
    value_id: ValueId,
) -> ProgramValue:
    """Resolve one value, preferring a config-derived scalar override."""

    override = bindings.value_overrides.get(value_id)
    if override is not None:
        return override
    topology_selection = bindings.topology_entity_sets.get(value_id)
    if topology_selection is not None:
        return topology_selection.table
    return logical_program_value(logical, value_id)


@dataclass(frozen=True, slots=True)
class BoundValueResolver(Mapping[ValueId, ProgramValue]):
    """Read-only mapping view without copying the logical value graph."""

    logical: VerifiedLogicalProgram
    bindings: BoundProgramFacts

    @override
    def __getitem__(self, value_id: ValueId) -> ProgramValue:
        return resolve_bound_value(self.logical, self.bindings, value_id)

    @override
    def __iter__(self) -> Iterator[ValueId]:
        return iter(self.logical.value_types)

    @override
    def __len__(self) -> int:
        return len(self.logical.value_types)
