"""SQLite storage. One short-lived connection per operation (WAL)."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable

from .config import DB_PATH
from .timeutil import now_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    url TEXT NOT NULL,
    strategy TEXT NOT NULL DEFAULT 'auto',
    interval_minutes INTEGER NOT NULL DEFAULT 60,
    enabled INTEGER NOT NULL DEFAULT 1,
    use_proxy INTEGER NOT NULL DEFAULT 1,
    locale TEXT NOT NULL DEFAULT 'zh',
    keywords_include TEXT NOT NULL DEFAULT '',
    keywords_exclude TEXT NOT NULL DEFAULT '',
    selectors TEXT NOT NULL DEFAULT '{}',
    feasibility TEXT NOT NULL DEFAULT '{}',
    notes TEXT NOT NULL DEFAULT '',
    baseline_done INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'idle',
    last_scan_at TEXT,
    last_success_at TEXT,
    last_error TEXT,
    last_http_status INTEGER NOT NULL DEFAULT 0,
    last_items_found INTEGER NOT NULL DEFAULT 0,
    last_notes TEXT NOT NULL DEFAULT '',
    fail_count INTEGER NOT NULL DEFAULT 0,
    last_item_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    summary TEXT NOT NULL DEFAULT '',
    published_at TEXT,
    is_update INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 0,
    reason TEXT NOT NULL DEFAULT '',
    ai_summary TEXT NOT NULL DEFAULT '',
    raw TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    notified INTEGER NOT NULL DEFAULT 0,
    UNIQUE(source_id, external_id)
);

CREATE TABLE IF NOT EXISTS channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    config TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER REFERENCES sources(id) ON DELETE SET NULL,
    item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'detected',
    channel_results TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    level TEXT NOT NULL,
    event TEXT NOT NULL,
    message TEXT NOT NULL,
    source_id INTEGER,
    detail TEXT
);

CREATE INDEX IF NOT EXISTS idx_items_source ON items(source_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_created ON alerts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_ts ON logs(ts DESC);
CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources(enabled);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=20, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


@contextmanager
def get_conn():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
    _seed_defaults()


def _migrate(conn: sqlite3.Connection) -> None:
    """Additive migrations for databases created by older builds."""
    wanted = {
        "sources": {
            "last_http_status": "INTEGER NOT NULL DEFAULT 0",
            "last_items_found": "INTEGER NOT NULL DEFAULT 0",
            "last_notes": "TEXT NOT NULL DEFAULT ''",
        }
    }
    for table, columns in wanted.items():
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, ddl in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def meta_get(key: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def meta_set(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def _seed_defaults() -> None:
    from .settings import ensure_defaults

    ensure_defaults()
    if meta_get("seeded_defaults") == "1":
        return
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM sources").fetchone()["c"]
        if count == 0:
            ts = now_iso()
            conn.execute(
                """INSERT INTO sources
                (name,url,strategy,interval_minutes,enabled,use_proxy,locale,notes,status,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    "KARDS",
                    "https://www.kardsplayer.com/zh/news",
                    "rsc",
                    60,
                    1,
                    1,
                    "zh",
                    "内置示例源：Next.js RSC 新闻列表，首次扫描建立基线。",
                    "idle",
                    ts,
                    ts,
                ),
            )
        channels = conn.execute("SELECT COUNT(*) AS c FROM channels").fetchone()["c"]
        if channels == 0:
            ts = now_iso()
            conn.execute(
                """INSERT INTO channels(name,type,enabled,config,created_at,updated_at)
                VALUES(?,?,?,?,?,?)""",
                ("运行日志（默认渠道）", "console", 1, "{}", ts, ts),
            )
    meta_set("seeded_defaults", "1")


def log_event(
    level: str,
    event: str,
    message: str,
    *,
    source_id: int | None = None,
    detail: str | None = None,
) -> None:
    level = (level or "info").lower()
    try:
        with get_conn() as conn:
            conn.execute(
                "INSERT INTO logs(ts,level,event,message,source_id,detail) VALUES(?,?,?,?,?,?)",
                (now_iso(), level, event[:80], message[:2000], source_id, (detail or "")[:8000] or None),
            )
            # Keep the table bounded.
            conn.execute(
                "DELETE FROM logs WHERE id < (SELECT MAX(id) - 5000 FROM logs)"
            )
    except Exception:
        # Logging must never take the app down.
        pass



def run_maintenance() -> None:
    """Prune logs and old, unalerted items according to general settings."""
    try:
        from .settings import get_setting

        cfg = get_setting("general", mask=False)
    except Exception:  # noqa: BLE001
        cfg = {}
    log_retention = max(100, int(cfg.get("log_retention") or 5000))
    item_days = max(30, int(cfg.get("item_retention_days") or 730))
    alert_days = max(30, int(cfg.get("alert_retention_days") or 365))

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    item_cutoff = (now - timedelta(days=item_days)).isoformat()
    alert_cutoff = (now - timedelta(days=alert_days)).isoformat()

    with get_conn() as conn:
        conn.execute(
            "DELETE FROM logs WHERE id NOT IN (SELECT id FROM logs ORDER BY id DESC LIMIT ?)",
            (log_retention,),
        )
        conn.execute("DELETE FROM alerts WHERE created_at < ?", (alert_cutoff,))
        conn.execute(
            "DELETE FROM items WHERE published_at IS NOT NULL AND published_at < ? "
            "AND id NOT IN (SELECT item_id FROM alerts WHERE item_id IS NOT NULL)",
            (item_cutoff,),
        )


def get_source(source_id: int) -> dict[str, Any] | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    return dict(row) if row else None


def list_sources() -> list[dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT s.*,
                (SELECT COUNT(*) FROM items i WHERE i.source_id=s.id) AS item_count,
                (SELECT COUNT(*) FROM items i WHERE i.source_id=s.id AND i.is_update=1) AS update_count,
                (SELECT title FROM items i WHERE i.source_id=s.id ORDER BY COALESCE(i.published_at,i.first_seen_at) DESC LIMIT 1) AS last_item_title
            FROM sources s ORDER BY s.enabled DESC, s.id ASC"""
        ).fetchall()
    return rows_to_dicts(rows)


def json_load(value: str | None, fallback):
    try:
        return json.loads(value) if value else fallback
    except (TypeError, ValueError):
        return fallback
