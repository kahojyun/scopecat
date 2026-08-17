"""SQLite index and immutable objects for project-level analyses."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from pydantic import BaseModel, ValidationError
from pydantic_core import PydanticSerializationError
from scopecat.analysis.repository import (
    AnalysisPublication,
    AnalysisPublicationManifest,
    AnalysisPublicationPage,
    AnalysisPublicationSummary,
)
from scopecat.kernel.errors import Conflict, DataIntegrityError, NotFound, StorageError
from scopecat.kernel.problems import (
    ModelLocation,
    ProblemPhase,
    StorageLocation,
    problem,
)

from scopecat_server.storage.sqlite.connection import SQLiteDatabase
from scopecat_server.storage.sqlite.object_store import (
    ImmutableObjectStore,
    ObjectCorruptError,
    ObjectNotFoundError,
    ObjectStoreError,
    StoredObject,
)

_SAFE_RECORD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass(frozen=True, slots=True)
class PreparedAnalysisPublication:
    """Immutable objects prepared before publishing their logical references."""

    publication: AnalysisPublication
    refs: tuple[tuple[str, StoredObject], ...]


class SQLiteAnalysisRepository:
    """Project analysis refs backed by the shared content-addressed store."""

    def __init__(self, database: SQLiteDatabase, objects: str | Path) -> None:
        self.sqlite = database
        self.objects = ImmutableObjectStore(objects)

    def list_summaries(
        self,
        *,
        limit: int,
        before: int | None,
    ) -> AnalysisPublicationPage:
        """Return one newest-first keyset page without reading content objects."""

        try:
            with self.sqlite.read_connection() as connection:
                if before is None:
                    rows = cast(
                        "list[sqlite3.Row]",
                        connection.execute(
                            """
                            SELECT sequence, manifest_json, title, analysis_key,
                                   revision, publication_hash, step_id,
                                   input_count, output_count
                            FROM analysis_publications
                            ORDER BY sequence DESC
                            LIMIT ?
                            """,
                            (limit + 1,),
                        ).fetchall(),
                    )
                else:
                    rows = cast(
                        "list[sqlite3.Row]",
                        connection.execute(
                            """
                            SELECT sequence, manifest_json, title, analysis_key,
                                   revision, publication_hash, step_id,
                                   input_count, output_count
                            FROM analysis_publications
                            WHERE sequence < ?
                            ORDER BY sequence DESC
                            LIMIT ?
                            """,
                            (before, limit + 1),
                        ).fetchall(),
                    )
            selected = rows[:limit]
            return AnalysisPublicationPage(
                items=tuple(_summary(row) for row in selected),
                next_cursor=(
                    cast("int", selected[-1]["sequence"]) if len(rows) > limit else None
                ),
            )
        except (sqlite3.Error, ValidationError) as error:
            raise _storage_failure("analyses") from error

    def latest_manifest(
        self,
        analysis_key: str,
    ) -> AnalysisPublicationManifest | None:
        try:
            with self.sqlite.read_connection() as connection:
                row = cast(
                    "sqlite3.Row | None",
                    connection.execute(
                        """
                        SELECT manifest_json
                        FROM analysis_publications
                        WHERE analysis_key = ?
                        ORDER BY revision DESC
                        LIMIT 1
                        """,
                        (analysis_key,),
                    ).fetchone(),
                )
            return (
                None
                if row is None
                else AnalysisPublicationManifest.model_validate_json(
                    cast("str", row["manifest_json"])
                )
            )
        except (sqlite3.Error, ValidationError) as error:
            raise _storage_failure(analysis_key) from error

    def read_manifest(self, record_id: str) -> AnalysisPublicationManifest:
        _validate_identity(record_id, "record.json")
        try:
            with self.sqlite.read_connection() as connection:
                row = cast(
                    "sqlite3.Row | None",
                    connection.execute(
                        """
                        SELECT manifest_json
                        FROM analysis_publications
                        WHERE record_id = ?
                        """,
                        (record_id,),
                    ).fetchone(),
                )
            if row is None:
                raise _not_found(record_id)
            return AnalysisPublicationManifest.model_validate_json(
                cast("str", row["manifest_json"])
            )
        except (sqlite3.Error, ValidationError) as error:
            raise _storage_failure(record_id) from error

    def publish(self, publication: AnalysisPublication) -> None:
        prepared = self.prepare_publication(publication)
        try:
            with self.sqlite.write_transaction() as connection:
                self.publish_prepared_in_transaction(connection, prepared)
        except Conflict, NotFound, DataIntegrityError:
            raise
        except sqlite3.Error as error:
            raise _storage_failure(publication.manifest.record.id) from error

    def prepare_publication(
        self,
        publication: AnalysisPublication,
    ) -> PreparedAnalysisPublication:
        """Write immutable objects without publishing their logical refs."""

        manifest = publication.manifest
        record_id = manifest.record.id
        prepared: list[tuple[str, StoredObject]] = []
        try:
            for write in publication.models:
                _validate_identity(record_id, write.ref)
                prepared.append(
                    (write.ref, self.objects.put(_encode_model(write.value)))
                )
            for write in publication.bytes:
                _validate_identity(record_id, write.ref)
                prepared.append((write.ref, self.objects.put(write.content)))
            return PreparedAnalysisPublication(
                publication=publication,
                refs=tuple(prepared),
            )
        except Conflict, NotFound:
            raise
        except (
            OSError,
            ObjectStoreError,
            PydanticSerializationError,
            TypeError,
            ValueError,
        ) as error:
            raise _storage_failure(record_id) from error

    def publish_prepared_in_transaction(
        self,
        connection: sqlite3.Connection,
        prepared: PreparedAnalysisPublication,
    ) -> bool:
        """Publish prepared refs through the caller's SQLite transaction."""

        publication = prepared.publication
        manifest = publication.manifest
        record_id = manifest.record.id
        manifest_json = manifest.model_dump_json()
        try:
            existing = cast(
                "sqlite3.Row | None",
                connection.execute(
                    """
                    SELECT manifest_json
                    FROM analysis_publications
                    WHERE record_id = ?
                    """,
                    (record_id,),
                ).fetchone(),
            )
            if existing is not None:
                if existing["manifest_json"] == manifest_json:
                    return False
                raise _conflict(record_id)
            connection.execute(
                """
                INSERT INTO analysis_publications(
                    record_id, analysis_key, revision, publication_hash,
                    title, step_id, input_count, output_count, manifest_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record_id,
                    publication.analysis_key,
                    publication.revision,
                    publication.publication_hash,
                    publication.title,
                    publication.step_id,
                    publication.input_count,
                    publication.output_count,
                    manifest_json,
                ),
            )
            connection.executemany(
                """
                INSERT INTO analysis_repository_refs(record_id, ref, digest)
                VALUES (?, ?, ?)
                """,
                ((record_id, ref, stored.digest) for ref, stored in prepared.refs),
            )
            return True
        except Conflict, NotFound:
            raise
        except sqlite3.IntegrityError as error:
            raise _conflict(record_id) from error
        except sqlite3.Error as error:
            raise _storage_failure(record_id) from error

    def read_model[TModel: BaseModel](
        self,
        record_id: str,
        ref: str,
        model_type: type[TModel],
    ) -> TModel:
        try:
            return model_type.model_validate_json(self.read_bytes(record_id, ref))
        except ValidationError as error:
            raise _invalid_ref(record_id, ref) from error

    def read_bytes(self, record_id: str, ref: str) -> bytes:
        _validate_identity(record_id, ref)
        try:
            with self.sqlite.read_connection() as connection:
                row = cast(
                    "sqlite3.Row | None",
                    connection.execute(
                        """
                        SELECT digest FROM analysis_repository_refs
                        WHERE record_id = ? AND ref = ?
                        """,
                        (record_id, ref),
                    ).fetchone(),
                )
            if row is None:
                raise _invalid_ref(record_id, ref)
            return self.objects.read(cast("str", row["digest"]))
        except DataIntegrityError:
            raise
        except (ObjectNotFoundError, ObjectCorruptError) as error:
            raise _invalid_ref(record_id, ref) from error
        except (sqlite3.Error, ObjectStoreError) as error:
            raise _storage_failure(record_id) from error


def _encode_model(model: BaseModel) -> bytes:
    return (
        json.dumps(
            model.model_dump(mode="json"),
            allow_nan=True,
            separators=(",", ":"),
        ).encode()
        + b"\n"
    )


def _summary(row: sqlite3.Row) -> AnalysisPublicationSummary:
    manifest = AnalysisPublicationManifest.model_validate_json(
        cast("str", row["manifest_json"])
    )
    return AnalysisPublicationSummary(
        record=manifest.record,
        title=cast("str", row["title"]),
        analysis_key=cast("str", row["analysis_key"]),
        revision=cast("int", row["revision"]),
        publication_hash=cast("str", row["publication_hash"]),
        step_id=cast("str | None", row["step_id"]),
        input_count=cast("int", row["input_count"]),
        output_count=cast("int", row["output_count"]),
    )


def _validate_identity(record_id: str, ref: str) -> None:
    relative = PurePosixPath(ref)
    if (
        _SAFE_RECORD_ID.fullmatch(record_id) is None
        or not relative.parts
        or relative.is_absolute()
        or ".." in relative.parts
    ):
        raise DataIntegrityError(
            [
                problem(
                    "analysis.identity_invalid",
                    "analysis record id and ref must be safe storage identities",
                    phase=ProblemPhase.PERSISTENCE,
                    location=ModelLocation(root="analysis_ref", path=("ref",)),
                )
            ]
        )


def _not_found(record_id: str) -> NotFound:
    return NotFound(
        [
            problem(
                "analysis.not_found",
                "analysis publication was not found",
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(ref=f"analyses/{record_id}"),
            )
        ]
    )


def _conflict(record_id: str) -> Conflict:
    return Conflict(
        [
            problem(
                "analysis.publication_conflict",
                "analysis publication identity already contains different content",
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(ref=f"analyses/{record_id}"),
            )
        ]
    )


def _invalid_ref(record_id: str, ref: str) -> DataIntegrityError:
    return DataIntegrityError(
        [
            problem(
                "analysis.ref_invalid",
                "analysis content does not match its durable reference",
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(ref=f"analyses/{record_id}/{ref}"),
            )
        ]
    )


def _storage_failure(ref: str) -> StorageError:
    return StorageError(
        [
            problem(
                "storage.operation_failed",
                "storage could not complete the analysis repository operation",
                phase=ProblemPhase.PERSISTENCE,
                location=StorageLocation(ref=ref),
            )
        ]
    )


__all__ = ["SQLiteAnalysisRepository"]
