"""SQLite metadata index backed by immutable content-addressed objects."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import cast

from pydantic import BaseModel, TypeAdapter, ValidationError
from pydantic_core import PydanticSerializationError
from scopecat.kernel.errors import (
    CheckFailed,
    Conflict,
    DataIntegrityError,
    NotFound,
    StorageError,
)
from scopecat.kernel.problems import (
    ModelLocation,
    ProblemPhase,
    StorageLocation,
    problem,
)
from scopecat.kernel.run_outcome import RunOutcome
from scopecat.records.config import ConfigProfileSnapshot
from scopecat.records.content import ContentEntry
from scopecat.records.measurement import MeasurementRecord
from scopecat.records.measurement_recording import MeasurementDatasetHeader
from scopecat.records.run import RunConfigSource, RunManifest
from scopecat.runs.admission import RunSkeleton
from scopecat.runs.provenance import validate_run_config_provenance
from scopecat.runs.refs import (
    CONFIG_PROFILE_SNAPSHOT_REF,
    RUN_REQUEST_REF,
)
from scopecat.runs.repository import RunContentPublication, TerminalRunCommit

from scopecat_server.storage.sqlite.connection import SQLiteDatabase
from scopecat_server.storage.sqlite.object_store import (
    ImmutableObjectStore,
    ObjectCorruptError,
    ObjectNotFoundError,
    ObjectStoreError,
    StoredObject,
)

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_RUN_CONFIG_SOURCE: TypeAdapter[RunConfigSource] = TypeAdapter(RunConfigSource)


@dataclass(frozen=True, slots=True)
class _PreparedRef:
    ref: str
    object: StoredObject
    replace: bool = True


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


@dataclass(frozen=True, slots=True)
class PreparedContentPublication:
    """Immutable content objects prepared before metadata publication."""

    publication: RunContentPublication
    refs: tuple[_PreparedRef, ...]


class SQLiteRunRepository:
    """Relational run metadata with payloads in a SHA-256 object directory."""

    def __init__(
        self,
        database: SQLiteDatabase,
        objects: str | Path,
    ) -> None:
        self.sqlite = database
        self.database = database.path
        self.objects = ImmutableObjectStore(objects)

    def exists(self, run_id: str, ref: str) -> bool:
        _validate_identity(run_id, ref)
        prefix = f"{ref}/"
        try:
            with self.sqlite.read_connection() as connection:
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
            with self.sqlite.read_connection() as connection:
                return self.read_manifest_in_transaction(connection, run_id)
        except sqlite3.Error as error:
            raise _storage_failure(run_id=run_id) from error

    def read_manifest_in_transaction(
        self,
        connection: sqlite3.Connection,
        run_id: str,
    ) -> RunManifest:
        """Assemble the compatibility run projection in one transaction."""

        _validate_run_id(run_id)
        return self._read_manifest_with_connection(connection, run_id)

    def prepare_run_skeleton(self, skeleton: RunSkeleton) -> PreparedRunSkeleton:
        """Write immutable admission objects before acquiring the SQLite writer."""

        manifest = skeleton.manifest
        run_id = manifest.run_id
        prepared = [
            self._prepare_model(
                run_id,
                CONFIG_PROFILE_SNAPSHOT_REF,
                skeleton.config,
            ),
            self._prepare_model(run_id, RUN_REQUEST_REF, skeleton.request),
        ]
        return PreparedRunSkeleton(
            manifest=manifest,
            refs=tuple(prepared),
        )

    def commit_run_skeleton_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedRunSkeleton,
    ) -> None:
        """Publish a prebuilt run skeleton in the caller's transaction."""

        self._replace_run_projection(connection, prepared.manifest)
        self._publish_refs(connection, prepared.manifest.run_id, prepared.refs)

    def commit_terminal(self, commit: TerminalRunCommit) -> RunManifest:
        run_id = commit.run_id
        prepared = self.prepare_terminal_commit(commit)
        try:
            with self._transaction() as connection:
                return self.commit_prepared_terminal_in_transaction(
                    connection,
                    prepared,
                )
        except sqlite3.Error as error:
            raise _storage_failure(run_id=run_id) from error

    def prepare_terminal_commit(
        self,
        commit: TerminalRunCommit,
    ) -> PreparedTerminalCommit:
        """Write immutable terminal payloads before acquiring the SQLite writer."""

        run_id = commit.run_id
        refs = [
            self._prepare_model(run_id, write.ref, write.value)
            for write in commit.models
        ]
        return PreparedTerminalCommit(commit=commit, refs=tuple(refs))

    def commit_prepared_terminal_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedTerminalCommit,
    ) -> RunManifest:
        """Publish prepared terminal refs without managing the transaction.

        The first terminal outcome wins while independently published contents
        merge through relational uniqueness.
        """

        commit = prepared.commit
        run_id = commit.run_id
        self._require_run_row(connection, run_id)
        outcome = commit.outcome
        connection.execute(
            """
            INSERT INTO run_outcomes(
                run_id, result, certainty, finished_at, outcome_json
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO NOTHING
            """,
            (
                run_id,
                outcome.result,
                outcome.certainty,
                outcome.finished_at.isoformat(),
                _encode_model(outcome).decode(),
            ),
        )
        self._upsert_contents(connection, run_id, commit.contents)
        self._publish_refs(connection, run_id, prepared.refs)
        return self._read_manifest_with_connection(connection, run_id)

    def publish_content(
        self,
        publication: RunContentPublication,
    ) -> RunManifest:
        prepared = self.prepare_content_publication(publication)
        try:
            with self._transaction() as connection:
                return self.publish_prepared_content_in_transaction(
                    connection,
                    prepared,
                )
        except sqlite3.Error as error:
            raise _storage_failure(run_id=publication.run_id) from error

    def prepare_content_publication(
        self,
        publication: RunContentPublication,
    ) -> PreparedContentPublication:
        """Write immutable objects without publishing their logical refs."""

        run_id = publication.run_id
        refs = [
            replace(
                self._prepare_model(run_id, write.ref, write.value),
                replace=write.replace,
            )
            for write in publication.models
        ]
        refs.extend(
            self._prepare_bytes(
                run_id,
                write.ref,
                write.content,
                replace=write.replace,
            )
            for write in publication.bytes
        )
        return PreparedContentPublication(
            publication=publication,
            refs=tuple(refs),
        )

    def publish_prepared_content_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedContentPublication,
    ) -> RunManifest:
        """Publish prepared refs and content metadata in one transaction."""

        publication = prepared.publication
        run_id = publication.run_id
        self._require_run_row(connection, run_id)
        self._upsert_contents(connection, run_id, publication.entries)
        self._publish_refs(connection, run_id, prepared.refs)
        return self._read_manifest_with_connection(connection, run_id)

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

    def read_measurement_records(
        self,
        run_id: str,
        ref: str,
    ) -> list[MeasurementRecord]:
        from scopecat.measurements.recording_arrow import (
            MeasurementArrowCodecError,
            decode_measurement_append,
            measurement_dataset_schema_hash,
        )

        _validate_identity(run_id, ref)
        header = self.read_model(
            run_id,
            f"{ref}/header.json",
            MeasurementDatasetHeader,
        )
        dataset_schema_hash = measurement_dataset_schema_hash(header.dataset_schema)
        prefix = f"{ref}/chunks/"
        try:
            with self.sqlite.read_connection() as connection:
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
        records: list[MeasurementRecord] = []
        for row in rows:
            chunk_ref = _text(row, "ref")
            try:
                append = decode_measurement_append(
                    self.read_bytes(run_id, chunk_ref),
                    header.dataset_schema,
                    dataset_schema_hash=dataset_schema_hash,
                )
            except MeasurementArrowCodecError as error:
                raise _invalid_ref(run_id, chunk_ref) from error
            records.extend(append.records)
        return records

    def read_text(self, run_id: str, ref: str) -> str:
        content = self._read_ref(run_id, ref)
        try:
            return content.decode()
        except UnicodeError as error:
            raise _invalid_ref(run_id, ref) from error

    def read_bytes(self, run_id: str, ref: str) -> bytes:
        return self._read_ref(run_id, ref)

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

    def _prepare_bytes(
        self,
        run_id: str,
        ref: str,
        content: bytes,
        *,
        replace: bool = True,
    ) -> _PreparedRef:
        _validate_identity(run_id, ref)
        try:
            stored = self.objects.put(content)
        except ObjectStoreError as error:
            raise _storage_failure(run_id=run_id, ref=ref) from error
        return _PreparedRef(ref=ref, object=stored, replace=replace)

    @staticmethod
    def _publish_refs(
        connection: sqlite3.Connection,
        run_id: str,
        prepared: Iterable[_PreparedRef],
    ) -> None:
        for item in prepared:
            if item.replace:
                connection.execute(
                    """
                    INSERT INTO run_repository_refs(run_id, ref, digest)
                    VALUES (?, ?, ?)
                    ON CONFLICT(run_id, ref) DO UPDATE SET
                        digest = excluded.digest
                    """,
                    (run_id, item.ref, item.object.digest),
                )
                continue
            inserted = connection.execute(
                """
                INSERT INTO run_repository_refs(run_id, ref, digest)
                VALUES (?, ?, ?)
                ON CONFLICT(run_id, ref) DO NOTHING
                """,
                (run_id, item.ref, item.object.digest),
            )
            if inserted.rowcount == 1:
                continue
            existing = _one(
                connection.execute(
                    """
                    SELECT digest FROM run_repository_refs
                    WHERE run_id = ? AND ref = ?
                    """,
                    (run_id, item.ref),
                )
            )
            if existing is None or _text(existing, "digest") != item.object.digest:
                raise _ref_conflict(run_id, item.ref)

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
                SELECT runs.*, run_outcomes.outcome_json
                FROM runs
                LEFT JOIN run_outcomes USING (run_id)
                WHERE runs.run_id = ?
                """,
                (run_id,),
            )
        )
        if row is None:
            raise NotFound(
                [
                    problem(
                        "run.not_found",
                        "run was not found",
                        phase=ProblemPhase.PERSISTENCE,
                        location=StorageLocation(run_id=run_id),
                    )
                ]
            )
        content_rows = _all(
            connection.execute(
                """
                SELECT entry_json FROM run_contents
                WHERE run_id = ?
                ORDER BY sequence
                """,
                (run_id,),
            )
        )
        try:
            config_source_json = cast("str | None", row["config_source_json"])
            outcome_json = cast("str | None", row["outcome_json"])
            return RunManifest(
                run_id=run_id,
                created_at=datetime.fromisoformat(_text(row, "created_at")),
                config_content_hash=_text(row, "config_content_hash"),
                config_source=(
                    None
                    if config_source_json is None
                    else _RUN_CONFIG_SOURCE.validate_json(config_source_json)
                ),
                outcome=(
                    None
                    if outcome_json is None
                    else RunOutcome.model_validate_json(outcome_json)
                ),
                contents=tuple(
                    ContentEntry.model_validate_json(_text(item, "entry_json"))
                    for item in content_rows
                ),
            )
        except ValidationError as error:
            raise _integrity_failure(
                run_id=run_id,
                code="run.manifest_invalid",
                message="run metadata does not match its durable schema",
            ) from error

    @staticmethod
    def _require_run_row(connection: sqlite3.Connection, run_id: str) -> None:
        row = _one(
            connection.execute(
                "SELECT 1 AS present FROM runs WHERE run_id = ?",
                (run_id,),
            )
        )
        if row is None:
            raise NotFound(
                [
                    problem(
                        "run.not_found",
                        "run was not found",
                        phase=ProblemPhase.PERSISTENCE,
                        location=StorageLocation(run_id=run_id),
                    )
                ]
            )

    @staticmethod
    def _upsert_contents(
        connection: sqlite3.Connection,
        run_id: str,
        entries: Iterable[ContentEntry],
    ) -> None:
        connection.executemany(
            """
            INSERT INTO run_contents(
                run_id, role, content_id, kind, produced_by, entry_json
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, role, content_id) DO UPDATE SET
                kind = excluded.kind,
                produced_by = excluded.produced_by,
                entry_json = excluded.entry_json
            """,
            (
                (
                    run_id,
                    entry.role,
                    entry.id,
                    entry.kind,
                    entry.produced_by,
                    _encode_model(entry).decode(),
                )
                for entry in entries
            ),
        )

    def _replace_run_projection(
        self,
        connection: sqlite3.Connection,
        manifest: RunManifest,
    ) -> None:
        source = manifest.config_source
        connection.execute(
            """
            INSERT INTO runs(
                run_id, created_at, config_content_hash, config_source_json
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                created_at = excluded.created_at,
                config_content_hash = excluded.config_content_hash,
                config_source_json = excluded.config_source_json
            """,
            (
                manifest.run_id,
                manifest.created_at.isoformat(),
                manifest.config_content_hash,
                None if source is None else _encode_model(source).decode(),
            ),
        )
        connection.execute(
            "DELETE FROM run_outcomes WHERE run_id = ?",
            (manifest.run_id,),
        )
        if (outcome := manifest.outcome) is not None:
            connection.execute(
                """
                INSERT INTO run_outcomes(
                    run_id, result, certainty, finished_at, outcome_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    manifest.run_id,
                    outcome.result,
                    outcome.certainty,
                    outcome.finished_at.isoformat(),
                    _encode_model(outcome).decode(),
                ),
            )
        connection.execute(
            "DELETE FROM run_contents WHERE run_id = ?",
            (manifest.run_id,),
        )
        self._upsert_contents(connection, manifest.run_id, manifest.contents)

    def _digest(self, run_id: str, ref: str) -> str | None:
        try:
            with self.sqlite.read_connection() as connection:
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
        with self.sqlite.write_transaction() as connection:
            yield connection


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
                problem(
                    "run.ref_path_escape",
                    "run ref must stay within the run directory",
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
            problem(
                "run.id_invalid",
                "run id is not safe for storage access",
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


def _ref_conflict(run_id: str, ref: str) -> Conflict:
    return Conflict(
        [
            problem(
                "run.ref_conflict",
                "immutable run content already contains different data",
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(run_id=run_id, ref=ref),
            )
        ]
    )


def _integrity_failure(
    *,
    ref: str | None = None,
    code: str,
    message: str,
    run_id: str | None = None,
) -> DataIntegrityError:
    return DataIntegrityError(
        [
            problem(
                code,
                message,
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(run_id=run_id, ref=ref),
            )
        ]
    )


def _storage_failure(
    *,
    ref: str | None = None,
    run_id: str | None = None,
) -> StorageError:
    return StorageError(
        [
            problem(
                "storage.operation_failed",
                "storage could not complete the run repository operation",
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
