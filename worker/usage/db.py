"""Usage tracking DB — SQLite log of all API calls with cost/token/unit data."""
from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

# Session ID is generated once per process lifetime (bridge server startup).
SESSION_ID: str = str(uuid.uuid4())

_DB_PATH = Path(__file__).parent / "usage.db"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS usage_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    session_id  TEXT NOT NULL,
    provider    TEXT NOT NULL,
    category    TEXT NOT NULL,
    model       TEXT,
    cost_usd    REAL NOT NULL DEFAULT 0.0,
    tokens_in   INTEGER DEFAULT 0,
    tokens_out  INTEGER DEFAULT 0,
    units       REAL DEFAULT 1.0,
    is_free     INTEGER NOT NULL DEFAULT 1,
    metadata    TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Create the usage_log table if it does not exist."""
    with _connect() as conn:
        conn.execute(_CREATE_TABLE_SQL)
        conn.commit()


def log_usage(
    provider: str,
    category: str,
    model: str | None = None,
    cost_usd: float = 0.0,
    tokens_in: int = 0,
    tokens_out: int = 0,
    units: float = 1.0,
    is_free: int = 1,
    metadata: dict | None = None,
) -> None:
    """Insert a single usage record. Never raises — logs error to stdout."""
    try:
        meta_str = json.dumps(metadata) if metadata else None
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO usage_log
                    (session_id, provider, category, model, cost_usd,
                     tokens_in, tokens_out, units, is_free, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (SESSION_ID, provider, category, model, cost_usd,
                 tokens_in, tokens_out, units, is_free, meta_str),
            )
            conn.commit()
    except (sqlite3.Error, OSError) as e:
        # Usage DB is diagnostic; a write failure must never break the
        # caller's hot path. Log at debug level to avoid noise.
        logger.debug("log_usage failed: %s", e)


def get_session_stats(session_id: str | None = None) -> dict:
    """Return per-provider call counts and costs for the given session.

    Defaults to the current session if session_id is None.
    """
    sid = session_id or SESSION_ID
    try:
        with _connect() as conn:
            rows = conn.execute(
                """
                SELECT provider, COUNT(*) as calls, SUM(cost_usd) as total_cost
                FROM usage_log
                WHERE session_id = ?
                GROUP BY provider
                """,
                (sid,),
            ).fetchall()
        return {
            row["provider"]: {
                "calls": row["calls"],
                "cost_usd": round(row["total_cost"] or 0.0, 6),
            }
            for row in rows
        }
    except sqlite3.Error as e:
        logger.debug("get_session_stats failed: %s", e)
        return {}


def get_daily_stats(provider: str) -> dict:
    """Return today's usage count and total cost for a provider (Pacific date reset)."""
    # Use UTC date as approximation; Pacific midnight = UTC+7/8, good enough for display
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) as calls, SUM(cost_usd) as total_cost
                FROM usage_log
                WHERE provider = ?
                  AND date(timestamp) = ?
                """,
                (provider, today),
            ).fetchone()
        return {
            "calls": row["calls"] or 0,
            "cost_usd": round(row["total_cost"] or 0.0, 6),
            "date": today,
        }
    except sqlite3.Error as e:
        logger.debug("get_daily_stats failed: %s", e)
        return {"calls": 0, "cost_usd": 0.0, "date": today}


def get_monthly_stats(provider: str) -> dict:
    """Return this calendar-month usage count, units, and total cost for a provider."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) as calls, SUM(units) as total_units, SUM(cost_usd) as total_cost
                FROM usage_log
                WHERE provider = ?
                  AND strftime('%Y-%m', timestamp) = ?
                """,
                (provider, month),
            ).fetchone()
        return {
            "calls": row["calls"] or 0,
            "total_units": row["total_units"] or 0.0,
            "cost_usd": round(row["total_cost"] or 0.0, 6),
            "month": month,
        }
    except sqlite3.Error as e:
        logger.debug("get_monthly_stats failed: %s", e)
        return {"calls": 0, "total_units": 0.0, "cost_usd": 0.0, "month": month}


def get_hourly_stats(provider: str) -> dict:
    """Return this hour's usage count for a provider."""
    now = datetime.now(timezone.utc)
    hour_prefix = now.strftime("%Y-%m-%d %H:")
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) as calls, SUM(cost_usd) as total_cost
                FROM usage_log
                WHERE provider = ?
                  AND timestamp LIKE ?
                """,
                (provider, hour_prefix + "%"),
            ).fetchone()
        return {
            "calls": row["calls"] or 0,
            "cost_usd": round(row["total_cost"] or 0.0, 6),
        }
    except sqlite3.Error as e:
        logger.debug("get_hourly_stats failed: %s", e)
        return {"calls": 0, "cost_usd": 0.0}


def get_monthly_total_cost() -> float:
    """Return the total cost across all providers for the current calendar month."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    try:
        with _connect() as conn:
            row = conn.execute(
                """
                SELECT SUM(cost_usd) as total
                FROM usage_log
                WHERE strftime('%Y-%m', timestamp) = ?
                  AND is_free = 0
                """,
                (month,),
            ).fetchone()
        return round(row["total"] or 0.0, 6)
    except sqlite3.Error as e:
        logger.debug("get_monthly_total_cost failed: %s", e)
        return 0.0
