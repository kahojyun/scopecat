from pathlib import Path

import pytest

from scopecat.config.profiles import ConfigProfileManifest, load_config_profile
from scopecat.kernel.errors import DataIntegrityError, NotFound, StorageError
from scopecat.kernel.problems import ExternalLocation, ProblemCategory
from tests.testkit.paths import CORE_FIXTURE_DIR as EXAMPLE_DIR
from tests.testkit.records import assert_model_round_trip, read_model


def test_config_profile_file_round_trip() -> None:
    profile = read_model(EXAMPLE_DIR / "config-profile.json", ConfigProfileManifest)
    restored = assert_model_round_trip(profile)

    assert restored.format_version == "scopecat.config_profile_manifest.v1"
    assert restored.system_ref == "system-spec.json"
    assert restored.environment_ref == "environment-spec.json"
    assert restored.parameter_snapshot_ref == "parameter-snapshot.json"


def test_load_config_profile_freezes_split_inputs() -> None:
    snapshot = load_config_profile(EXAMPLE_DIR / "config-profile.json")

    assert snapshot.id == "simple-scan-profile"
    assert snapshot.parameter_snapshot.get("drive_frequency") is not None


def test_load_config_profile_maps_missing_input_to_not_found(tmp_path: Path) -> None:
    missing_path = tmp_path / "missing.json"

    with pytest.raises(NotFound) as captured:
        load_config_profile(missing_path)

    problem = captured.value.problems[0]
    assert problem.code == "config.profile.not_found"
    assert problem.category is ProblemCategory.NOT_FOUND
    assert problem.location == ExternalLocation(uri=str(missing_path))
    assert isinstance(captured.value.__cause__, FileNotFoundError)


def test_load_config_profile_maps_invalid_json_to_data_integrity(
    tmp_path: Path,
) -> None:
    profile_path = tmp_path / "config-profile.json"
    profile_path.write_text("not-json")

    with pytest.raises(DataIntegrityError) as captured:
        load_config_profile(profile_path)

    problem = captured.value.problems[0]
    assert problem.code == "config.profile.invalid"
    assert problem.category is ProblemCategory.DATA_INTEGRITY
    assert captured.value.__cause__ is not None


def test_load_config_profile_maps_io_failure_without_exposing_raw_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_path = tmp_path / "config-profile.json"
    storage_cause = PermissionError("private filesystem details")

    def fail_read_text(_path: Path, *_args: object, **_kwargs: object) -> str:
        raise storage_cause

    monkeypatch.setattr(Path, "read_text", fail_read_text)

    with pytest.raises(StorageError) as captured:
        load_config_profile(profile_path)

    assert captured.value.__cause__ is storage_cause
    assert captured.value.problems[0].category is ProblemCategory.STORAGE
    assert "private filesystem details" not in str(captured.value)
