"""SQLite persistence for saved analyses (standard-library driver, no ORM).

Choices that matter for a project like this:

* one connection per operation, opened and closed inside a context manager, so
  FastAPI's thread pool never shares a connection across threads;
* WAL journal + busy timeout so concurrent reads and a write do not collide;
* the full result is stored as JSON (single source of truth) while a handful of
  summary columns are denormalised for listing without parsing every document;
* schema creation is idempotent, so restarting the container keeps projects.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from app.config import get_settings
from app.schemas.analysis import (
    AnalysisRequest,
    AnalysisResult,
    ProjectCreateRequest,
    ProjectDetail,
    ProjectSummary,
)
from app.schemas.common import EngineMode, ProjectKind, SCHEMA_VERSION

logger = logging.getLogger("nyx.storage")

SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        engine_mode TEXT NOT NULL,
        schema_version TEXT NOT NULL,
        application_type TEXT NOT NULL,
        preferred_provider TEXT,
        suitability_score REAL NOT NULL,
        suitability_outcome TEXT NOT NULL,
        expected_users INTEGER,
        component_count INTEGER NOT NULL DEFAULT 0,
        finding_count INTEGER NOT NULL DEFAULT 0,
        excerpt TEXT NOT NULL DEFAULT '',
        requirements_json TEXT NOT NULL,
        options_json TEXT NOT NULL,
        result_json TEXT NOT NULL,
        notes TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects (updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_projects_kind ON projects (kind, updated_at DESC)",
    """
    CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
]


class ProjectNotFound(Exception):
    pass


class ProjectStoreError(Exception):
    pass


class ProjectStore:
    def __init__(self, db_path: str | Path | None = None) -> None:
        settings = get_settings()
        self.db_path = str(db_path or settings.db_path)
        self._write_lock = threading.Lock()
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._shared: sqlite3.Connection | None = None
        self._init_schema()

    # ------------------------------------------------------------- plumbing

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        if self.db_path == ":memory:":
            # A single shared connection keeps an in-memory database alive for the
            # lifetime of the store (used by tests); access is guarded by a lock.
            if self._shared is None:
                self._shared = self._new_connection()
            yield self._shared
            return
        connection = self._new_connection()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        if self.db_path != ":memory:":
            connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.isolation_level = "DEFERRED"
        return connection

    def _init_schema(self) -> None:
        with self.connect() as connection:
            for statement in SCHEMA_STATEMENTS:
                connection.execute(statement)
            connection.execute(
                "INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)",
                ("schema_version", SCHEMA_VERSION),
            )

    def close(self) -> None:
        if self._shared is not None:
            self._shared.close()
            self._shared = None

    # ------------------------------------------------------------------ write

    def create(self, payload: ProjectCreateRequest, result: AnalysisResult) -> ProjectDetail:
        """Persist an analysis produced from `payload`, keyed by a fresh id."""
        return self.save_result(
            result,
            project_id=f"prj-{uuid4().hex[:12]}",
            name=payload.name or result.title,
            kind=ProjectKind.USER,
        )

    def save_result(
        self,
        result: AnalysisResult,
        *,
        project_id: str | None = None,
        kind: ProjectKind = ProjectKind.USER,
        name: str | None = None,
        notes: str | None = None,
    ) -> ProjectDetail:
        """Insert a pre-computed result (used by the example seed and re-analysis)."""
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        target = project_id or f"prj-{uuid4().hex[:12]}"
        proposed = result.architecture(result.primary_view) or (result.architectures[-1] if result.architectures else None)
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """
                INSERT INTO projects (
                    id, name, kind, engine_mode, schema_version, application_type, preferred_provider,
                    suitability_score, suitability_outcome, expected_users, component_count, finding_count,
                    excerpt, requirements_json, options_json, result_json, notes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    result_json = excluded.result_json,
                    requirements_json = excluded.requirements_json,
                    suitability_score = excluded.suitability_score,
                    suitability_outcome = excluded.suitability_outcome,
                    component_count = excluded.component_count,
                    finding_count = excluded.finding_count,
                    excerpt = excluded.excerpt,
                    updated_at = excluded.updated_at
                """,
                (
                    target,
                    (name or result.title).strip()[:90],
                    kind.value,
                    result.engine_mode.value,
                    result.schema_version,
                    result.application.application_type.value,
                    result.application.preferred_provider.value if result.application.preferred_provider else None,
                    result.suitability.score,
                    result.suitability.outcome.value,
                    result.application.expected_users,
                    len(proposed.components) if proposed else 0,
                    len(result.security.findings),
                    _excerpt(result),
                    json.dumps(result.application.model_dump(mode="json"), ensure_ascii=False),
                    json.dumps({"providers": [p.value for p in result.providers]}, ensure_ascii=False),
                    json.dumps(result.to_json_dict(), ensure_ascii=False),
                    notes,
                    now,
                    now,
                ),
            )
        return self.get(target)

    def update(self, project_id: str, *, name: str | None = None, notes: str | None = None) -> ProjectDetail:
        current = self.get(project_id)  # raises when missing
        assignments: list[str] = []
        parameters: list[Any] = []
        if name is not None:
            assignments.append("name = ?")
            parameters.append(name.strip()[:90])
            stored = json.loads(self._raw_result_json(project_id))
            stored["title"] = name.strip()[:90]
            assignments.append("result_json = ?")
            parameters.append(json.dumps(stored, ensure_ascii=False))
        if notes is not None:
            assignments.append("notes = ?")
            parameters.append(notes.strip()[:2000])
        if not assignments:
            return current
        assignments.append("updated_at = ?")
        parameters.append(datetime.now(timezone.utc).isoformat(timespec="seconds"))
        parameters.append(project_id)
        with self._write_lock, self.connect() as connection:
            connection.execute(
                f"UPDATE projects SET {', '.join(assignments)} WHERE id = ?",  # noqa: S608 - identifiers are fixed above
                parameters,
            )
        return self.get(project_id)

    def replace_result(self, project_id: str, result: AnalysisResult) -> ProjectDetail:
        with self._write_lock, self.connect() as connection:
            connection.execute(
                """
                UPDATE projects
                   SET result_json = ?, requirements_json = ?, engine_mode = ?, suitability_score = ?,
                       suitability_outcome = ?, component_count = ?, finding_count = ?, excerpt = ?,
                       updated_at = ?
                 WHERE id = ?
                """,
                (
                    json.dumps(result.to_json_dict(), ensure_ascii=False),
                    json.dumps(result.application.model_dump(mode="json"), ensure_ascii=False),
                    result.engine_mode.value,
                    result.suitability.score,
                    result.suitability.outcome.value,
                    len(result.architectures[-1].components) if result.architectures else 0,
                    len(result.security.findings),
                    _excerpt(result),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    project_id,
                ),
            )
        return self.get(project_id)

    def delete(self, project_id: str) -> bool:
        with self._write_lock, self.connect() as connection:
            cursor = connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------- read

    def list(self, *, limit: int = 50, offset: int = 0, kind: str | None = None) -> list[ProjectSummary]:
        clause = ""
        parameters: list[Any] = []
        if kind:
            clause = "WHERE kind = ?"
            parameters.append(kind)
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM projects
                {clause}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, max(1, min(limit, 200)), max(0, offset)],
            ).fetchall()
        return [self._summary(row) for row in rows]

    def get(self, project_id: str) -> ProjectDetail:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ProjectNotFound(project_id)
        return self._detail(row)

    def get_result(self, project_id: str) -> AnalysisResult:
        return self.get(project_id).result

    def _raw_result_json(self, project_id: str) -> str:
        with self.connect() as connection:
            row = connection.execute("SELECT result_json FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            raise ProjectNotFound(project_id)
        return str(row["result_json"])

    def count(self, *, kind: str | None = None) -> int:
        with self.connect() as connection:
            if kind:
                return int(connection.execute("SELECT COUNT(*) AS n FROM projects WHERE kind = ?", (kind,)).fetchone()["n"])
            return int(connection.execute("SELECT COUNT(*) AS n FROM projects").fetchone()["n"])

    def stats(self) -> dict[str, Any]:
        with self.connect() as connection:
            totals = connection.execute(
                "SELECT COUNT(*) AS n, MAX(updated_at) AS newest, MIN(created_at) AS oldest FROM projects"
            ).fetchone()
            outcomes = connection.execute(
                "SELECT suitability_outcome, COUNT(*) AS n FROM projects GROUP BY suitability_outcome"
            ).fetchall()
            types = connection.execute(
                "SELECT application_type, COUNT(*) AS n FROM projects GROUP BY application_type ORDER BY n DESC"
            ).fetchall()
            examples = connection.execute("SELECT COUNT(*) AS n FROM projects WHERE kind = ?", (ProjectKind.EXAMPLE.value,)).fetchone()
            user = connection.execute("SELECT COUNT(*) AS n FROM projects WHERE kind = ?", (ProjectKind.USER.value,)).fetchone()
            avg = connection.execute("SELECT AVG(suitability_score) AS avg_score FROM projects WHERE kind = ?", (ProjectKind.USER.value,)).fetchone()
        return {
            "total": int(totals["n"] or 0),
            "user_projects": int(user["n"] or 0),
            "example_projects": int(examples["n"] or 0),
            "newest": totals["newest"],
            "oldest": totals["oldest"],
            "outcomes": {row["suitability_outcome"]: int(row["n"]) for row in outcomes},
            "application_types": {row["application_type"]: int(row["n"]) for row in types},
            "average_user_score": round(float(avg["avg_score"]), 1) if avg["avg_score"] is not None else None,
        }

    def exists(self, project_id: str) -> bool:
        with self.connect() as connection:
            return connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is not None

    # ----------------------------------------------------------- row mapping

    def _summary(self, row: sqlite3.Row) -> ProjectSummary:
        return ProjectSummary(
            id=row["id"],
            name=row["name"],
            kind=ProjectKind(row["kind"]),
            engine_mode=EngineMode(row["engine_mode"]),
            application_type=row["application_type"],
            preferred_provider=row["preferred_provider"],
            suitability_score=float(row["suitability_score"]),
            suitability_outcome=row["suitability_outcome"],
            expected_users=row["expected_users"],
            component_count=int(row["component_count"]),
            finding_count=int(row["finding_count"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            excerpt=row["excerpt"] or "",
        )

    def _detail(self, row: sqlite3.Row) -> ProjectDetail:
        payload = json.loads(row["result_json"])
        result = AnalysisResult.model_validate(payload)
        return ProjectDetail(
            id=row["id"],
            name=row["name"],
            kind=ProjectKind(row["kind"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            requirements=result.application,
            result=result,
        )


def _excerpt(result: AnalysisResult) -> str:
    text = result.application.description
    return (text[:177] + "…") if len(text) > 178 else text


_store: ProjectStore | None = None
_store_lock = threading.Lock()


def get_store() -> ProjectStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = ProjectStore()
    return _store


def reset_store_for_tests(store: ProjectStore | None) -> None:
    """Test hook: swap the process-wide store (pass None to rebuild lazily)."""
    global _store
    with _store_lock:
        if _store is not None and _store is not store:
            _store.close()
        _store = store


def build_request(requirements_json: dict[str, Any]) -> AnalysisRequest:
    return AnalysisRequest.model_validate({"requirements": requirements_json})


__all__ = [
    "ProjectNotFound",
    "ProjectStore",
    "ProjectStoreError",
    "build_request",
    "get_store",
    "reset_store_for_tests",
]
