from __future__ import annotations

from pathlib import Path

import pytest

from scopecat.adapters.filesystem.measurement_files import read_measurement_records_path
from scopecat.kernel.errors import DataIntegrityError, NotFound, StorageError
from scopecat.kernel.problems import ProblemCategory, StorageLocation


def _read(path: Path) -> object:
    return read_measurement_records_path(
        path=path,
        ref="data/measurements.ndjson",
        missing_code="measurement.missing",
        empty_code="measurement.empty",
        invalid_code="measurement.invalid",
        noun="measurement input",
    )


def test_measurement_read_distinguishes_missing_and_corrupt_paths(
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.ndjson"
    with pytest.raises(NotFound) as missing:
        _read(missing_path)

    missing_problem = missing.value.problems[0]
    assert missing_problem.category is ProblemCategory.NOT_FOUND
    assert missing_problem.location == StorageLocation(ref="data/measurements.ndjson")
    assert isinstance(missing.value.__cause__, FileNotFoundError)

    directory_path = tmp_path / "directory.ndjson"
    directory_path.mkdir()
    with pytest.raises(DataIntegrityError) as directory:
        _read(directory_path)

    assert directory.value.problems[0].category is ProblemCategory.DATA_INTEGRITY
    assert isinstance(directory.value.__cause__, IsADirectoryError)


def test_measurement_read_preserves_operating_system_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "measurements.ndjson"
    path.write_text("{}\n")

    def fail_read(_path: Path, *args: object, **kwargs: object) -> str:
        _ = args, kwargs
        raise PermissionError("private operating-system detail")

    monkeypatch.setattr(Path, "read_text", fail_read)

    with pytest.raises(StorageError) as captured:
        _read(path)

    problem = captured.value.problems[0]
    assert problem.category is ProblemCategory.STORAGE
    assert "private operating-system detail" not in problem.message
    assert isinstance(captured.value.__cause__, PermissionError)
