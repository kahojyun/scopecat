"""Typed compiler values retained after logical program binding."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.compiler.relations.verification import VerifiedRelationPlan
from scopecat.graph.table_values import TableSource
from scopecat.kernel.value_types import Table


@dataclass(frozen=True, slots=True)
class TableValue:
    """A typed whole table passed directly to a domain compiler."""

    source: TableSource
    value_type: Table


type CompilerValue = VerifiedRelationPlan | TableValue
