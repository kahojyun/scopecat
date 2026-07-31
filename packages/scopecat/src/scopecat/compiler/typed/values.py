"""Typed compiler values retained after logical program binding."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.relations.verification import VerifiedRelationPlan
from scopecat.kernel.value_types import Table
from scopecat.program.table_values import TableSource


@dataclass(frozen=True, slots=True)
class TableValue:
    """A typed whole table passed directly to a domain compiler."""

    source: TableSource
    value_type: Table


type CompilerValue = VerifiedRelationPlan | TableValue
