from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from .config import Settings


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        for directory in (settings.data_dir, settings.upload_dir, settings.audio_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.database = settings.data_dir / "voice-smiths.sqlite3"
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, chapter_index INTEGER NOT NULL,
                    chapter_title TEXT NOT NULL, status TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
                    total INTEGER NOT NULL, progress INTEGER NOT NULL DEFAULT 0, error TEXT,
                    audio_path TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, payload TEXT NOT NULL
                );
            """)
            for table in ("projects", "jobs"):
                columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
                if "tenant_id" not in columns:
                    connection.execute(f"ALTER TABLE {table} ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'legacy'")
                connection.execute(f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant ON {table}(tenant_id)")

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def save_project(self, project: dict[str, Any], tenant_id: str | None = None) -> dict[str, Any]:
        with self.connect() as connection:
            if tenant_id is None:
                existing = connection.execute("SELECT tenant_id FROM projects WHERE id=?", (project["id"],)).fetchone()
                tenant_id = existing["tenant_id"] if existing else "legacy"
            cursor = connection.execute(
                "INSERT INTO projects (id, title, created_at, payload, tenant_id) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title, payload=excluded.payload "
                "WHERE projects.tenant_id=excluded.tenant_id",
                (project["id"], project["title"], project["created_at"], json.dumps(project, ensure_ascii=False), tenant_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("作品不属于当前工作空间")
        return project

    def get_project(self, project_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT payload FROM projects WHERE id=?" + (" AND tenant_id=?" if tenant_id else ""),
                                     (project_id, tenant_id) if tenant_id else (project_id,)).fetchone()
        return json.loads(row["payload"]) if row else None

    def list_projects(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT payload FROM projects" + (" WHERE tenant_id=?" if tenant_id else "") + " ORDER BY created_at DESC",
                                      (tenant_id,) if tenant_id else ()).fetchall()
        summaries = []
        for row in rows:
            project = json.loads(row["payload"])
            summaries.append({key: value for key, value in project.items() if key not in {"chapters"}})
        return summaries

    def create_job(self, project_id: str, chapter_index: int, chapter: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        payload = json.dumps(chapter, ensure_ascii=False, sort_keys=True)
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            project = connection.execute("SELECT tenant_id FROM projects WHERE id=?", (project_id,)).fetchone()
            if project is None:
                raise ValueError("作品不存在")
            existing = connection.execute(
                "SELECT * FROM jobs WHERE project_id=? AND chapter_index=? AND payload=? "
                "AND status IN ('queued', 'running', 'merging') LIMIT 1",
                (project_id, chapter_index, payload),
            ).fetchone()
            if existing:
                return self._job(existing), False
            job_id = uuid.uuid4().hex
            now = timestamp()
            connection.execute(
                "INSERT INTO jobs (id, project_id, chapter_index, chapter_title, status, total, "
                "created_at, updated_at, payload, tenant_id) VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)",
                (job_id, project_id, chapter_index, chapter["title"], len(chapter["segments"]), now, now, payload, project["tenant_id"]),
            )
        return self.get_job(job_id), True

    @staticmethod
    def _job(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["payload"] = json.loads(result["payload"])
        return result

    def get_job(self, job_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE id=?" + (" AND tenant_id=?" if tenant_id else ""),
                                     (job_id, tenant_id) if tenant_id else (job_id,)).fetchone()
        return self._job(row) if row else None

    def list_jobs(self, tenant_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM jobs" + (" WHERE tenant_id=?" if tenant_id else "") + " ORDER BY created_at DESC",
                                      (tenant_id,) if tenant_id else ()).fetchall()
        return [self._job(row) for row in rows]

    def update_job(self, job_id: str, **fields: Any) -> None:
        allowed = {"status", "completed", "progress", "error", "audio_path"}
        if not set(fields).issubset(allowed):
            raise ValueError("无效任务字段")
        fields["updated_at"] = timestamp()
        columns = ", ".join(f"{name}=?" for name in fields)
        with self.connect() as connection:
            connection.execute(f"UPDATE jobs SET {columns} WHERE id=?", (*fields.values(), job_id))

    def recover_jobs(self) -> list[str]:
        with self.connect() as connection:
            connection.execute(
                "UPDATE jobs SET status='interrupted', error='服务中断，请点击重试继续生成', updated_at=? "
                "WHERE status IN ('running', 'merging')", (timestamp(),),
            )
            rows = connection.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY created_at").fetchall()
        return [row["id"] for row in rows]
