"""SQLite storage: collected items, drafts and OAuth tokens."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .models import DraftStatus, Item

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    data TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS items_canonical ON items(canonical_url);

CREATE TABLE IF NOT EXISTS drafts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id TEXT NOT NULL,
    canonical_url TEXT NOT NULL,
    title TEXT NOT NULL,
    slot_at TEXT NOT NULL,
    status TEXT NOT NULL,
    content TEXT NOT NULL,
    media TEXT NOT NULL DEFAULT '[]',
    discord_message_id INTEGER,
    results TEXT NOT NULL DEFAULT '{}',
    meta TEXT NOT NULL DEFAULT '{}',
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS drafts_status ON drafts(status, slot_at);

CREATE TABLE IF NOT EXISTS tokens (
    name TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _item_from_json(raw: str) -> Item:
    data = json.loads(raw)
    if data.get("published_at"):
        data["published_at"] = datetime.fromisoformat(data["published_at"])
    return Item(**data)


class Database:
    def __init__(self, path: Path | str):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        columns = {r["name"] for r in self._conn.execute("PRAGMA table_info(drafts)")}
        if "meta" not in columns:
            with self._tx() as c:
                c.execute("ALTER TABLE drafts ADD COLUMN meta TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._conn:
            yield self._conn

    # --- items ---------------------------------------------------------------

    def upsert_items(self, items: list[Item]) -> None:
        with self._tx() as c:
            c.executemany(
                """INSERT INTO items (id, source, canonical_url, data, score, fetched_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET data=excluded.data, score=excluded.score,
                                                 fetched_at=excluded.fetched_at""",
                [
                    (i.id, i.source, i.canonical, json.dumps(asdict(i), default=str), i.score, _now())
                    for i in items
                ],
            )

    def recent_items(self, hours: int = 48) -> list[Item]:
        since = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
        rows = self._conn.execute("SELECT data FROM items WHERE fetched_at >= ?", (since,)).fetchall()
        return [_item_from_json(r["data"]) for r in rows]

    def get_item(self, item_id: str) -> Item | None:
        row = self._conn.execute("SELECT data FROM items WHERE id = ?", (item_id,)).fetchone()
        return _item_from_json(row["data"]) if row else None

    # --- drafts --------------------------------------------------------------

    def covered_topics(self, days: int) -> list[tuple[str, str]]:
        """(canonical_url, title) of drafts not rejected within the window."""
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT canonical_url, title FROM drafts WHERE created_at >= ? AND status != ?",
            (since, DraftStatus.REJECTED.value),
        ).fetchall()
        return [(r["canonical_url"], r["title"]) for r in rows]

    def rejected_item_ids(self, days: int) -> set[str]:
        since = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT item_id FROM drafts WHERE created_at >= ? AND status = ?",
            (since, DraftStatus.REJECTED.value),
        ).fetchall()
        return {r["item_id"] for r in rows}

    def create_draft(self, item: Item, slot_at: datetime, content: dict, media: list[str]) -> int:
        with self._tx() as c:
            cur = c.execute(
                """INSERT INTO drafts (item_id, canonical_url, title, slot_at, status, content, media,
                                       created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    item.id, item.canonical, item.title, slot_at.astimezone(UTC).isoformat(),
                    DraftStatus.PENDING.value, json.dumps(content), json.dumps(media), _now(), _now(),
                ),
            )
            return int(cur.lastrowid)

    def get_draft(self, draft_id: int) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        return self._draft(row) if row else None

    def update_draft(self, draft_id: int, **fields: Any) -> None:
        for key in ("content", "media", "results", "meta"):
            if key in fields:
                fields[key] = json.dumps(fields[key])
        if isinstance(fields.get("status"), DraftStatus):
            fields["status"] = fields["status"].value
        if isinstance(fields.get("slot_at"), datetime):
            fields["slot_at"] = fields["slot_at"].astimezone(UTC).isoformat()
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in fields)
        with self._tx() as c:
            c.execute(f"UPDATE drafts SET {cols} WHERE id = ?", (*fields.values(), draft_id))

    def delete_draft(self, draft_id: int) -> None:
        with self._tx() as c:
            c.execute("DELETE FROM drafts WHERE id = ?", (draft_id,))

    def claim_draft(self, draft_id: int, expected: DraftStatus, new: DraftStatus) -> bool:
        """Atomic status transition, so a draft is never published twice."""
        with self._tx() as c:
            cur = c.execute(
                "UPDATE drafts SET status = ?, updated_at = ? WHERE id = ? AND status = ?",
                (new.value, _now(), draft_id, expected.value),
            )
            return cur.rowcount == 1

    def due_drafts(self, now: datetime | None = None) -> list[dict[str, Any]]:
        now = (now or datetime.now(UTC)).astimezone(UTC).isoformat()
        rows = self._conn.execute(
            "SELECT * FROM drafts WHERE status = ? AND slot_at <= ? ORDER BY slot_at",
            (DraftStatus.APPROVED.value, now),
        ).fetchall()
        return [self._draft(r) for r in rows]

    def active_draft_for_slot(self, slot_at: datetime) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM drafts WHERE slot_at = ? AND status NOT IN (?, ?) ORDER BY id DESC LIMIT 1",
            (slot_at.astimezone(UTC).isoformat(), DraftStatus.REJECTED.value, DraftStatus.FAILED.value),
        ).fetchone()
        return self._draft(row) if row else None

    @staticmethod
    def _draft(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["content"] = json.loads(d["content"])
        d["media"] = json.loads(d["media"])
        d["results"] = json.loads(d["results"])
        d["meta"] = json.loads(d["meta"])
        d["slot_at"] = datetime.fromisoformat(d["slot_at"])
        d["status"] = DraftStatus(d["status"])
        return d

    def validated_contents(self, limit: int) -> list[dict[str, Any]]:
        """Content of the drafts a human approved, newest first: the best references for the house voice."""
        rows = self._conn.execute(
            "SELECT content FROM drafts WHERE status IN (?, ?, ?) ORDER BY updated_at DESC LIMIT ?",
            (DraftStatus.APPROVED.value, DraftStatus.PUBLISHING.value, DraftStatus.PUBLISHED.value, limit),
        ).fetchall()
        return [json.loads(r["content"]) for r in rows]

    def recent_hooks(self, limit: int = 8) -> list[str]:
        rows = self._conn.execute(
            "SELECT content FROM drafts WHERE status != ? ORDER BY id DESC LIMIT ?",
            (DraftStatus.REJECTED.value, limit),
        ).fetchall()
        hooks = []
        for r in rows:
            post = json.loads(r["content"]).get("threads", {}).get("post", "").strip()
            if post:
                hooks.append(post.splitlines()[0])
        return hooks

    def stats(self) -> dict[str, int]:
        rows = self._conn.execute("SELECT status, COUNT(*) AS n FROM drafts GROUP BY status").fetchall()
        return {r["status"]: r["n"] for r in rows}

    # --- tokens --------------------------------------------------------------

    def get_token(self, name: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT data FROM tokens WHERE name = ?", (name,)).fetchone()
        return json.loads(row["data"]) if row else None

    def set_token(self, name: str, data: dict[str, Any]) -> None:
        with self._tx() as c:
            c.execute(
                """INSERT INTO tokens (name, data, updated_at) VALUES (?, ?, ?)
                   ON CONFLICT(name) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
                (name, json.dumps(data), _now()),
            )
