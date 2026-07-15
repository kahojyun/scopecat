"""Internal local run store."""

from __future__ import annotations

from collections.abc import Generator, Iterable
from contextlib import contextmanager, suppress
from fcntl import LOCK_EX, LOCK_UN, flock
from pathlib import Path
from stat import S_ISDIR, S_ISREG

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from scopecat.adapters.filesystem.io import (
    ensure_durable_directory,
)
from scopecat.adapters.filesystem.io import (
    read_jsonl as _read_jsonl,
)
from scopecat.adapters.filesystem.io import (
    read_model as _read_model,
)
from scopecat.adapters.filesystem.io import (
    read_text as _read_text,
)
from scopecat.adapters.filesystem.io import write_bytes_atomic as _write_bytes_atomic
from scopecat.adapters.filesystem.io import (
    write_jsonl as _write_jsonl,
)
from scopecat.adapters.filesystem.io import (
    write_model as _write_model,
)
from scopecat.adapters.filesystem.io import (
    write_model_if_absent as _write_model_if_absent,
)
from scopecat.adapters.filesystem.io import (
    write_text as _write_text,
)
from scopecat.adapters.filesystem.layout import FilesystemRunLayout
from scopecat.kernel.errors import DataIntegrityError, NotFound, StorageError
from scopecat.kernel.problems import (
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
    StorageLocation,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunManifest
from scopecat.records.run_plan import RunPlanRecord
from scopecat.records.run_request import RunRequest
from scopecat.runs.provenance import validate_run_config_provenance
from scopecat.runs.refs import (
    CONFIG_PROFILE_SNAPSHOT_REF,
    MANIFEST_REF,
    RUN_PLAN_REF,
    RUN_REQUEST_REF,
)
from scopecat.runs.repository import RunRefKind


class FilesystemRunRepository:
    """Internal entrypoint for local run persistence."""

    def __init__(self, workspace: str | Path) -> None:
        self.layout = FilesystemRunLayout.from_workspace(workspace)

    def display_run_path(self, run_id: str) -> Path:
        return self.layout.display_run_path(run_id)

    def display_ref_path(self, run_id: str, ref: str) -> Path:
        return self.layout.display_ref_path(run_id, ref)

    def ref_path(self, run_id: str, ref: str) -> Path:
        return self.layout.ref_path(run_id, ref)

    def exists(self, run_id: str, ref: str) -> bool:
        path = self.ref_path(run_id, ref)
        try:
            path.stat()
        except FileNotFoundError:
            return False
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        return True

    def ref_kind(self, run_id: str, ref: str) -> RunRefKind:
        path = self.ref_path(run_id, ref)
        try:
            mode = path.stat().st_mode
        except FileNotFoundError:
            return "missing"
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        if S_ISREG(mode):
            return "file"
        if S_ISDIR(mode):
            return "directory"
        return "other"

    def read_manifest(self, run_id: str) -> RunManifest:
        manifest_path = self.ref_path(run_id, MANIFEST_REF)
        try:
            return _read_model(manifest_path, RunManifest)
        except FileNotFoundError as error:
            raise NotFound(
                [
                    _run_problem(
                        run_id=run_id,
                        ref=MANIFEST_REF,
                        code="run.not_found",
                        category=ProblemCategory.NOT_FOUND,
                        message="run was not found",
                    )
                ]
            ) from error
        except (IsADirectoryError, UnicodeError, ValidationError) as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=MANIFEST_REF,
                code="run.manifest_invalid",
                message="run manifest does not match its durable schema",
            ) from error
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=MANIFEST_REF) from error

    def write_manifest(self, manifest: RunManifest) -> None:
        self.write_model(manifest.run_id, MANIFEST_REF, manifest)

    @contextmanager
    def run_lock(self, run_id: str) -> Generator[None]:
        """Serialize mutations of one run's content and manifest.

        Callers that also hold the config-registry lock must acquire that lock
        first. This lock is intentionally not re-entrant; locked helpers avoid
        acquiring it a second time.
        """

        lock_ref = ".run.lock"
        lock_path = self.ref_path(run_id, lock_ref)
        with _exclusive_lock(lock_path, run_id=run_id, ref=lock_ref):
            yield

    def list_runs(self) -> list[RunManifest]:
        runs_root = self.layout.validated_runs_root()
        try:
            root_stat = runs_root.stat()
        except FileNotFoundError:
            return []
        except OSError as error:
            raise _storage_failure(ref="runs") from error
        if not S_ISDIR(root_stat.st_mode):
            raise _integrity_failure(
                ref="runs",
                code="run.repository_invalid",
                message="run repository root is not a directory",
            )
        try:
            manifest_paths = sorted(runs_root.glob("*/manifest.json"))
        except OSError as error:
            raise _storage_failure(ref="runs") from error
        manifests: list[RunManifest] = []
        for manifest_path in manifest_paths:
            manifests.append(self.read_manifest(manifest_path.parent.name))
        return sorted(manifests, key=lambda manifest: manifest.created_at)

    def write_structured_run_inputs(
        self,
        *,
        manifest: RunManifest,
        request: RunRequest | None,
        plan: RunPlanRecord,
        config: ConfigProfileSnapshot,
    ) -> None:
        # Publish accepted inputs before the manifest makes the run visible.
        validate_run_config_provenance(
            manifest=manifest,
            plan=plan,
            config=config,
        )
        if request is not None:
            self.write_model(manifest.run_id, RUN_REQUEST_REF, request)
        self.write_model(manifest.run_id, RUN_PLAN_REF, plan)
        self.write_model(
            manifest.run_id,
            CONFIG_PROFILE_SNAPSHOT_REF,
            config,
        )
        self.write_manifest(manifest)

    def write_run_skeleton(
        self,
        *,
        manifest: RunManifest,
        request: RunRequest | None,
        plan: RunPlanRecord,
        config: ConfigProfileSnapshot,
    ) -> None:
        """Durably accept a run before any instrument interaction begins."""

        if manifest.status not in {"planned", "running"}:
            msg = "run skeleton manifest must be planned or running"
            raise ValueError(msg)
        self.write_structured_run_inputs(
            manifest=manifest,
            request=request,
            plan=plan,
            config=config,
        )

    def read_config_profile_snapshot(self, run_id: str) -> ConfigProfileSnapshot:
        manifest = self.read_manifest(run_id)
        plan = (
            self.read_model(run_id, RUN_PLAN_REF, RunPlanRecord)
            if self.exists(run_id, RUN_PLAN_REF)
            else None
        )
        config = self.read_model(
            run_id, CONFIG_PROFILE_SNAPSHOT_REF, ConfigProfileSnapshot
        )
        validate_run_config_provenance(
            manifest=manifest,
            plan=plan,
            config=config,
        )
        return config

    def read_run_plan(self, run_id: str) -> RunPlanRecord:
        manifest = self.read_manifest(run_id)
        plan = self.read_model(run_id, RUN_PLAN_REF, RunPlanRecord)
        config = self.read_model(
            run_id, CONFIG_PROFILE_SNAPSHOT_REF, ConfigProfileSnapshot
        )
        validate_run_config_provenance(
            manifest=manifest,
            plan=plan,
            config=config,
        )
        return plan

    def read_model[TModel: BaseModel](
        self, run_id: str, ref: str, model_type: type[TModel]
    ) -> TModel:
        path = self.ref_path(run_id, ref)
        try:
            return _read_model(path, model_type)
        except FileNotFoundError as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_missing",
                message="run is missing a referenced durable record",
            ) from error
        except (IsADirectoryError, UnicodeError, ValidationError) as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_invalid",
                message="run record does not match its durable schema",
            ) from error
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error

    def write_model(self, run_id: str, ref: str, model: BaseModel) -> None:
        path = self.ref_path(run_id, ref)
        try:
            _write_model(path, model)
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        except (PydanticSerializationError, TypeError, ValueError) as error:
            raise _serialization_failure(run_id=run_id, ref=ref) from error

    def write_model_if_absent(
        self,
        run_id: str,
        ref: str,
        model: BaseModel,
    ) -> bool:
        path = self.ref_path(run_id, ref)
        try:
            return _write_model_if_absent(path, model)
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        except (PydanticSerializationError, TypeError, ValueError) as error:
            raise _serialization_failure(run_id=run_id, ref=ref) from error

    def read_jsonl[TModel: BaseModel](
        self, run_id: str, ref: str, model_type: type[TModel]
    ) -> list[TModel]:
        path = self.ref_path(run_id, ref)
        try:
            return _read_jsonl(path, model_type)
        except FileNotFoundError as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_missing",
                message="run is missing a referenced durable record",
            ) from error
        except (IsADirectoryError, UnicodeError, ValidationError) as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_invalid",
                message="run record does not match its durable schema",
            ) from error
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error

    def write_jsonl(self, run_id: str, ref: str, records: Iterable[BaseModel]) -> None:
        path = self.ref_path(run_id, ref)
        try:
            _write_jsonl(path, records)
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        except (PydanticSerializationError, TypeError, ValueError) as error:
            raise _serialization_failure(run_id=run_id, ref=ref) from error

    def read_text(self, run_id: str, ref: str) -> str:
        path = self.ref_path(run_id, ref)
        try:
            return _read_text(path)
        except FileNotFoundError as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_missing",
                message="run is missing a referenced durable record",
            ) from error
        except (IsADirectoryError, UnicodeError) as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_invalid",
                message="run record is not valid text",
            ) from error
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error

    def read_bytes(self, run_id: str, ref: str) -> bytes:
        path = self.ref_path(run_id, ref)
        try:
            return path.read_bytes()
        except FileNotFoundError as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_missing",
                message="run is missing a referenced durable record",
            ) from error
        except IsADirectoryError as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_invalid",
                message="run record is not a readable file",
            ) from error
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error

    def write_text(self, run_id: str, ref: str, content: str) -> None:
        path = self.ref_path(run_id, ref)
        try:
            _write_text(path, content)
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error

    def write_bytes(self, run_id: str, ref: str, content: bytes) -> None:
        path = self.ref_path(run_id, ref)
        try:
            _write_bytes_atomic(path, content)
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error


@contextmanager
def _exclusive_lock(
    path: Path,
    *,
    ref: str,
    run_id: str | None = None,
) -> Generator[None]:
    lock_file = None
    try:
        ensure_durable_directory(path.parent)
        lock_file = path.open("a+b")
        flock(lock_file.fileno(), LOCK_EX)
    except OSError as error:
        if lock_file is not None:
            with suppress(OSError):
                lock_file.close()
        raise _storage_failure(run_id=run_id, ref=ref) from error
    assert lock_file is not None
    try:
        yield
    finally:
        try:
            flock(lock_file.fileno(), LOCK_UN)
            lock_file.close()
        except OSError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error


def _serialization_failure(*, run_id: str, ref: str) -> DataIntegrityError:
    return _integrity_failure(
        run_id=run_id,
        ref=ref,
        code="run.ref_not_serializable",
        message="run record cannot be represented by the durable format",
    )


def _integrity_failure(
    *,
    ref: str,
    code: str,
    message: str,
    run_id: str | None = None,
) -> DataIntegrityError:
    return DataIntegrityError(
        [
            _run_problem(
                run_id=run_id,
                ref=ref,
                code=code,
                category=ProblemCategory.DATA_INTEGRITY,
                message=message,
            )
        ]
    )


def _storage_failure(
    *,
    ref: str,
    run_id: str | None = None,
) -> StorageError:
    return StorageError(
        [
            _run_problem(
                run_id=run_id,
                ref=ref,
                code="storage.operation_failed",
                category=ProblemCategory.STORAGE,
                message="storage could not complete the run repository operation",
            )
        ]
    )


def _run_problem(
    *,
    ref: str,
    code: str,
    category: ProblemCategory,
    message: str,
    run_id: str | None = None,
) -> Problem:
    return Problem(
        code=code,
        impact=ProblemImpact.BLOCKING,
        category=category,
        phase=ProblemPhase.PERSISTENCE,
        message=message,
        location=StorageLocation(run_id=run_id, ref=ref),
    )
