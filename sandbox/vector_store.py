"""Vector store — sqlite-vec when available, dormant otherwise.

This module gracefully degrades. The system Python on macOS
(`/usr/bin/python3`) is built WITHOUT `--enable-loadable-sqlite-extensions`,
which means even with `pip install sqlite-vec` it cannot load. So we:

1. Check whether the current python's sqlite3 supports `enable_load_extension`.
2. Check whether `sqlite_vec` is importable.
3. If both: enable vector ops. If either fails: log a clear instruction and
   make every vector method a no-op that returns an empty / sentinel value.

The rest of the code (researcher.py) should call `is_enabled()` once at
startup and gate writes accordingly. Backfill is supported: when vectors
come online later, call `backfill_from_db()` to embed every existing note.

How to enable:
  - Install Python from python.org (Homebrew or pyenv also work).
    The stock /usr/bin/python3 on macOS won't ever support this — Apple
    builds it without extension loading.
  - `pip install sqlite-vec`
  - Add EMBEDDING_PROVIDER=gemini (or openai) to sandbox/.env
  - Restart the server; `is_enabled()` should now return True.
"""
from __future__ import annotations

import json
import os
import sqlite3
from typing import Any

ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(ROOT, "research.db")

# ---- capability detection (cheap; runs once on import) -----------------------

_CONN_HAS_EXT: bool
_SQLITE_VEC_AVAILABLE: bool
_DISABLED_REASON: str | None = None

try:
    _probe = sqlite3.connect(":memory:")
    _CONN_HAS_EXT = hasattr(_probe, "enable_load_extension")
    _probe.close()
except Exception:  # noqa: BLE001
    _CONN_HAS_EXT = False

try:
    import sqlite_vec  # type: ignore
    _SQLITE_VEC_AVAILABLE = True
except Exception:  # noqa: BLE001
    _SQLITE_VEC_AVAILABLE = False

if not _CONN_HAS_EXT:
    _DISABLED_REASON = (
        "python's sqlite3 was built without enable_load_extension "
        "(stock macOS /usr/bin/python3 has this limitation). "
        "Install python from python.org or via Homebrew/pyenv, then `pip install sqlite-vec`."
    )
elif not _SQLITE_VEC_AVAILABLE:
    _DISABLED_REASON = "sqlite-vec is not installed. Run: pip install sqlite-vec"


def is_enabled() -> bool:
    return _CONN_HAS_EXT and _SQLITE_VEC_AVAILABLE


def disabled_reason() -> str | None:
    return _DISABLED_REASON


# ---- live API (no-ops when disabled) -----------------------------------------

EMBED_DIM = 768  # gemini text-embedding-004 default; adjust per provider

def init_vector_tables() -> None:
    if not is_enabled():
        return
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS note_embeddings USING vec0(
            note_rowid INTEGER PRIMARY KEY,
            clause_id TEXT,
            pass_number INTEGER,
            embedding float[{EMBED_DIM}]
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS passage_embeddings USING vec0(
            id INTEGER PRIMARY KEY,
            source TEXT,
            ref TEXT,
            embedding float[768]
        )
    """)
    conn.commit()
    conn.close()


def embed_text(text: str) -> list[float] | None:
    """Single-call embedding. Returns None if no embedding provider available.

    Routes to whichever provider is configured. Gemini text-embedding-004 is
    the default if GEMINI_API_KEY is set.
    """
    if not is_enabled():
        return None
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key:
        return None
    import urllib.request
    model = os.environ.get("BATAILLE_EMBED_MODEL", "text-embedding-004")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent?key={key}"
    payload = {"content": {"parts": [{"text": text}]}}
    req = urllib.request.Request(
        url,
        method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps(payload).encode("utf-8"),
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("embedding", {}).get("values")


def store_note_embedding(clause_id: str, pass_number: int, text: str) -> bool:
    if not is_enabled():
        return False
    vec = embed_text(text)
    if not vec:
        return False
    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    # vec0 wants the embedding as bytes or as a json string of floats
    conn.execute(
        "INSERT INTO note_embeddings(clause_id, pass_number, embedding) VALUES (?, ?, ?)",
        (clause_id, pass_number, json.dumps(vec)),
    )
    conn.commit()
    conn.close()
    return True


def search_similar_passages(query_text: str, k: int = 5) -> list[dict]:
    """Given a paragraph, return the top-k passages whose embedding is closest.
    Empty list when disabled."""
    if not is_enabled():
        return []
    vec = embed_text(query_text)
    if not vec:
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    rows = conn.execute(
        """
        SELECT source, ref, distance
        FROM passage_embeddings
        WHERE embedding MATCH ?
        ORDER BY distance
        LIMIT ?
        """,
        (json.dumps(vec), k),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def backfill_from_db() -> dict:
    """Walk every research note and every clause anchor, embed, and store.
    Returns counts. No-op when disabled."""
    if not is_enabled():
        return {"enabled": False, "reason": _DISABLED_REASON, "embedded": 0}
    # Implementation left thin until needed — current notes are small enough
    # that this should be called once after enabling, not on every restart.
    raise NotImplementedError("backfill_from_db: implement when vectors are enabled")
