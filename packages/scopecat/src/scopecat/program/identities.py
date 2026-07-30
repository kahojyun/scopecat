"""Nominal identities shared by the symbolic program model."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class InvocationKey:
    """Identity of one explicit module invocation during authoring."""

    value: UUID

    @classmethod
    def fresh(cls) -> InvocationKey:
        return cls(uuid4())


@dataclass(frozen=True, slots=True)
class ComputeDeclarationKey:
    """Identity shared by a compute declaration and its result use."""

    value: UUID

    @classmethod
    def fresh(cls) -> ComputeDeclarationKey:
        return cls(uuid4())
