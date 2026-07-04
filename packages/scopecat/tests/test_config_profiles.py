from pathlib import Path

from scopecat.config_profiles import ConfigProfileFile, load_config_profile
from tests.support.records import assert_model_round_trip, read_model

EXAMPLE_DIR = Path(__file__).parents[3] / "fixtures" / "core" / "simple_scan"


def test_config_profile_file_round_trip() -> None:
    profile = read_model(EXAMPLE_DIR / "config-profile.json", ConfigProfileFile)
    restored = assert_model_round_trip(
        profile,
        schema_version="scopecat.config_profile.v0",
    )

    assert restored.system_ref == "system-spec.json"
    assert restored.environment_ref == "environment-spec.json"
    assert restored.parameter_state_ref == "parameter-state.json"


def test_load_config_profile_freezes_split_inputs() -> None:
    snapshot = load_config_profile(EXAMPLE_DIR / "config-profile.json")

    assert snapshot.id == "example-workspace-profile"
    assert snapshot.parameter_build is not None
