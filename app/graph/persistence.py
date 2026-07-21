from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

from app.common.settings import get_settings
from app.graph.state import AcademicState


_setup_lock = threading.Lock()
_database_ready = False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connection() -> sqlite3.Connection:
    settings = get_settings()
    connection = sqlite3.connect(settings.db_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    return connection


def infer_thread_title(message: str, *, fallback: str = "未命名任务") -> str:
    normalized = " ".join((message or "").split())
    if not normalized:
        return fallback
    if len(normalized) <= 28:
        return normalized
    return normalized[:28].rstrip() + "..."


def setup_database() -> None:
    global _database_ready
    if _database_ready:
        return

    with _setup_lock:
        if _database_ready:
            return
        with _connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    title_source TEXT NOT NULL DEFAULT 'auto',
                    last_preview TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'idle',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_chat_messages_thread_id
                ON chat_messages(thread_id);

                CREATE TABLE IF NOT EXISTS react_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    state_json TEXT NOT NULL,
                    trace_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_react_runs_thread_id
                ON react_runs(thread_id);
                """
            )
        _database_ready = True


def _get_thread_row(connection: sqlite3.Connection, thread_id: str) -> sqlite3.Row | None:
    return connection.execute(
        "SELECT * FROM threads WHERE thread_id = ?",
        (thread_id,),
    ).fetchone()


def upsert_thread(
    thread_id: str,
    *,
    title: str | None = None,
    preview: str | None = None,
    status: str | None = None,
) -> None:
    setup_database()
    with _connection() as connection:
        row = _get_thread_row(connection, thread_id)
        now = _now_iso()
        clean_title = (title or "").strip()
        clean_preview = (preview or "").strip()
        clean_status = (status or "").strip()

        if row is None:
            connection.execute(
                """
                INSERT INTO threads (thread_id, title, title_source, last_preview, status, created_at, updated_at)
                VALUES (?, ?, 'auto', ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    clean_title or infer_thread_title(clean_preview, fallback=thread_id),
                    clean_preview,
                    clean_status or "idle",
                    now,
                    now,
                ),
            )
            return

        next_title = row["title"]
        if clean_title and row["title_source"] != "custom" and not next_title:
            next_title = clean_title
        if clean_preview and row["title_source"] != "custom" and row["title"] == infer_thread_title(
            row["last_preview"] or row["title"],
            fallback=row["title"],
        ):
            next_title = infer_thread_title(clean_preview, fallback=row["title"])

        connection.execute(
            """
            UPDATE threads
            SET title = ?, last_preview = ?, status = ?, updated_at = ?
            WHERE thread_id = ?
            """,
            (
                next_title,
                clean_preview or row["last_preview"],
                clean_status or row["status"],
                now,
                thread_id,
            ),
        )


def set_thread_status(thread_id: str, status: str, *, preview: str | None = None) -> None:
    upsert_thread(thread_id, preview=preview, status=status)


def rename_thread(thread_id: str, title: str) -> None:
    setup_database()
    with _connection() as connection:
        connection.execute(
            """
            UPDATE threads
            SET title = ?, title_source = 'custom', updated_at = ?
            WHERE thread_id = ?
            """,
            (title.strip() or "未命名任务", _now_iso(), thread_id),
        )


def get_thread_summary(thread_id: str) -> dict | None:
    setup_database()
    with _connection() as connection:
        row = _get_thread_row(connection, thread_id)
    if not row:
        return None
    return {
        "thread_id": row["thread_id"],
        "title": row["title"],
        "last_preview": row["last_preview"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def list_threads(limit: int = 100) -> list[dict]:
    setup_database()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT thread_id, title, last_preview, status, created_at, updated_at
            FROM threads
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    return [
        {
            "thread_id": row["thread_id"],
            "title": row["title"],
            "last_preview": row["last_preview"],
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]


def append_chat_message(thread_id: str, role: str, content: str) -> None:
    setup_database()
    preview = content if role == "user" else None
    upsert_thread(thread_id, preview=preview)
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO chat_messages (thread_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (thread_id, role, content, _now_iso()),
        )


def get_thread_messages(thread_id: str) -> list[dict[str, str]]:
    setup_database()
    with _connection() as connection:
        rows = connection.execute(
            """
            SELECT role, content
            FROM chat_messages
            WHERE thread_id = ?
            ORDER BY id ASC
            """,
            (thread_id,),
        ).fetchall()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


def clear_thread_data(thread_id: str) -> None:
    setup_database()
    with _connection() as connection:
        connection.execute("DELETE FROM chat_messages WHERE thread_id = ?", (thread_id,))
        connection.execute("DELETE FROM react_runs WHERE thread_id = ?", (thread_id,))
        connection.execute(
            """
            UPDATE threads
            SET last_preview = '', status = 'empty', updated_at = ?
            WHERE thread_id = ?
            """,
            (_now_iso(), thread_id),
        )


def delete_thread(thread_id: str) -> None:
    setup_database()
    with _connection() as connection:
        connection.execute("DELETE FROM chat_messages WHERE thread_id = ?", (thread_id,))
        connection.execute("DELETE FROM react_runs WHERE thread_id = ?", (thread_id,))
        connection.execute("DELETE FROM threads WHERE thread_id = ?", (thread_id,))


def save_run_state(state: AcademicState) -> None:
    setup_database()
    with _connection() as connection:
        connection.execute(
            """
            INSERT INTO react_runs (thread_id, state_json, trace_json, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                state["thread_id"],
                json.dumps(state, ensure_ascii=False),
                json.dumps(state.get("react_trace", []), ensure_ascii=False),
                _now_iso(),
            ),
        )


def load_latest_state(thread_id: str) -> AcademicState | None:
    setup_database()
    with _connection() as connection:
        row = connection.execute(
            """
            SELECT state_json
            FROM react_runs
            WHERE thread_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (thread_id,),
        ).fetchone()

    if not row:
        return None
    return json.loads(row["state_json"])


def get_thread_bundle(thread_id: str) -> dict | None:
    thread = get_thread_summary(thread_id)
    if not thread:
        return None
    return {
        "thread": thread,
        "messages": get_thread_messages(thread_id),
        "state": load_latest_state(thread_id),
    }
