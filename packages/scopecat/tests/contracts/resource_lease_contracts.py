"""Reusable behavior for whole-run resource lease managers."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

from scopecat.execution.ports.resources import ResourceLeaseManager
from scopecat.kernel.resource_identity import ResourceClaim


class ResourceLeaseManagerContract:
    """Overlapping claims exclude while distinct claims remain independent."""

    def make_manager(self, tmp_path: Path) -> ResourceLeaseManager:
        raise NotImplementedError

    def test_empty_and_duplicate_claim_sets_are_valid(self, tmp_path: Path) -> None:
        manager = self.make_manager(tmp_path)
        claim = ResourceClaim(id="source")

        with manager.acquire(()):
            pass
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                lambda: _enter_once(manager, (claim, claim)),
            )
            future.result(timeout=2)

    def test_overlapping_claims_are_mutually_exclusive(self, tmp_path: Path) -> None:
        manager = self.make_manager(tmp_path)
        claim = ResourceClaim(id="shared")
        first_entered = Event()
        release_first = Event()
        second_started = Event()
        second_entered = Event()

        def hold_first() -> None:
            with manager.acquire((claim,)):
                first_entered.set()
                assert release_first.wait(timeout=2)

        def enter_second() -> None:
            second_started.set()
            with manager.acquire((claim,)):
                second_entered.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(hold_first)
            assert first_entered.wait(timeout=2)
            second = executor.submit(enter_second)
            assert second_started.wait(timeout=2)
            assert not second_entered.wait(timeout=0.05)
            release_first.set()
            first.result(timeout=2)
            second.result(timeout=2)
        assert second_entered.is_set()

    def test_distinct_claims_can_progress_independently(self, tmp_path: Path) -> None:
        manager = self.make_manager(tmp_path)
        first_claim = ResourceClaim(id="first")
        second_claim = ResourceClaim(id="second")
        first_entered = Event()
        release_first = Event()
        second_entered = Event()

        def hold_first() -> None:
            with manager.acquire((first_claim,)):
                first_entered.set()
                assert release_first.wait(timeout=2)

        def enter_second() -> None:
            with manager.acquire((second_claim,)):
                second_entered.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(hold_first)
            assert first_entered.wait(timeout=2)
            second = executor.submit(enter_second)
            assert second_entered.wait(timeout=2)
            release_first.set()
            first.result(timeout=2)
            second.result(timeout=2)


def _enter_once(
    manager: ResourceLeaseManager,
    claims: tuple[ResourceClaim, ...],
) -> None:
    with manager.acquire(claims):
        pass


__all__ = ["ResourceLeaseManagerContract"]
