"""Public durable transition journal contracts for host orchestration.

Domain runtimes and other host-side effect coordinators depend on this small
boundary.  Storage implementations remain free to live behind internal
adapters; callers should not need to import Scopecat's execution engine.
"""

from scopecat._execution.journal import (
    ExecutionEffect,
    ExecutionJournal,
    ExecutionJournalError,
    ExecutionStage,
    ExecutionTransition,
    JournalEntryState,
    MemoryExecutionJournal,
)

__all__ = [
    "ExecutionEffect",
    "ExecutionJournal",
    "ExecutionJournalError",
    "ExecutionStage",
    "ExecutionTransition",
    "JournalEntryState",
    "MemoryExecutionJournal",
]
