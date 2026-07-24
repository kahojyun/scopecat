"""SQLite metadata index backed by immutable content-addressed objects."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Generator, Iterable
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path, PurePosixPath
from typing import cast

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError

from scopecat.adapters.sqlite.object_store import (
    ImmutableObjectStore,
    ObjectCorruptError,
    ObjectNotFoundError,
    ObjectStoreError,
    StoredObject,
)
from scopecat.adapters.sqlite.run_schema import RUN_SCHEMA_SQL, RUN_SCHEMA_VERSION
from scopecat.kernel.errors import (
    CheckFailed,
    DataIntegrityError,
    NotFound,
    StorageError,
)
from scopecat.kernel.problems import (
    ModelLocation,
    ProblemCategory,
    ProblemPhase,
    StorageLocation,
    blocking_problem,
)
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import MeasurementDatasetAppend
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


@dataclass(frozen=True, slots=True)
class _PreparedRef:
    ref: str
    object: StoredObject


@dataclass(frozen=True, slots=True)
class PreparedTerminalCommit:
    """Immutable terminal objects prepared before the database write lock."""

    commit: TerminalRunCommit
    refs: tuple[_PreparedRef, ...]


@dataclass(frozen=True, slots=True)
class PreparedRunSkeleton:
    """Immutable admission objects prepared before the database write lock."""

    manifest: RunManifest
    refs: tuple[_PreparedRef, ...]
    manifest_digest: str


class SQLiteRunRepository:
    """Run refs in SQLite, with values in a SHA-256 object directory."""

    def __init__(
        self,
        database: str | Path,
        objects: str | Path,
        *,
        busy_timeout_seconds: float = 5,
    ) -> None:
        self.database = Path(database)
        self.objects = ImmutableObjectStore(objects)
        self._busy_timeout_seconds = busy_timeout_seconds

    def bootstrap(self) -> None:
        """Create the current run-index schema without migration behavior."""

        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            self.objects.bootstrap()
            with closing(self._connect()) as connection:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.executescript(RUN_SCHEMA_SQL)
                row = _one(
                    connection.execute(
                        """
                        SELECT version FROM run_repository_schema
                        WHERE singleton = 1
                        """
                    )
                )
        except (OSError, sqlite3.Error) as error:
            raise _storage_failure(ref="run-repository") from error
        version = None if row is None else _integer(row, "version")
        if version != RUN_SCHEMA_VERSION:
            raise _integrity_failure(
                ref="run-repository",
                code="storage.schema_unsupported",
                message=f"unsupported run repository schema version: {version}",
            )

    def exists(self, run_id: str, ref: str) -> bool:
        _validate_identity(run_id, ref)
        prefix = f"{ref}/"
        try:
            with closing(self._connect()) as connection:
                row = _one(
                    connection.execute(
                        """
                        SELECT 1 AS present FROM run_repository_refs
                        WHERE run_id = ?
                          AND (
                              ref = ?
                              OR substr(ref, 1, ?) = ?
                          )
                        LIMIT 1
                        """,
                        (run_id, ref, len(prefix), prefix),
                    )
                )
        except sqlite3.Error as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        return row is not None

    def read_manifest(self, run_id: str) -> RunManifest:
        _validate_run_id(run_id)
        try:
            with closing(self._connect()) as connection:
                return self.read_manifest_in_transaction(connection, run_id)
        except sqlite3.Error as error:
            raise _storage_failure(run_id=run_id, ref=MANIFEST_REF) from error

    def read_manifest_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> RunManifest:
        """Read a manifest through an existing daemon transaction."""

        _validate_run_id(run_id)
        return self._read_manifest_with_connection(connection, run_id)

    def write_manifest(self, manifest: RunManifest) -> None:
        _validate_run_id(manifest.run_id)
        try:
            with self._transaction() as connection:
                self.write_manifest_in_transaction(connection, manifest)
        except sqlite3.Error as error:
            raise _storage_failure(
                run_id=manifest.run_id,
                ref=MANIFEST_REF,
            ) from error

    def write_manifest_in_transaction(
        self,
        connection: sqlite3.Connection,
        manifest: RunManifest,
    ) -> None:
        """Publish a manifest through an existing daemon write transaction."""

        prepared = self._prepare_model(
            manifest.run_id,
            MANIFEST_REF,
            manifest,
        )
        self._publish_refs(connection, manifest.run_id, (prepared,))
        self._publish_manifest(connection, manifest, prepared.object.digest)

    def list_runs(self) -> list[RunManifest]:
        try:
            with closing(self._connect()) as connection:
                rows = _all(
                    connection.execute(
                        """
                        SELECT run_id FROM run_repository_manifests
                        ORDER BY created_at, run_id
                        """
                    )
                )
        except sqlite3.Error as error:
            raise _storage_failure(ref=MANIFEST_REF) from error
        return [self.read_manifest(_text(row, "run_id")) for row in rows]

    def write_run_skeleton(
        self,
        *,
        manifest: RunManifest,
        request: RunRequest | None,
        config: ConfigProfileSnapshot,
    ) -> None:
        prepared = self.prepare_run_skeleton(
            manifest=manifest,
            request=request,
            config=config,
        )
        try:
            with self._transaction() as connection:
                self.commit_run_skeleton_in_transaction(connection, prepared)
        except sqlite3.Error as error:
            raise _storage_failure(
                run_id=manifest.run_id,
                ref=MANIFEST_REF,
            ) from error

    def prepare_run_skeleton(
        self,
        *,
        manifest: RunManifest,
        request: RunRequest | None,
        config: ConfigProfileSnapshot,
    ) -> PreparedRunSkeleton:
        """Write immutable admission objects before acquiring the SQLite writer."""

        if manifest.lifecycle != "accepted":
            msg = "run skeleton manifest must be accepted"
            raise ValueError(msg)
        validate_run_config_provenance(manifest=manifest, config=config)
        run_id = manifest.run_id
        prepared = [
            self._prepare_model(
                run_id,
                CONFIG_PROFILE_SNAPSHOT_REF,
                config,
            )
        ]
        if request is not None:
            prepared.append(self._prepare_model(run_id, RUN_REQUEST_REF, request))
        manifest_ref = self._prepare_model(run_id, MANIFEST_REF, manifest)
        prepared.append(manifest_ref)
        return PreparedRunSkeleton(
            manifest=manifest,
            refs=tuple(prepared),
            manifest_digest=manifest_ref.object.digest,
        )

    def commit_run_skeleton_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedRunSkeleton,
    ) -> None:
        """Publish a prebuilt run skeleton in the caller's transaction."""

        self._publish_refs(connection, prepared.manifest.run_id, prepared.refs)
        self._publish_manifest(
            connection,
            prepared.manifest,
            prepared.manifest_digest,
        )

    def commit_terminal(self, commit: TerminalRunCommit) -> RunManifest:
        run_id = commit.manifest.run_id
        prepared = self.prepare_terminal_commit(commit)
        try:
            with self._transaction() as connection:
                return self.commit_prepared_terminal_in_transaction(
                    connection,
                    prepared,
                )
        except sqlite3.Error as error:
            raise _storage_failure(run_id=run_id, ref=MANIFEST_REF) from error

    def prepare_terminal_commit(
        self,
        commit: TerminalRunCommit,
    ) -> PreparedTerminalCommit:
        """Write immutable terminal payloads before acquiring the SQLite writer."""

        run_id = commit.manifest.run_id
        refs = [
            self._prepare_model(run_id, write.ref, write.value)
            for write in commit.models
        ]
        refs.extend(
            self._prepare_jsonl(run_id, write.ref, write.records)
            for write in commit.record_sets
        )
        return PreparedTerminalCommit(commit=commit, refs=tuple(refs))

    def commit_terminal_in_transaction(
        self,
        connection: sqlite3.Connection,
        commit: TerminalRunCommit,
    ) -> RunManifest:
        """Prepare and publish a terminal commit in the caller's transaction."""

        return self.commit_prepared_terminal_in_transaction(
            connection,
            self.prepare_terminal_commit(commit),
        )

    def commit_prepared_terminal_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedTerminalCommit,
    ) -> RunManifest:
        """Publish prepared terminal refs without managing the transaction.

        Reading current through the write transaction preserves content published
        by an earlier serialized writer.
        """

        commit = prepared.commit
        run_id = commit.manifest.run_id
        current = self._read_manifest_with_connection(connection, run_id)
        manifest = commit.manifest.model_copy(
            update={
                "contents": upsert_contents(
                    current.contents,
                    commit.manifest.contents,
                )
            }
        )
        manifest_ref = self._prepare_model(run_id, MANIFEST_REF, manifest)
        self._publish_refs(connection, run_id, (*prepared.refs, manifest_ref))
        self._publish_manifest(
            connection,
            manifest,
            manifest_ref.object.digest,
        )
        return manifest

    def read_config_profile_snapshot(self, run_id: str) -> ConfigProfileSnapshot:
        manifest = self.read_manifest(run_id)
        config = self.read_model(
            run_id,
            CONFIG_PROFILE_SNAPSHOT_REF,
            ConfigProfileSnapshot,
        )
        validate_run_config_provenance(manifest=manifest, config=config)
        return config

    def read_model[TModel: BaseModel](
        self,
        run_id: str,
        ref: str,
        model_type: type[TModel],
    ) -> TModel:
        content = self._read_ref(run_id, ref)
        try:
            return model_type.model_validate_json(content)
        except ValidationError as error:
            raise _invalid_ref(run_id, ref) from error

    def write_model(self, run_id: str, ref: str, model: BaseModel) -> None:
        self._write_prepared(run_id, self._prepare_model(run_id, ref, model))

    def write_model_if_absent(
        self,
        run_id: str,
        ref: str,
        model: BaseModel,
    ) -> bool:
        prepared = self._prepare_model(run_id, ref, model)
        try:
            with self._transaction() as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO run_repository_refs(run_id, ref, digest, size)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(run_id, ref) DO NOTHING
                    """,
                    (
                        run_id,
                        ref,
                        prepared.object.digest,
                        prepared.object.size,
                    ),
                )
                return cursor.rowcount == 1
        except sqlite3.Error as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error

    def read_jsonl[TModel: BaseModel](
        self,
        run_id: str,
        ref: str,
        model_type: type[TModel],
    ) -> list[TModel]:
        try:
            return [
                model_type.model_validate_json(line)
                for line in self.read_text(run_id, ref).splitlines()
                if line.strip()
            ]
        except ValidationError as error:
            raise _invalid_ref(run_id, ref) from error

    def read_measurement_records(
        self,
        run_id: str,
        ref: str,
    ) -> list[MeasurementRecord]:
        _validate_identity(run_id, ref)
        if self._digest(run_id, ref) is not None:
            return self.read_jsonl(run_id, ref, MeasurementRecord)
        prefix = f"{ref}/chunks/"
        try:
            with closing(self._connect()) as connection:
                rows = _all(
                    connection.execute(
                        """
                        SELECT ref FROM run_repository_refs
                        WHERE run_id = ? AND substr(ref, 1, ?) = ?
                        ORDER BY ref
                        """,
                        (run_id, len(prefix), prefix),
                    )
                )
        except sqlite3.Error as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        return [
            record
            for row in rows
            for record in self.read_model(
                run_id,
                _text(row, "ref"),
                MeasurementDatasetAppend,
            ).records
        ]

    def write_jsonl(
        self,
        run_id: str,
        ref: str,
        records: Iterable[BaseModel],
    ) -> None:
        self._write_prepared(run_id, self._prepare_jsonl(run_id, ref, records))

    def read_text(self, run_id: str, ref: str) -> str:
        content = self._read_ref(run_id, ref)
        try:
            return content.decode()
        except UnicodeError as error:
            raise _invalid_ref(run_id, ref) from error

    def read_bytes(self, run_id: str, ref: str) -> bytes:
        return self._read_ref(run_id, ref)

    def write_text(self, run_id: str, ref: str, content: str) -> None:
        if content and not content.endswith("\n"):
            content = f"{content}\n"
        self.write_bytes(run_id, ref, content.encode())

    def write_bytes(self, run_id: str, ref: str, content: bytes) -> None:
        _validate_identity(run_id, ref)
        try:
            stored = self.objects.put(content)
        except ObjectStoreError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        self._write_prepared(run_id, _PreparedRef(ref=ref, object=stored))

    def _prepare_model(
        self,
        run_id: str,
        ref: str,
        model: BaseModel,
    ) -> _PreparedRef:
        _validate_identity(run_id, ref)
        try:
            content = _encode_model(model) + b"\n"
            stored = self.objects.put(content)
        except ObjectStoreError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        except (PydanticSerializationError, TypeError, ValueError) as error:
            raise _serialization_failure(run_id, ref) from error
        return _PreparedRef(ref=ref, object=stored)

    def _prepare_jsonl(
        self,
        run_id: str,
        ref: str,
        records: Iterable[BaseModel],
    ) -> _PreparedRef:
        _validate_identity(run_id, ref)
        try:
            content = b"".join(_encode_model(record) + b"\n" for record in records)
            stored = self.objects.put(content)
        except ObjectStoreError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        except (PydanticSerializationError, TypeError, ValueError) as error:
            raise _serialization_failure(run_id, ref) from error
        return _PreparedRef(ref=ref, object=stored)

    def _write_prepared(self, run_id: str, prepared: _PreparedRef) -> None:
        try:
            with self._transaction() as connection:
                self._publish_refs(connection, run_id, (prepared,))
        except sqlite3.Error as error:
            raise _storage_failure(run_id=run_id, ref=prepared.ref) from error

    @staticmethod
    def _publish_refs(
        connection: sqlite3.Connection,
        run_id: str,
        prepared: Iterable[_PreparedRef],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO run_repository_refs(run_id, ref, digest, size)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(run_id, ref) DO UPDATE SET
                digest = excluded.digest,
                size = excluded.size
            """,
            [
                (run_id, item.ref, item.object.digest, item.object.size)
                for item in prepared
            ],
        )

    @staticmethod
    def _publish_manifest(
        connection: sqlite3.Connection,
        manifest: RunManifest,
        digest: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO run_repository_manifests(run_id, digest, created_at)
            VALUES (?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                digest = excluded.digest,
                created_at = excluded.created_at
            """,
            (
                manifest.run_id,
                digest,
                manifest.created_at.astimezone(UTC).isoformat(),
            ),
        )

    def _read_ref(self, run_id: str, ref: str) -> bytes:
        _validate_identity(run_id, ref)
        digest = self._digest(run_id, ref)
        if digest is None:
            raise _integrity_failure(
                run_id=run_id,
                ref=ref,
                code="run.ref_missing",
                message="run is missing a referenced durable record",
            )
        return self._read_object(digest, run_id=run_id, ref=ref)

    def _read_manifest_with_connection(
        self,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> RunManifest:
        row = _one(
            connection.execute(
                """
                SELECT digest FROM run_repository_manifests
                WHERE run_id = ?
                """,
                (run_id,),
            )
        )
        if row is None:
            raise NotFound(
                [
                    blocking_problem(
                        "run.not_found",
                        "run was not found",
                        category=ProblemCategory.NOT_FOUND,
                        phase=ProblemPhase.PERSISTENCE,
                        location=StorageLocation(
                            run_id=run_id,
                            ref=MANIFEST_REF,
                        ),
                    )
                ]
            )
        content = self._read_object(
            _text(row, "digest"),
            run_id=run_id,
            ref=MANIFEST_REF,
        )
        try:
            return RunManifest.model_validate_json(content)
        except ValidationError as error:
            raise _integrity_failure(
                run_id=run_id,
                ref=MANIFEST_REF,
                code="run.manifest_invalid",
                message="run manifest does not match its durable schema",
            ) from error

    def _digest(self, run_id: str, ref: str) -> str | None:
        try:
            with closing(self._connect()) as connection:
                row = _one(
                    connection.execute(
                        """
                        SELECT digest FROM run_repository_refs
                        WHERE run_id = ? AND ref = ?
                        """,
                        (run_id, ref),
                    )
                )
        except sqlite3.Error as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        return None if row is None else _text(row, "digest")

    def _read_object(self, digest: str, *, run_id: str, ref: str) -> bytes:
        try:
            return self.objects.read(digest)
        except (ObjectNotFoundError, ObjectCorruptError) as error:
            raise _invalid_ref(run_id, ref) from error
        except ObjectStoreError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error

    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection]:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.database,
            isolation_level=None,
            timeout=self._busy_timeout_seconds,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection


def _encode_model(model: BaseModel) -> bytes:
    return json.dumps(
        model.model_dump(mode="json"),
        allow_nan=True,
        separators=(",", ":"),
    ).encode()


def _validate_identity(run_id: str, ref: str) -> None:
    _validate_run_id(run_id)
    relative = PurePosixPath(ref)
    if not relative.parts or relative.is_absolute() or ".." in relative.parts:
        raise CheckFailed(
            [
                blocking_problem(
                    "run.ref_path_escape",
                    "run ref must stay within the run directory",
                    category=ProblemCategory.INVALID_INPUT,
                    phase=ProblemPhase.PERSISTENCE,
                    location=ModelLocation(root="run_ref", path=("ref",)),
                    details={"ref": ref},
                )
            ]
        )


def _validate_run_id(run_id: str) -> None:
    if _SAFE_RUN_ID.fullmatch(run_id):
        return
    raise CheckFailed(
        [
            blocking_problem(
                "run.id_invalid",
                "run id is not safe for storage access",
                category=ProblemCategory.INVALID_INPUT,
                phase=ProblemPhase.PERSISTENCE,
                location=ModelLocation(root="run", path=("run_id",)),
                details={"run_id": run_id},
            )
        ]
    )


def _serialization_failure(run_id: str, ref: str) -> DataIntegrityError:
    return _integrity_failure(
        run_id=run_id,
        ref=ref,
        code="run.ref_not_serializable",
        message="run record cannot be represented by the durable format",
    )


def _invalid_ref(run_id: str, ref: str) -> DataIntegrityError:
    return _integrity_failure(
        run_id=run_id,
        ref=ref,
        code="run.ref_invalid",
        message="run record does not match its durable schema",
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
            blocking_problem(
                code,
                message,
                category=ProblemCategory.DATA_INTEGRITY,
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(run_id=run_id, ref=ref),
            )
        ]
    )


def _storage_failure(*, ref: str, run_id: str | None = None) -> StorageError:
    return StorageError(
        [
            blocking_problem(
                "storage.operation_failed",
                "storage could not complete the run repository operation",
                category=ProblemCategory.STORAGE,
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(run_id=run_id, ref=ref),
            )
        ]
    )


def _one(cursor: sqlite3.Cursor) -> sqlite3.Row | None:
    return cast("sqlite3.Row | None", cursor.fetchone())


def _all(cursor: sqlite3.Cursor) -> list[sqlite3.Row]:
    return cast("list[sqlite3.Row]", cursor.fetchall())


def _text(row: sqlite3.Row, column: str) -> str:
    return cast("str", row[column])


def _integer(row: sqlite3.Row, column: str) -> int:
    return cast("int", row[column])
