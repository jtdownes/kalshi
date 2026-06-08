"""
Scanned series management — which Kalshi series the snapshot scanner polls.
"""

import psycopg2.extras
from datetime import datetime

from .core import _conn, _lock


def get_scanned_series(enabled_only: bool = False) -> list[dict]:
    where = "WHERE enabled = TRUE" if enabled_only else ""
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(f"""
            SELECT series_ticker, label, look_ahead_seconds, interval_seconds, enabled, added_at
            FROM scanned_series {where} ORDER BY added_at, series_ticker
        """)
        return [dict(r) for r in cur.fetchall()]


def add_scanned_series(series_ticker: str, label: str | None,
                       look_ahead_seconds: int, interval_seconds: int) -> dict:
    now = datetime.utcnow().isoformat()
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            INSERT INTO scanned_series
                (series_ticker, label, look_ahead_seconds, interval_seconds, enabled, added_at)
            VALUES (%s, %s, %s, %s, TRUE, %s)
            ON CONFLICT (series_ticker) DO UPDATE SET
                label = EXCLUDED.label,
                look_ahead_seconds = EXCLUDED.look_ahead_seconds,
                interval_seconds = EXCLUDED.interval_seconds,
                enabled = TRUE
            RETURNING series_ticker, label, look_ahead_seconds, interval_seconds, enabled, added_at
        """, (series_ticker, label, look_ahead_seconds, interval_seconds, now))
        conn.commit()
        return dict(cur.fetchone())


def remove_scanned_series(series_ticker: str) -> bool:
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM scanned_series WHERE series_ticker = %s", (series_ticker,))
        conn.commit()
        return cur.rowcount > 0


def set_scanned_series_enabled(series_ticker: str, enabled: bool) -> bool:
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE scanned_series SET enabled = %s WHERE series_ticker = %s",
                    (enabled, series_ticker))
        conn.commit()
        return cur.rowcount > 0
