"""
Weather observation snapshots.
"""

import psycopg2.extras

from .core import _conn, _lock


def save_weather_snapshot(station, scanned_at, obs_date, max_temp_f, min_temp_f,
                          precip_in, issued, raw_excerpt, source_url=None):
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO weather_snapshots
              (station, scanned_at, obs_date, max_temp_f, min_temp_f, precip_in, issued, raw_excerpt, source_url)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (station, scanned_at, obs_date, max_temp_f, min_temp_f, precip_in, issued, raw_excerpt, source_url))
        conn.commit()


def get_latest_weather_snapshot(station: str) -> dict | None:
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT station, obs_date, max_temp_f, min_temp_f, precip_in, issued
            FROM weather_snapshots WHERE station = %s
            ORDER BY scanned_at DESC LIMIT 1
        """, (station,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_recent_weather_snapshots(limit: int = 100) -> list[dict]:
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT station, scanned_at, obs_date, max_temp_f, min_temp_f, precip_in, issued, source_url
            FROM weather_snapshots ORDER BY scanned_at DESC LIMIT %s
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]
