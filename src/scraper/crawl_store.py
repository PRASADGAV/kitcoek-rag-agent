"""
Crawl manifest persistence using SQLite.

Stores every discovered URL and its crawl status so runs can be:
- Resumed after interruption
- Queried for coverage reports
- Exported as CSV/JSON
"""

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Any


DB_PATH = os.getenv("CRAWL_DB_PATH", "data/crawl_runs/crawl.db")


class CrawlStore:
    """
    SQLite-backed store for crawl URLs, status and metadata.

    Schema:
      urls table — one row per discovered URL
    """

    def __init__(self, db_path: str = DB_PATH, run_id: str = ""):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self.run_id  = run_id or _make_run_id()
        self._conn   = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self._conn.executescript("""
        CREATE TABLE IF NOT EXISTS urls (
            canonical_url     TEXT PRIMARY KEY,
            url_requested     TEXT,
            url_final         TEXT,
            parent_url        TEXT,
            anchor_text       TEXT,
            host              TEXT,
            path              TEXT,
            resource_type     TEXT DEFAULT 'html',
            discovery_method  TEXT DEFAULT 'unknown',
            depth             INTEGER DEFAULT 0,
            http_status       INTEGER,
            content_type      TEXT,
            content_length    INTEGER,
            last_modified     TEXT,
            etag              TEXT,
            crawl_status      TEXT DEFAULT 'pending',
            skip_reason       TEXT,
            error_message     TEXT,
            first_seen_at     TEXT,
            last_checked_at   TEXT,
            run_id            TEXT,
            title             TEXT,
            content_hash      TEXT,
            extracted_chars   INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS runs (
            run_id            TEXT PRIMARY KEY,
            started_at        TEXT,
            completed_at      TEXT,
            status            TEXT DEFAULT 'running',
            seeds             INTEGER DEFAULT 0,
            discovered        INTEGER DEFAULT 0,
            fetched           INTEGER DEFAULT 0,
            extracted         INTEGER DEFAULT 0,
            failed            INTEGER DEFAULT 0,
            skipped           INTEGER DEFAULT 0,
            is_partial        INTEGER DEFAULT 0,
            notes             TEXT
        );
        """)
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # Run management
    # ------------------------------------------------------------------ #

    def start_run(self, seeds: int = 0) -> str:
        now = _now()
        self._conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, started_at, status, seeds) VALUES (?,?,?,?)",
            (self.run_id, now, "running", seeds)
        )
        self._conn.commit()
        return self.run_id

    def finish_run(self, is_partial: bool = False, notes: str = ""):
        stats = self.get_stats()
        self._conn.execute("""
            UPDATE runs SET
                completed_at=?, status=?, discovered=?, fetched=?,
                extracted=?, failed=?, skipped=?, is_partial=?, notes=?
            WHERE run_id=?
        """, (
            _now(),
            "partial" if is_partial else "complete",
            stats["discovered"], stats["fetched"],
            stats["extracted"], stats["failed"],
            stats["skipped"],
            1 if is_partial else 0,
            notes,
            self.run_id
        ))
        self._conn.commit()

    # ------------------------------------------------------------------ #
    # URL management
    # ------------------------------------------------------------------ #

    def add_url(
        self,
        canonical_url: str,
        parent_url: str = "",
        anchor_text: str = "",
        depth: int = 0,
        resource_type: str = "html",
        discovery_method: str = "unknown",
    ) -> bool:
        """
        Add a URL to the crawl queue if not already known.
        Returns True if newly added, False if already exists.
        """
        from urllib.parse import urlparse
        parsed = urlparse(canonical_url)

        existing = self._conn.execute(
            "SELECT canonical_url FROM urls WHERE canonical_url=?",
            (canonical_url,)
        ).fetchone()

        if existing:
            return False

        now = _now()
        self._conn.execute("""
            INSERT INTO urls (
                canonical_url, url_requested, parent_url, anchor_text,
                host, path, resource_type, discovery_method,
                depth, crawl_status, first_seen_at, run_id
            ) VALUES (?,?,?,?,?,?,?,?,?,'pending',?,?)
        """, (
            canonical_url, canonical_url, parent_url, anchor_text,
            parsed.netloc, parsed.path,
            resource_type, discovery_method,
            depth, now, self.run_id
        ))
        self._conn.commit()
        return True

    def get_next_pending(self, limit: int = 10) -> list[dict]:
        """Get next pending URLs ordered by depth (BFS)."""
        rows = self._conn.execute("""
            SELECT * FROM urls
            WHERE crawl_status='pending'
            ORDER BY depth ASC, first_seen_at ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]

    def mark_fetching(self, canonical_url: str):
        self._conn.execute(
            "UPDATE urls SET crawl_status='fetching', last_checked_at=? WHERE canonical_url=?",
            (_now(), canonical_url)
        )
        self._conn.commit()

    def mark_fetched(
        self,
        canonical_url: str,
        url_final: str = "",
        http_status: int = 200,
        content_type: str = "",
        content_length: int = 0,
        title: str = "",
        content_hash: str = "",
        extracted_chars: int = 0,
    ):
        self._conn.execute("""
            UPDATE urls SET
                crawl_status='fetched',
                url_final=?, http_status=?,
                content_type=?, content_length=?,
                title=?, content_hash=?,
                extracted_chars=?,
                last_checked_at=?
            WHERE canonical_url=?
        """, (
            url_final, http_status, content_type, content_length,
            title, content_hash, extracted_chars, _now(), canonical_url
        ))
        self._conn.commit()

    def mark_extracted(self, canonical_url: str, extracted_chars: int = 0):
        self._conn.execute("""
            UPDATE urls SET crawl_status='extracted', extracted_chars=?, last_checked_at=?
            WHERE canonical_url=?
        """, (extracted_chars, _now(), canonical_url))
        self._conn.commit()

    def mark_failed(self, canonical_url: str, error: str = "", http_status: int = 0):
        self._conn.execute("""
            UPDATE urls SET crawl_status='failed', error_message=?, http_status=?, last_checked_at=?
            WHERE canonical_url=?
        """, (error[:500], http_status, _now(), canonical_url))
        self._conn.commit()

    def mark_skipped(self, canonical_url: str, reason: str = ""):
        self._conn.execute("""
            UPDATE urls SET crawl_status='skipped', skip_reason=?, last_checked_at=?
            WHERE canonical_url=?
        """, (reason[:200], _now(), canonical_url))
        self._conn.commit()

    def is_known(self, canonical_url: str) -> bool:
        row = self._conn.execute(
            "SELECT canonical_url FROM urls WHERE canonical_url=?",
            (canonical_url,)
        ).fetchone()
        return row is not None

    # ------------------------------------------------------------------ #
    # Stats and exports
    # ------------------------------------------------------------------ #

    def get_stats(self) -> dict:
        row = self._conn.execute("""
            SELECT
                COUNT(*) as discovered,
                SUM(CASE WHEN crawl_status='pending'   THEN 1 ELSE 0 END) as pending,
                SUM(CASE WHEN crawl_status='fetching'  THEN 1 ELSE 0 END) as fetching,
                SUM(CASE WHEN crawl_status='fetched'   THEN 1 ELSE 0 END) as fetched,
                SUM(CASE WHEN crawl_status='extracted' THEN 1 ELSE 0 END) as extracted,
                SUM(CASE WHEN crawl_status='failed'    THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN crawl_status='skipped'   THEN 1 ELSE 0 END) as skipped,
                SUM(CASE WHEN resource_type='pdf'      THEN 1 ELSE 0 END) as pdfs,
                SUM(CASE WHEN resource_type='docx' OR resource_type='pptx'
                              OR resource_type='xlsx'  THEN 1 ELSE 0 END) as office_docs,
                SUM(CASE WHEN resource_type='html'     THEN 1 ELSE 0 END) as html_pages
            FROM urls WHERE run_id=?
        """, (self.run_id,)).fetchone()
        return dict(row) if row else {}

    def get_all_urls(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM urls WHERE run_id=? ORDER BY depth, first_seen_at",
            (self.run_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_urls_by_status(self, status: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM urls WHERE run_id=? AND crawl_status=?",
            (self.run_id, status)
        ).fetchall()
        return [dict(r) for r in rows]

    def export_csv(self, path: str):
        import csv
        rows = self.get_all_urls()
        if not rows:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    def export_json(self, path: str):
        rows = self.get_all_urls()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)

    def count_pending(self) -> int:
        row = self._conn.execute(
            "SELECT COUNT(*) FROM urls WHERE run_id=? AND crawl_status='pending'",
            (self.run_id,)
        ).fetchone()
        return row[0] if row else 0

    def close(self):
        self._conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S")
