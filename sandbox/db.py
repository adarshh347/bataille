"""SQLite layer — relational mirror of the per-clause JSONL files.

We keep JSONL as the source of truth for now (inspectable, git-friendly,
zero migration cost). SQLite mirrors writes so we can run relational
queries: ORDER BY recent, GROUP BY pass_kind, JOIN to clauses, etc.

Vector storage is a separate concern (see `vector_store.py`). It is
intentionally optional — the system Python's sqlite3 on macOS is built
without `enable_load_extension`, so sqlite-vec won't load there. The
relational layer here uses only stdlib sqlite3 and works everywhere.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "research.db")

_lock = threading.Lock()  # the http server is multi-threaded; protect sqlite writes


SCHEMA = """
CREATE TABLE IF NOT EXISTS clauses (
    id            TEXT PRIMARY KEY,
    source_file   TEXT,
    layers        TEXT,        -- json array
    salience      INTEGER,     -- 0 / 1 / 2
    seed          INTEGER,     -- 0/1
    outward_tags  TEXT,        -- json array of {seed,research-task,kin,install-deep}
    book          TEXT,
    section       TEXT,
    note          TEXT,
    anchor        TEXT,
    pinned        INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT
);

CREATE TABLE IF NOT EXISTS research_notes (
    clause_id    TEXT NOT NULL,
    pass_number  INTEGER NOT NULL,
    pass_kind    TEXT NOT NULL,
    provider     TEXT,
    model        TEXT,
    generated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    PRIMARY KEY (clause_id, pass_number)
);

CREATE INDEX IF NOT EXISTS idx_notes_kind ON research_notes(pass_kind);
CREATE INDEX IF NOT EXISTS idx_notes_recent ON research_notes(generated_at DESC);
CREATE INDEX IF NOT EXISTS idx_notes_clause ON research_notes(clause_id);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    """Idempotent — call at startup."""
    with _lock, connect() as c:
        c.executescript(SCHEMA)


def sync_clauses_from_json(clauses: list[dict]) -> int:
    """Mirror the clauses.json into the db. Upsert; preserve `pinned` column."""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _lock, connect() as c:
        for cl in clauses:
            c.execute(
                """
                INSERT INTO clauses (id, source_file, layers, salience, seed, outward_tags,
                                     book, section, note, anchor, updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    source_file = excluded.source_file,
                    layers = excluded.layers,
                    salience = excluded.salience,
                    seed = excluded.seed,
                    outward_tags = excluded.outward_tags,
                    book = excluded.book,
                    section = excluded.section,
                    note = excluded.note,
                    anchor = excluded.anchor,
                    updated_at = excluded.updated_at
                """,
                (
                    cl.get("id"),
                    cl.get("source_file"),
                    json.dumps(cl.get("layers", []), ensure_ascii=False),
                    int(cl.get("salience") or 0),
                    int(bool(cl.get("seed"))),
                    json.dumps(cl.get("outward_tags", []), ensure_ascii=False),
                    cl.get("book", ""),
                    cl.get("section", ""),
                    cl.get("note", ""),
                    cl.get("anchor", ""),
                    now,
                ),
            )
    return len(clauses)


def insert_note(note: dict) -> None:
    """Mirror one research_note into the db. Idempotent on (clause_id, pass_number)."""
    meta = note.get("_meta", {})
    with _lock, connect() as c:
        c.execute(
            """
            INSERT OR REPLACE INTO research_notes
                (clause_id, pass_number, pass_kind, provider, model, generated_at, payload_json)
            VALUES (?,?,?,?,?,?,?)
            """,
            (
                note.get("clause_id"),
                int(note.get("pass_number", 0)),
                note.get("pass_kind", "unknown"),
                meta.get("provider"),
                meta.get("model"),
                meta.get("generated_at") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
                json.dumps(note, ensure_ascii=False),
            ),
        )


def set_pinned(clause_id: str, pinned: bool) -> None:
    with _lock, connect() as c:
        c.execute("UPDATE clauses SET pinned = ? WHERE id = ?", (1 if pinned else 0, clause_id))


def pinned_clauses() -> list[str]:
    with connect() as c:
        rows = c.execute("SELECT id FROM clauses WHERE pinned = 1 ORDER BY id").fetchall()
    return [r["id"] for r in rows]


def notes_for(clause_id: str) -> list[dict]:
    with connect() as c:
        rows = c.execute(
            "SELECT payload_json FROM research_notes WHERE clause_id = ? ORDER BY pass_number ASC",
            (clause_id,),
        ).fetchall()
    return [json.loads(r["payload_json"]) for r in rows]


def recent_notes(limit: int = 20) -> list[dict]:
    """For a 'research feed' UI."""
    with connect() as c:
        rows = c.execute(
            "SELECT payload_json FROM research_notes ORDER BY generated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [json.loads(r["payload_json"]) for r in rows]


def stats() -> dict:
    with connect() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM research_notes").fetchone()["n"]
        by_kind = [
            dict(r) for r in c.execute(
                "SELECT pass_kind, COUNT(*) AS n FROM research_notes GROUP BY pass_kind ORDER BY n DESC"
            ).fetchall()
        ]
        clauses_with_research = c.execute(
            "SELECT COUNT(DISTINCT clause_id) AS n FROM research_notes"
        ).fetchone()["n"]
        pinned_count = c.execute("SELECT COUNT(*) AS n FROM clauses WHERE pinned = 1").fetchone()["n"]
    return {
        "total_notes": total,
        "by_pass_kind": by_kind,
        "clauses_with_research": clauses_with_research,
        "pinned_count": pinned_count,
    }
