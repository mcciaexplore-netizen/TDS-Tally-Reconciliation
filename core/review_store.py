"""Local-only reviewer decisions for the desktop reconciliation app."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "reconciliation_review.db"


def _connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute("""CREATE TABLE IF NOT EXISTS reviewer_aliases (
        portal_name TEXT NOT NULL, tally_name TEXT NOT NULL, financial_year TEXT NOT NULL DEFAULT '',
        reviewer TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
        PRIMARY KEY (portal_name, financial_year)
    )""")
    return connection


def load_local_aliases(financial_year: str | None = None) -> dict[str, str]:
    with _connection() as connection:
        if financial_year:
            rows = connection.execute("SELECT portal_name, tally_name FROM reviewer_aliases WHERE financial_year IN ('', ?) ORDER BY created_at", (financial_year,)).fetchall()
        else:
            rows = connection.execute("SELECT portal_name, tally_name FROM reviewer_aliases ORDER BY created_at").fetchall()
    return dict(rows)


def save_alias(portal_name: str, tally_name: str, financial_year: str | None = None, reviewer: str = "", reason: str = "reviewer approved") -> None:
    if not portal_name.strip() or not tally_name.strip():
        raise ValueError("Portal and Tally company names are required.")
    with _connection() as connection:
        connection.execute(
            """INSERT INTO reviewer_aliases(portal_name, tally_name, financial_year, reviewer, reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(portal_name, financial_year) DO UPDATE SET
               tally_name=excluded.tally_name, reviewer=excluded.reviewer, reason=excluded.reason, created_at=excluded.created_at""",
            (portal_name.strip(), tally_name.strip(), financial_year or "", reviewer.strip(), reason.strip(), datetime.now(timezone.utc).isoformat()),
        )


def export_aliases() -> list[dict[str, str]]:
    with _connection() as connection:
        rows = connection.execute("SELECT portal_name, tally_name, financial_year, reviewer, reason, created_at FROM reviewer_aliases ORDER BY created_at DESC").fetchall()
    keys = ("portal_name", "tally_name", "financial_year", "reviewer", "reason", "created_at")
    return [dict(zip(keys, row)) for row in rows]
