from __future__ import annotations

from pathlib import Path

import pytest

from scopecat_server import (
    ProjectManifestError,
    discover_lab_project,
    load_lab_project,
)


def test_project_paths_are_resolved_from_manifest(tmp_path: Path) -> None:
    config = tmp_path / "config" / "initial.json"
    config.parent.mkdir()
    config.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "scopecat.toml"
    manifest.write_text(
        (
            "[lab]\n"
            'application = "my_lab.application:create"\n'
            'bootstrap-config = "config/initial.json"\n'
        ),
        encoding="utf-8",
    )

    project = load_lab_project(manifest)

    assert project.root == tmp_path
    assert project.application == "my_lab.application:create"
    assert project.bootstrap_config == config


def test_project_is_discovered_from_a_child_directory(tmp_path: Path) -> None:
    (tmp_path / "scopecat.toml").write_text(
        '[lab]\napplication = "my_lab.application:create"\n',
        encoding="utf-8",
    )
    child = tmp_path / "notebooks" / "calibration"
    child.mkdir(parents=True)

    assert discover_lab_project(child).root == tmp_path


@pytest.mark.parametrize(
    "content, message",
    [
        ("", r"requires a \[lab\] table"),
        ("[lab]\n", "requires application or bootstrap-config"),
        ("[lab]\nunknown = true\n", r"unknown \[lab\] field"),
        ("[lab]\napplication = ''\n", "must be a non-empty string"),
    ],
)
def test_invalid_project_manifests_fail_at_the_boundary(
    tmp_path: Path,
    content: str,
    message: str,
) -> None:
    manifest = tmp_path / "scopecat.toml"
    manifest.write_text(content, encoding="utf-8")

    with pytest.raises(ProjectManifestError, match=message):
        load_lab_project(manifest)
