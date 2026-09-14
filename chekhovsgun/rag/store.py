"""SQLite-backed index for saved items, chunks and their vectors.

Why SQLite and not a vector database: a personal bookmark library is thousands
of chunks, not millions. One file, zero services, trivially backed up — and an
in-memory float32 matrix brute-forces cosine similarity over 100k chunks in a
few milliseconds, which is far below the latency the browser extension needs.

The matrix and the BM25 statistics are cached and invalidated by a monotonic
``revision`` counter bumped on every write, so a long-running server never
re-reads the database unless something actually changed.
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from ..models import STATUS_ACTIVE, STATUSES, Chunk, SavedItem
from .text import tokenize

log = logging.getLogger(__name__)

SCHEMA_VERSION = 3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id            TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    title         TEXT NOT NULL DEFAULT '',
    url           TEXT NOT NULL DEFAULT '',
    author        TEXT NOT NULL DEFAULT '',
    author_id     TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    thumbnail     TEXT NOT NULL DEFAULT '',
    duration      INTEGER NOT NULL DEFAULT 0,
    published_at  REAL NOT NULL DEFAULT 0,
    saved_at      REAL NOT NULL DEFAULT 0,
    folder        TEXT NOT NULL DEFAULT '',
    lang          TEXT NOT NULL DEFAULT '',
    tags          TEXT NOT NULL DEFAULT '[]',
    extra         TEXT NOT NULL DEFAULT '{}',
    content_hash  TEXT NOT NULL DEFAULT '',
    has_transcript INTEGER NOT NULL DEFAULT 0,
    indexed_at    REAL NOT NULL DEFAULT 0,
    -- User-owned columns. Ingest never writes these, so a re-sync can replace
    -- every platform field above without touching the user's own work.
    status        TEXT NOT NULL DEFAULT 'active',
    user_tags     TEXT NOT NULL DEFAULT '[]',
    note          TEXT NOT NULL DEFAULT '',
    status_at     REAL NOT NULL DEFAULT 0,
    transcript_source TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_items_source ON items(source);
CREATE INDEX IF NOT EXISTS idx_items_saved_at ON items(saved_at DESC);

CREATE TABLE IF NOT EXISTS chunks (
    id        TEXT PRIMARY KEY,
    item_id   TEXT NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    ordinal   INTEGER NOT NULL DEFAULT 0,
    text      TEXT NOT NULL,
    start     REAL NOT NULL DEFAULT 0,
    end       REAL NOT NULL DEFAULT 0,
    kind      TEXT NOT NULL DEFAULT 'transcript',
    embedding BLOB,
    dim       INTEGER NOT NULL DEFAULT 0,
    -- Retrieval tokens, computed once at write time and stored space-joined.
    -- Tokenising 15k chunks takes ~6s; doing it on every cache rebuild made
    -- server start-up and the first query after each sync unusable.
    tokens    TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_chunks_item ON chunks(item_id);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    kind      TEXT NOT NULL,
    source    TEXT NOT NULL DEFAULT '',
    item_id   TEXT NOT NULL DEFAULT '',
    payload   TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);
"""


def _col(row: sqlite3.Row, name: str, default: Any) -> Any:
    """Read a column that may not exist yet on a not-yet-migrated row.

    ``sqlite3.Row`` raises IndexError for an unknown key and is not a dict, so
    neither ``row.get`` nor ``name in row`` does what you would expect.
    """
    try:
        value = row[name]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _row_to_item(row: sqlite3.Row) -> SavedItem:
    return SavedItem(
        source=row["source"],
        source_id=row["source_id"],
        title=row["title"],
        url=row["url"],
        author=row["author"],
        author_id=row["author_id"],
        description=row["description"],
        thumbnail=row["thumbnail"],
        duration=row["duration"],
        published_at=row["published_at"],
        saved_at=row["saved_at"],
        folder=row["folder"],
        lang=row["lang"],
        tags=json.loads(row["tags"] or "[]"),
        extra=json.loads(row["extra"] or "{}"),
        status=_col(row, "status", STATUS_ACTIVE) or STATUS_ACTIVE,
        user_tags=json.loads(_col(row, "user_tags", "[]") or "[]"),
        note=_col(row, "note", ""),
        transcript_source=_col(row, "transcript_source", ""),
    )


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        id=row["id"],
        item_id=row["item_id"],
        ordinal=row["ordinal"],
        text=row["text"],
        start=row["start"],
        end=row["end"],
        kind=row["kind"],
    )


class _LexicalIndex:
    """A compact BM25 index over every chunk in the store.

    Postings are numpy arrays rather than Python lists. Chinese tokenisation
    emits character unigrams, so a common character's posting list runs to tens
    of thousands of entries, and a twenty-token query walking those lists in
    Python cost ~56ms per search — an order of magnitude more than everything
    else in the query path combined. Each token's document indices are unique,
    so the scatter-add below is a plain fancy-index assignment, not np.add.at.
    """

    __slots__ = ("avg_len", "chunk_ids", "doc_len", "max_df", "postings", "total")

    #: Tokens appearing in more than this share of chunks are skipped. Their IDF
    #: is near zero, so they cannot change the ranking, but they carry the
    #: longest posting lists — in Chinese text that is every common character.
    MAX_DF_RATIO = 0.35

    def __init__(self, chunk_ids: list[str], token_lists: list[Sequence[str]]) -> None:
        self.chunk_ids = chunk_ids
        self.total = len(chunk_ids)
        self.doc_len = np.zeros(self.total, dtype=np.float32)

        raw: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for index, tokens in enumerate(token_lists):
            self.doc_len[index] = len(tokens)
            for token, count in Counter(tokens).items():
                raw[token].append((index, count))

        self.postings: dict[str, tuple[np.ndarray, np.ndarray]] = {
            token: (
                np.fromiter((i for i, _ in entries), dtype=np.int32, count=len(entries)),
                np.fromiter((c for _, c in entries), dtype=np.float32, count=len(entries)),
            )
            for token, entries in raw.items()
        }
        self.avg_len = float(self.doc_len.mean()) if self.total else 1.0
        self.max_df = max(8, int(self.total * self.MAX_DF_RATIO))

    def doc_freq(self, token: str) -> int:
        posting = self.postings.get(token)
        return int(posting[0].shape[0]) if posting else 0

    def search(
        self, tokens: Sequence[str], limit: int, k1: float = 1.4, b: float = 0.72
    ) -> list[tuple[int, float]]:
        if not self.total:
            return []
        scores = np.zeros(self.total, dtype=np.float32)
        avg = self.avg_len or 1.0
        touched = False
        for token in set(tokens):
            posting = self.postings.get(token)
            if posting is None:
                continue
            indices, freqs = posting
            df = indices.shape[0]
            if df > self.max_df:
                continue
            idf = math.log(1.0 + (self.total - df + 0.5) / (df + 0.5))
            norm = freqs * (k1 + 1.0) / (
                freqs + k1 * (1.0 - b + b * self.doc_len[indices] / avg)
            )
            scores[indices] += idf * norm
            touched = True
        if not touched:
            return []
        limit = min(limit, self.total)
        top = np.argpartition(-scores, limit - 1)[:limit]
        top = top[np.argsort(-scores[top])]
        return [(int(i), float(scores[i])) for i in top if scores[i] > 0.0]


class Store:
    """Thread-safe SQLite store with cached vector and lexical indexes."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()
        self._revision = 0
        self._cache_revision = -1
        self._matrix: np.ndarray | None = None
        self._matrix_ids: list[str] = []
        self._lexical: _LexicalIndex | None = None
        self._token_sets: dict[str, frozenset[str]] = {}
        self.set_meta("schema_version", str(SCHEMA_VERSION))

    def _migrate(self) -> None:
        """Bring an index written by an older version up to the current schema."""
        columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(chunks)").fetchall()
        }
        if "tokens" not in columns:
            log.info("migrating index: adding chunks.tokens")
            self._conn.execute("ALTER TABLE chunks ADD COLUMN tokens TEXT NOT NULL DEFAULT ''")
            rows = self._conn.execute("SELECT id, text FROM chunks").fetchall()
            self._conn.executemany(
                "UPDATE chunks SET tokens=? WHERE id=?",
                [(" ".join(tokenize(row["text"])), row["id"]) for row in rows],
            )

        item_columns = {
            row["name"] for row in self._conn.execute("PRAGMA table_info(items)").fetchall()
        }
        for column, ddl in (
            ("status", "TEXT NOT NULL DEFAULT 'active'"),
            ("user_tags", "TEXT NOT NULL DEFAULT '[]'"),
            ("note", "TEXT NOT NULL DEFAULT ''"),
            ("status_at", "REAL NOT NULL DEFAULT 0"),
            ("transcript_source", "TEXT NOT NULL DEFAULT ''"),
        ):
            if column not in item_columns:
                log.info("migrating index: adding items.%s", column)
                self._conn.execute(f"ALTER TABLE items ADD COLUMN {column} {ddl}")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_items_status ON items(status)")

    # ------------------------------------------------------------- lifecycle
    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _touch(self) -> None:
        self._revision += 1

    @property
    def revision(self) -> int:
        """Monotonic write counter. Cheap cache key — no COUNT queries needed."""
        return self._revision

    # ------------------------------------------------------------------ meta
    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            self._conn.commit()

    def get_meta(self, key: str, default: str = "") -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # ----------------------------------------------------------------- items
    def upsert_item(
        self,
        item: SavedItem,
        *,
        content_hash: str = "",
        has_transcript: bool = False,
        transcript_source: str = "",
    ) -> None:
        """Insert or refresh the platform-owned fields of an item.

        The ON CONFLICT clause deliberately omits ``status``, ``user_tags`` and
        ``note``: those belong to the user, and a nightly re-sync must never
        resurrect something they marked 已消化.
        """
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO items (id, source, source_id, title, url, author, author_id,
                                   description, thumbnail, duration, published_at, saved_at,
                                   folder, lang, tags, extra, content_hash, has_transcript,
                                   indexed_at, transcript_source)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title, url=excluded.url, author=excluded.author,
                    author_id=excluded.author_id, description=excluded.description,
                    thumbnail=excluded.thumbnail, duration=excluded.duration,
                    published_at=excluded.published_at, saved_at=excluded.saved_at,
                    folder=excluded.folder, lang=excluded.lang, tags=excluded.tags,
                    extra=excluded.extra, content_hash=excluded.content_hash,
                    has_transcript=excluded.has_transcript, indexed_at=excluded.indexed_at,
                    transcript_source=excluded.transcript_source
                """,
                (
                    item.id, item.source, item.source_id, item.title, item.url, item.author,
                    item.author_id, item.description, item.thumbnail, int(item.duration),
                    float(item.published_at), float(item.saved_at), item.folder, item.lang,
                    json.dumps(item.tags, ensure_ascii=False),
                    json.dumps(item.extra, ensure_ascii=False),
                    content_hash, int(has_transcript), time.time(), transcript_source,
                ),
            )
            self._conn.commit()
            self._touch()

    def set_item_status(
        self,
        item_id: str,
        *,
        status: str | None = None,
        add_tags: Sequence[str] | None = None,
        remove_tags: Sequence[str] | None = None,
        note: str | None = None,
    ) -> SavedItem | None:
        """Update the user-owned fields. Returns the item, or None if unknown."""
        with self._lock:
            row = self._conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
            if row is None:
                return None
            if status is not None and status not in STATUSES:
                raise ValueError(f"unknown status {status!r}; expected one of {STATUSES}")

            tags = json.loads(row["user_tags"] or "[]")
            for tag in add_tags or ():
                tag = tag.strip()
                if tag and tag not in tags:
                    tags.append(tag)
            for tag in remove_tags or ():
                if tag in tags:
                    tags.remove(tag)

            self._conn.execute(
                "UPDATE items SET status=?, user_tags=?, note=?, status_at=? WHERE id=?",
                (
                    status if status is not None else row["status"],
                    json.dumps(tags, ensure_ascii=False),
                    note if note is not None else row["note"],
                    time.time(),
                    item_id,
                ),
            )
            self._conn.commit()
            self._touch()
        return self.get_item(item_id)

    def item_ids_with_status(self, statuses: Sequence[str]) -> set[str]:
        """Ids to keep out of the popup. Small, and read on every relate call."""
        statuses = [s for s in statuses if s]
        if not statuses:
            return set()
        placeholders = ",".join("?" * len(statuses))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id FROM items WHERE status IN ({placeholders})", statuses
            ).fetchall()
        return {row["id"] for row in rows}

    def all_user_tags(self) -> list[tuple[str, int]]:
        """Every user tag with its item count, most used first."""
        counts: Counter[str] = Counter()
        with self._lock:
            rows = self._conn.execute(
                "SELECT user_tags FROM items WHERE user_tags != '[]'"
            ).fetchall()
        for row in rows:
            counts.update(json.loads(row["user_tags"] or "[]"))
        return counts.most_common()

    def get_item(self, item_id: str) -> SavedItem | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return _row_to_item(row) if row else None

    def get_items(self, item_ids: Iterable[str]) -> dict[str, SavedItem]:
        ids = list(dict.fromkeys(item_ids))
        if not ids:
            return {}
        out: dict[str, SavedItem] = {}
        with self._lock:
            for start in range(0, len(ids), 400):  # stay under SQLite's variable limit
                batch = ids[start : start + 400]
                placeholders = ",".join("?" * len(batch))
                rows = self._conn.execute(
                    f"SELECT * FROM items WHERE id IN ({placeholders})", batch
                ).fetchall()
                for row in rows:
                    out[row["id"]] = _row_to_item(row)
        return out

    def item_hashes(self, source: str = "") -> dict[str, str]:
        """``item_id -> content_hash``; used to skip unchanged items on re-ingest."""
        query = "SELECT id, content_hash FROM items"
        params: tuple[Any, ...] = ()
        if source:
            query += " WHERE source=?"
            params = (source,)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
        return {row["id"]: row["content_hash"] for row in rows}

    def list_items(
        self,
        *,
        source: str = "",
        query: str = "",
        status: str = "",
        tag: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[SavedItem]:
        sql = "SELECT * FROM items"
        clauses: list[str] = []
        params: list[Any] = []
        if source:
            clauses.append("source=?")
            params.append(source)
        if status:
            clauses.append("status=?")
            params.append(status)
        if tag:
            # user_tags is a JSON array; a LIKE on the quoted form is exact
            # enough here and needs no JSON1 extension.
            clauses.append("user_tags LIKE ?")
            params.append(f'%"{tag}"%')
        if query:
            clauses.append("(title LIKE ? OR author LIKE ? OR description LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY saved_at DESC, indexed_at DESC LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_item(row) for row in rows]

    def delete_item(self, item_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM chunks WHERE item_id=?", (item_id,))
            self._conn.execute("DELETE FROM items WHERE id=?", (item_id,))
            self._conn.commit()
            self._touch()

    # ---------------------------------------------------------------- chunks
    def replace_chunks(self, item_id: str, chunks: Sequence[Chunk], vectors: np.ndarray | None) -> None:
        """Swap in a fresh chunk set for one item, atomically."""
        with self._lock:
            self._conn.execute("DELETE FROM chunks WHERE item_id=?", (item_id,))
            rows = []
            for index, chunk in enumerate(chunks):
                blob = None
                dim = 0
                if vectors is not None and index < len(vectors):
                    vector = np.asarray(vectors[index], dtype=np.float32)
                    blob = vector.tobytes()
                    dim = int(vector.shape[0])
                rows.append(
                    (chunk.id, chunk.item_id, chunk.ordinal, chunk.text,
                     float(chunk.start), float(chunk.end), chunk.kind, blob, dim,
                     " ".join(tokenize(chunk.text)))
                )
            self._conn.executemany(
                "INSERT OR REPLACE INTO chunks "
                "(id, item_id, ordinal, text, start, end, kind, embedding, dim, tokens) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                rows,
            )
            self._conn.commit()
            self._touch()

    def get_chunks(self, chunk_ids: Iterable[str]) -> dict[str, Chunk]:
        ids = list(dict.fromkeys(chunk_ids))
        if not ids:
            return {}
        out: dict[str, Chunk] = {}
        with self._lock:
            for start in range(0, len(ids), 400):
                batch = ids[start : start + 400]
                placeholders = ",".join("?" * len(batch))
                rows = self._conn.execute(
                    f"SELECT * FROM chunks WHERE id IN ({placeholders})", batch
                ).fetchall()
                for row in rows:
                    out[row["id"]] = _row_to_chunk(row)
        return out

    def item_chunks(self, item_id: str) -> list[Chunk]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM chunks WHERE item_id=? ORDER BY ordinal", (item_id,)
            ).fetchall()
        return [_row_to_chunk(row) for row in rows]

    # --------------------------------------------------------------- indexes
    def _rebuild_caches(self) -> None:
        """Load every chunk once and build both the vector matrix and BM25 index."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, text, tokens, embedding, dim FROM chunks ORDER BY rowid"
            ).fetchall()

        ids: list[str] = []
        vectors: list[np.ndarray] = []
        token_lists: list[Sequence[str]] = []
        token_sets: dict[str, frozenset[str]] = {}
        dim = 0
        for row in rows:
            ids.append(row["id"])
            # Stored at write time; only fall back for rows written before the
            # tokens column existed and somehow missed the migration.
            tokens = row["tokens"].split() if row["tokens"] else tokenize(row["text"])
            token_lists.append(tokens)
            token_sets[row["id"]] = frozenset(tokens)
            blob, row_dim = row["embedding"], row["dim"]
            if blob and row_dim:
                dim = dim or row_dim
                vectors.append(np.frombuffer(blob, dtype=np.float32))
            else:
                vectors.append(np.zeros(0, dtype=np.float32))

        if dim:
            matrix = np.zeros((len(ids), dim), dtype=np.float32)
            for index, vector in enumerate(vectors):
                if vector.shape[0] == dim:
                    matrix[index] = vector
            self._matrix = matrix
        else:
            self._matrix = None

        self._matrix_ids = ids
        self._token_sets = token_sets
        self._lexical = _LexicalIndex(ids, token_lists)
        self._cache_revision = self._revision
        log.debug("rebuilt caches: %d chunks, dim=%d", len(ids), dim)

    def _ensure_caches(self) -> None:
        if self._cache_revision != self._revision or self._lexical is None:
            self._rebuild_caches()

    def dense_search(self, query_vector: np.ndarray, limit: int) -> list[tuple[str, float]]:
        with self._lock:
            self._ensure_caches()
            matrix, ids = self._matrix, self._matrix_ids
            if matrix is None or not ids or matrix.shape[1] != query_vector.shape[0]:
                return []
            scores = matrix @ np.asarray(query_vector, dtype=np.float32)
        limit = min(limit, scores.shape[0])
        if limit <= 0:
            return []
        top = np.argpartition(-scores, limit - 1)[:limit]
        top = top[np.argsort(-scores[top])]
        return [(ids[i], float(scores[i])) for i in top]

    def lexical_search(self, query: str, limit: int) -> list[tuple[str, float]]:
        tokens = tokenize(query)
        if not tokens:
            return []
        with self._lock:
            self._ensure_caches()
            lexical, ids = self._lexical, self._matrix_ids
            if lexical is None or not ids:
                return []
            ranked = lexical.search(tokens, limit)
        return [(ids[index], score) for index, score in ranked]

    def idf_weights(self, tokens: Sequence[str]) -> dict[str, float]:
        """``token -> idf``, with 0 for tokens that appear nowhere in the library.

        A query word the library has never seen cannot discriminate between
        saved items, so it must not count towards — or against — a coverage
        score. Dropping it is what lets "how I made my React app faster" be
        judged on the word ``react`` alone.
        """
        with self._lock:
            self._ensure_caches()
            lexical = self._lexical
            if lexical is None or not lexical.total:
                return {}
            total = lexical.total
            weights: dict[str, float] = {}
            for token in set(tokens):
                freq = lexical.doc_freq(token)
                if freq:
                    weights[token] = math.log(1.0 + total / freq)
        return weights


    def token_sets(self, chunk_ids: Sequence[str]) -> dict[str, frozenset[str]]:
        """Cached token sets for scoring. Avoids re-tokenising candidate text on
        every query — with 160 candidates that was the single largest cost in
        the hot path."""
        with self._lock:
            self._ensure_caches()
            return {cid: self._token_sets.get(cid, frozenset()) for cid in chunk_ids}

    # ---------------------------------------------------------------- events
    def log_event(self, kind: str, *, source: str = "", item_id: str = "", payload: dict | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO events (ts, kind, source, item_id, payload) VALUES (?,?,?,?,?)",
                (time.time(), kind, source, item_id, json.dumps(payload or {}, ensure_ascii=False)),
            )
            self._conn.commit()

    def recent_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY ts DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [
            {
                "ts": row["ts"],
                "kind": row["kind"],
                "source": row["source"],
                "item_id": row["item_id"],
                "payload": json.loads(row["payload"] or "{}"),
            }
            for row in rows
        ]

    # ----------------------------------------------------------------- stats
    def stats(self) -> dict[str, Any]:
        with self._lock:
            items = self._conn.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
            chunks = self._conn.execute("SELECT COUNT(*) c FROM chunks").fetchone()["c"]
            with_transcript = self._conn.execute(
                "SELECT COUNT(*) c FROM items WHERE has_transcript=1"
            ).fetchone()["c"]
            by_source = {
                row["source"]: row["c"]
                for row in self._conn.execute(
                    "SELECT source, COUNT(*) c FROM items GROUP BY source"
                ).fetchall()
            }
            fired = self._conn.execute(
                "SELECT COUNT(DISTINCT item_id) c FROM events WHERE kind='fired'"
            ).fetchone()["c"]
            by_status = {
                row["status"]: row["c"]
                for row in self._conn.execute(
                    "SELECT status, COUNT(*) c FROM items GROUP BY status"
                ).fetchall()
            }
            comment_chunks = self._conn.execute(
                "SELECT COUNT(*) c FROM chunks WHERE kind='comment'"
            ).fetchone()["c"]
            transcribed = self._conn.execute(
                "SELECT COUNT(*) c FROM items WHERE transcript_source='whisper'"
            ).fetchone()["c"]
            last = self._conn.execute("SELECT MAX(indexed_at) m FROM items").fetchone()["m"]
        return {
            "items": items,
            "chunks": chunks,
            "items_with_transcript": with_transcript,
            "by_source": by_source,
            "items_fired": fired,
            "by_status": by_status,
            "items_digested": by_status.get("digested", 0),
            "comment_chunks": comment_chunks,
            "items_transcribed": transcribed,
            # The honest success metric: not how often the popup fired, but how
            # many saves the user actually went back and finished.
            "coverage": round(by_status.get("digested", 0) / items, 4) if items else 0.0,
            "fire_rate": round(fired / items, 4) if items else 0.0,
            "last_indexed_at": last or 0.0,
            "embedding_signature": self.get_meta("embedding_signature"),
            "db_path": str(self.db_path),
        }
