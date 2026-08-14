from datetime import timedelta

import pytest

from scopecat.records.execution_journal import ExecutionTransition
from scopecat.sdk.journal import (
    ExecutionJournalError,
    ProcessExecutionJournal,
    claim_transition,
    commit_transition,
)


def _transition(*, state: str = "started") -> ExecutionTransition:
    return ExecutionTransition.model_validate(
        {
            "run_id": "run-1",
            "operation_id": "operation-1",
            "stage": "domain_execute",
            "effect": "acquisition",
            "state": state,
            "evidence": {"sample_counts": [1, 2]},
        }
    )


def test_process_journal_sequences_and_replays_exact_transitions() -> None:
    journal = ProcessExecutionJournal()
    started = _transition()

    claimed = claim_transition(journal, started)
    retry = journal.append(
        started.model_copy(
            update={"timestamp": started.timestamp + timedelta(seconds=1)}
        )
    )
    completed = commit_transition(
        journal,
        started.model_copy(update={"state": "completed"}),
    )

    assert claimed.sequence == 0
    assert retry == claimed
    assert completed.sequence == 1
    assert journal.entries() == (claimed, completed)


def test_process_journal_rejects_duplicate_claims_and_isolates_snapshots() -> None:
    journal = ProcessExecutionJournal()
    started = _transition()
    claimed = claim_transition(journal, started)

    claimed.evidence["sample_counts"] = [99]

    assert journal.entries()[0].evidence == {"sample_counts": [1, 2]}
    with pytest.raises(ExecutionJournalError, match="already claimed"):
        journal.claim(started)
    with pytest.raises(ExecutionJournalError, match="only a started transition"):
        journal.claim(started.model_copy(update={"state": "completed"}))
