"""In-memory implementation of the durable run repository contract."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from pathlib import PurePosixPath
from threading import RLock

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from scopecat.kernel.errors import CheckFailed, DataIntegrityError, NotFound
from scopecat.kernel.problems import (
    ModelLocation,
    Problem,
    ProblemCategory,
    ProblemImpact,
    ProblemPhase,
    StorageLocation,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.run import RunManifest
from scopecat.records.run_request import RunRequest
from scopecat.runs.access import upsert_contents
from scopecat.runs.provenance import validate_run_config_provenance
from scopecat.runs.refs import (
    CONFIG_PROFILE_SNAPSHOT_REF,
    MANIFEST_REF,
    RUN_REQUEST_REF,
)
from scopecat.runs.repository import TerminalRunCommit

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class MemoryRunRepository:
    """Serialized in-memory run state used by contracts and pure use-case tests."""

    def __init__(self) -> None:
        self._content: dict[tuple[str, str], bytes] = {}
        self._locks: defaultdict[str, RLock] = defaultdict(RLock)

    def exists(self, run_id: str, ref: str) -> bool:
        return self._key(run_id, ref) in self._content

    def read_manifest(self, run_id: str) -> RunManifest:
        key = self._key(run_id, MANIFEST_REF)
        content = self._content.get(key)
        if content is None:
            raise NotFound(
                [
                    _problem(
                        run_id=run_id,
                        ref=MANIFEST_REF,
                        code="run.not_found",
                        category=ProblemCategory.NOT_FOUND,
                        message="run was not found",
                    )
                ]
            )
        return _validate_model(
            content,
            RunManifest,
            run_id=run_id,
            ref=MANIFEST_REF,
            code="run.manifest_invalid",
            message="run manifest does not match its durable schema",
        )

    def write_manifest(self, manifest: RunManifest) -> None:
        self.write_model(manifest.run_id, MANIFEST_REF, manifest)

    @contextmanager
    def run_lock(self, run_id: str) -> Generator[None]:
        _validate_run_id(run_id)
        with self._locks[run_id]:
            yield

    def list_runs(self) -> list[RunManifest]:
        run_ids = {run_id for run_id, ref in self._content if ref == MANIFEST_REF}
        return sorted(
            (self.read_manifest(run_id) for run_id in run_ids),
            key=lambda manifest: manifest.created_at,
        )

    def write_run_skeleton(
        self,
        *,
        manifest: RunManifest,
        request: RunRequest | None,
        config: ConfigProfileSnapshot,
    ) -> None:
        if manifest.lifecycle != "accepted":
            msg = "run skeleton manifest must be accepted"
            raise ValueError(msg)
        validate_run_config_provenance(
            manifest=manifest,
            config=config,
        )
        if request is not None:
            self.write_model(manifest.run_id, RUN_REQUEST_REF, request)
        self.write_model(manifest.run_id, CONFIG_PROFILE_SNAPSHOT_REF, config)
        self.write_manifest(manifest)

    def commit_terminal(self, commit: TerminalRunCommit) -> RunManifest:
        run_id = commit.manifest.run_id
        for write in commit.models:
            self.write_model(run_id, write.ref, write.value)
        for write in commit.record_sets:
            self.write_jsonl(run_id, write.ref, write.records)
        with self.run_lock(run_id):
            current = self.read_manifest(run_id)
            manifest = commit.manifest.model_copy(
                update={
                    "contents": upsert_contents(
                        current.contents,
                        commit.manifest.contents,
                    )
                }
            )
            self.write_manifest(manifest)
        return manifest

    def read_config_profile_snapshot(self, run_id: str) -> ConfigProfileSnapshot:
        manifest = self.read_manifest(run_id)
        config = self.read_model(
            run_id,
            CONFIG_PROFILE_SNAPSHOT_REF,
            ConfigProfileSnapshot,
        )
        validate_run_config_provenance(
            manifest=manifest,
            config=config,
        )
        return config

    def read_model[TModel: BaseModel](
        self,
        run_id: str,
        ref: str,
        model_type: type[TModel],
    ) -> TModel:
        content = self._require_content(run_id, ref)
        return _validate_model(
            content,
            model_type,
            run_id=run_id,
            ref=ref,
            code="run.ref_invalid",
            message="run record does not match its durable schema",
        )

    def write_model(self, run_id: str, ref: str, model: BaseModel) -> None:
        self._content[self._key(run_id, ref)] = _serialize_model(
            model,
            run_id=run_id,
            ref=ref,
        )

    def write_model_if_absent(
        self,
        run_id: str,
        ref: str,
        model: BaseModel,
    ) -> bool:
        key = self._key(run_id, ref)
        content = _serialize_model(model, run_id=run_id, ref=ref)
        with self._locks[run_id]:
            if key in self._content:
                return False
            self._content[key] = content
            return True

    def read_jsonl[TModel: BaseModel](
        self,
        run_id: str,
        ref: str,
        model_type: type[TModel],
    ) -> list[TModel]:
        content = self.read_text(run_id, ref)
        try:
            return [
                model_type.model_validate_json(line)
                for line in content.splitlines()
                if line.strip()
            ]
        except ValidationError as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_invalid",
                message="run record does not match its durable schema",
            ) from error

    def write_jsonl(
        self,
        run_id: str,
        ref: str,
        records: Iterable[BaseModel],
    ) -> None:
        try:
            content = "".join(
                json.dumps(
                    record.model_dump(mode="json"),
                    allow_nan=True,
                    separators=(",", ":"),
                )
                + "\n"
                for record in records
            )
        except (PydanticSerializationError, TypeError, ValueError) as error:
            raise _serialization_failure(run_id=run_id, ref=ref) from error
        self.write_text(run_id, ref, content)

    def read_text(self, run_id: str, ref: str) -> str:
        content = self._require_content(run_id, ref)
        try:
            return content.decode()
        except UnicodeError as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_invalid",
                message="run record is not valid text",
            ) from error

    def read_bytes(self, run_id: str, ref: str) -> bytes:
        return bytes(self._require_content(run_id, ref))

    def write_bytes(self, run_id: str, ref: str, content: bytes) -> None:
        self._content[self._key(run_id, ref)] = bytes(content)

    def write_text(self, run_id: str, ref: str, content: str) -> None:
        if content and not content.endswith("\n"):
            content = f"{content}\n"
        self.write_bytes(run_id, ref, content.encode())

    def _require_content(self, run_id: str, ref: str) -> bytes:
        content = self._content.get(self._key(run_id, ref))
        if content is None:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_missing",
                message="run is missing a referenced durable record",
            )
        return content

    @staticmethod
    def _key(run_id: str, ref: str) -> tuple[str, str]:
        _validate_run_id(run_id)
        _validate_ref(ref)
        return run_id, ref


def _validate_run_id(run_id: str) -> None:
    if _SAFE_RUN_ID.fullmatch(run_id) is not None:
        return
    raise CheckFailed(
        [
            Problem(
                code="run.id_invalid",
                impact=ProblemImpact.BLOCKING,
                category=ProblemCategory.INVALID_INPUT,
                phase=ProblemPhase.PERSISTENCE,
                message="run id is not safe for storage access",
                location=ModelLocation(root="run", path=("run_id",)),
                details={"run_id": run_id},
            )
        ]
    )


def _validate_ref(ref: str) -> None:
    path = PurePosixPath(ref)
    if not path.parts or path.is_absolute() or ".." in path.parts:
        raise CheckFailed(
            [
                Problem(
                    code="run.ref_path_escape",
                    impact=ProblemImpact.BLOCKING,
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.PERSISTENCE,
                    message="run ref must stay within the run directory",
                    location=ModelLocation(root="run_ref", path=("ref",)),
                    details={"ref": ref},
                )
            ]
        )


def _serialize_model(model: BaseModel, *, run_id: str, ref: str) -> bytes:
    try:
        return (
            json.dumps(
                model.model_dump(mode="json"),
                allow_nan=True,
                indent=2,
            )
            + "\n"
        ).encode()
    except (PydanticSerializationError, TypeError, ValueError) as error:
        raise _serialization_failure(run_id=run_id, ref=ref) from error


def _validate_model[TModel: BaseModel](
    content: bytes,
    model_type: type[TModel],
    *,
    run_id: str,
    ref: str,
    code: str,
    message: str,
) -> TModel:
    try:
        return model_type.model_validate_json(content)
    except (UnicodeError, ValidationError) as error:
        raise _integrity_failure(
            run_id=run_id,
            ref=ref,
            code=code,
            message=message,
        ) from error


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
            _problem(
                run_id=run_id,
                ref=ref,
                code=code,
                category=ProblemCategory.DATA_INTEGRITY,
                message=message,
            )
        ]
    )


def _problem(
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
