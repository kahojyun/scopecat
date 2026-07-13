from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.adapters.filesystem.run_repository import FilesystemRunRepository
from scopecat.composition.local import local_workspace_services
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    StorageError,
)
from scopecat.records.run import RunManifest
from scopecat.run_comparison import (
    RunComparisonReviewRecord,
    execute_run_comparison,
    list_run_comparisons,
    review_run_comparison,
)
from scopecat.runs.refs import MANIFEST_REF, record_content_ref
from tests.testkit.run_comparison import run_signal_experiment


def test_list_and_review_run_comparison_updates_baseline_manifest(
    tmp_path: Path,
) -> None:
    services = local_workspace_services(tmp_path)
    baseline_run_id, comparison_id = _write_comparison(tmp_path)

    views_before = list_run_comparisons(run_id=baseline_run_id, services=services)
    result, review = review_run_comparison(
        run_id=baseline_run_id,
        selector=comparison_id,
        services=services,
        state="accepted",
        reviewer="operator",
        note="candidate is equivalent",
    )
    views_after = list_run_comparisons(run_id=baseline_run_id, services=services)

    assert views_before[0].review_status == "not_reviewed"
    assert result.comparison_id == comparison_id
    assert review.decision == "accepted"
    assert views_after[0].review_status == "reviewed"


def test_review_run_comparison_rejected_works_on_record_selector(
    tmp_path: Path,
) -> None:
    services = local_workspace_services(tmp_path)
    baseline_run_id, comparison_id = _write_comparison(tmp_path)

    _result, review = review_run_comparison(
        run_id=baseline_run_id,
        selector=f"{comparison_id}-result",
        services=services,
        state="rejected",
        reviewer="operator",
        note="not suitable",
    )

    assert review.decision == "rejected"


def test_review_run_comparison_rejects_second_review(tmp_path: Path) -> None:
    services = local_workspace_services(tmp_path)
    baseline_run_id, comparison_id = _write_comparison(tmp_path)
    review_run_comparison(
        run_id=baseline_run_id,
        selector=comparison_id,
        services=services,
        state="accepted",
        reviewer="operator",
        note="first decision",
    )

    with pytest.raises(Conflict) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector=comparison_id,
            services=services,
            state="rejected",
            reviewer="operator",
            note="second decision",
        )

    assert error.value.problems[0].code == "run_comparison_already_reviewed"


def test_review_run_comparison_recovers_orphan_after_manifest_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = local_workspace_services(tmp_path)
    baseline_run_id, comparison_id = _write_comparison(tmp_path)
    review_record_id = f"{comparison_id}-review"
    review_ref = record_content_ref(
        record_id=review_record_id,
        kind="run_comparison_review_record",
    )
    original_write_manifest = FilesystemRunRepository.write_manifest
    failed = False

    def fail_first_review_manifest(
        storage: FilesystemRunRepository,
        manifest: RunManifest,
    ) -> None:
        nonlocal failed
        if not failed and any(
            record.id == review_record_id for record in manifest.records
        ):
            failed = True
            raise OSError("injected review manifest failure")
        original_write_manifest(storage, manifest)

    monkeypatch.setattr(
        FilesystemRunRepository,
        "write_manifest",
        fail_first_review_manifest,
    )

    with pytest.raises(OSError, match="injected review manifest failure"):
        review_run_comparison(
            run_id=baseline_run_id,
            selector=comparison_id,
            services=services,
            state="accepted",
            reviewer="operator",
            note="retryable decision",
        )

    storage = services.runs
    orphan = storage.read_model(
        baseline_run_id,
        review_ref,
        RunComparisonReviewRecord,
    )
    assert all(
        record.id != review_record_id
        for record in storage.read_manifest(baseline_run_id).records
    )
    assert (
        list_run_comparisons(
            run_id=baseline_run_id,
            services=services,
        )[0].review_status
        == "not_reviewed"
    )

    _result, recovered = review_run_comparison(
        run_id=baseline_run_id,
        selector=comparison_id,
        services=services,
        state="accepted",
        reviewer="operator",
        note="retryable decision",
    )

    assert recovered == orphan
    assert any(
        record.id == review_record_id
        for record in storage.read_manifest(baseline_run_id).records
    )


def test_review_run_comparison_republishes_visible_manifest_after_replace_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    services = local_workspace_services(tmp_path)
    baseline_run_id, comparison_id = _write_comparison(tmp_path)
    review_record_id = f"{comparison_id}-review"
    review_ref = record_content_ref(
        record_id=review_record_id,
        kind="run_comparison_review_record",
    )
    manifest_path = FilesystemRunRepository(tmp_path).ref_path(
        baseline_run_id,
        MANIFEST_REF,
    )
    real_replace = Path.replace
    manifest_replace_attempts = 0

    def fail_after_first_manifest_replace(source: Path, target: Path) -> Path:
        nonlocal manifest_replace_attempts
        replaced = real_replace(source, target)
        if target == manifest_path:
            manifest_replace_attempts += 1
            if manifest_replace_attempts == 1:
                raise OSError("injected manifest post-replace failure")
        return replaced

    monkeypatch.setattr(Path, "replace", fail_after_first_manifest_replace)

    with pytest.raises(StorageError) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector=comparison_id,
            services=services,
            state="accepted",
            reviewer="operator",
            note="durably committed decision",
        )
    assert error.value.problems[0].code == "storage.operation_failed"

    storage = services.runs
    committed = storage.read_model(
        baseline_run_id,
        review_ref,
        RunComparisonReviewRecord,
    )
    assert any(
        record.id == review_record_id
        for record in storage.read_manifest(baseline_run_id).records
    )
    assert (
        list_run_comparisons(
            run_id=baseline_run_id,
            services=services,
        )[0].review_status
        == "reviewed"
    )

    _result, recovered = review_run_comparison(
        run_id=baseline_run_id,
        selector=comparison_id,
        services=services,
        state="accepted",
        reviewer="operator",
        note="durably committed decision",
    )

    assert recovered == committed
    assert manifest_replace_attempts == 2


def test_review_run_comparison_rejects_path_escape(tmp_path: Path) -> None:
    services = local_workspace_services(tmp_path)
    baseline_run_id = run_signal_experiment(tmp_path)

    with pytest.raises(CheckFailed) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector="../escape.json",
            services=services,
            state="accepted",
            reviewer="operator",
            note="",
        )

    assert error.value.problems[0].code == "run_comparison_path_escape"


def test_review_run_comparison_rejects_invalid_json(tmp_path: Path) -> None:
    services = local_workspace_services(tmp_path)
    baseline_run_id, comparison_id = _write_comparison(tmp_path)
    FilesystemRunRepository(tmp_path).ref_path(
        baseline_run_id,
        record_content_ref(
            record_id=f"{comparison_id}-result",
            kind="run_comparison_result",
        ),
    ).write_text("{}\n")

    with pytest.raises(DataIntegrityError) as error:
        review_run_comparison(
            run_id=baseline_run_id,
            selector=comparison_id,
            services=services,
            state="accepted",
            reviewer="operator",
            note="",
        )

    assert error.value.problems[0].code == "invalid_run_comparison"


def _write_comparison(tmp_path: Path) -> tuple[str, str]:
    services = local_workspace_services(tmp_path)
    baseline_run_id = run_signal_experiment(tmp_path)
    candidate_run_id = run_signal_experiment(tmp_path)
    execute_run_comparison(
        baseline_run_id=baseline_run_id,
        candidate_run_id=candidate_run_id,
        services=services,
    )
    return baseline_run_id, f"run-comparison-{candidate_run_id}-signal"
