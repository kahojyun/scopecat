"""Resolve canonical logical values with sparse binding-time overrides."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import cast, override

from scopecat.compiler.frontend.logical_verification import VerifiedLogicalProgram
from scopecat.compiler.typed.program import BoundProgramFacts
from scopecat.program.expressions import ComputeResultScalarExpr, ScalarExpr
from scopecat.program.table_values import TableSource
from scopecat.program.value_graph import ValueId
from scopecat.program.value_types import Table

type ProgramValue = ScalarExpr | TableSource


def logical_program_value(
    logical: VerifiedLogicalProgram,
    value_id: ValueId,
) -> ProgramValue:
    """Project one value from the canonical verified logical program."""

    operation = logical.operation_results.get(value_id)
    if operation is not None:
        return ComputeResultScalarExpr(
            value_id=value_id,
            value_type=operation.result_type,
        )
    scalar = logical.scalar_values.get(value_id)
    if scalar is not None:
        return scalar
    value_def = logical.value_defs[value_id]
    if not isinstance(value_def.value_type, Table):
        raise AssertionError("verified non-scalar value must be a table")
    return cast("TableSource", value_def.source)


def resolve_bound_value(
    logical: VerifiedLogicalProgram,
    bindings: BoundProgramFacts,
    value_id: ValueId,
) -> ProgramValue:
    """Resolve one value, preferring a config-derived scalar override."""

    override = bindings.value_overrides.get(value_id)
    if override is not None:
        return override
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
