"""Application service for physical sample registry workflows."""

from __future__ import annotations

from scopecat.daemon.views import SamplePage, SampleRevisionPage, SampleView
from scopecat.daemon.wire import (
    SampleCreateCommand,
    SampleMutationReceipt,
    SampleReviseCommand,
)
from scopecat.records.sample import SampleBinding, SampleRevision, SampleSelector

from scopecat_server.storage.sqlite.samples import SQLiteSampleStore


class SampleService:
    """Expose stable samples without leaking SQLite identities."""

    def __init__(self, store: SQLiteSampleStore) -> None:
        self._store = store

    def list(
        self,
        *,
        limit: int = 100,
        before: int | None = None,
    ) -> SamplePage:
        return self._store.list_samples(limit=limit, before=before)

    def get(self, sample_id: str) -> SampleView:
        return self._store.get_sample(sample_id)

    def revisions(
        self,
        sample_id: str,
        *,
        limit: int = 100,
        before: int | None = None,
    ) -> SampleRevisionPage:
        return self._store.list_revisions(sample_id, limit=limit, before=before)

    def revision(self, sample_id: str, revision: int) -> SampleRevision:
        return self._store.get_revision(sample_id, revision)

    def create(self, command: SampleCreateCommand) -> SampleMutationReceipt:
        return self._store.create_sample(command)

    def revise(
        self,
        sample_id: str,
        command: SampleReviseCommand,
    ) -> SampleMutationReceipt:
        return self._store.revise_sample(sample_id, command)

    def resolve_bindings(
        self,
        selectors: tuple[SampleSelector, ...],
    ) -> tuple[SampleBinding, ...]:
        return self._store.resolve_bindings(selectors)


__all__ = ["SampleService"]
