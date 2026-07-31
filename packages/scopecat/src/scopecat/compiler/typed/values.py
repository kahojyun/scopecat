"""Typed compiler values retained after logical program binding."""

from __future__ import annotations

from dataclasses import dataclass

from scopecat.kernel.value_types import Table
from scopecat.program.expressions import ScalarExpression
from scopecat.program.table_values import TableSource


@dataclass(frozen=True, slots=True)
class TableValue:
    """A typed whole table passed directly to a domain compiler."""

    source: TableSource
    value_type: Table


type CompilerValue = ScalarExpression | TableValue
