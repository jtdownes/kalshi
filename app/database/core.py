"""
Low-level database helpers: connection, raw execute, SQL file runner, and DB init.
"""

import os
import json
import time
import re
import psycopg2
import psycopg2.extras
import threading
import logging
from contextlib import contextmanager
from datetime import datetime, date

import config
import rules as rules_engine

SQL_QUERIES_PATH = "/data/queries"

log = logging.getLogger(__name__)
_lock = threading.Lock()


def _conn():
    """Return a raw psycopg2 connection. Used internally by all db modules."""
    return psycopg2.connect(config.DB_URL)


@contextmanager
def cursor_conn():
    """Yield a DictCursor for use in route handlers that run raw SQL."""
    conn = psycopg2.connect(config.DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            yield cur
    finally:
        conn.close()


def _execute(conn, query, params=None):
    if "INSERT OR IGNORE" in query.upper():
        query = re.sub(r"(?i)INSERT OR IGNORE INTO", "INSERT INTO", query)
        if "ORDERS" in query.upper():
            query += " ON CONFLICT (client_order_id) DO NOTHING"
    query = query.replace("?", "%s")
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(query, params)
    return cur


def execute_sql_file(file_name, params=None):
    """Execute a SQL file from SQL_QUERIES_PATH."""
    sql_file_path = os.path.join(SQL_QUERIES_PATH, file_name)
    with open(sql_file_path, "r") as f:
        query = f.read()
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, params) if params else cur.execute(query)
        conn.commit()
        if cur.description:
            return [dict(r) for r in cur.fetchall()]
        return cur.rowcount


def _backfill_rules():
    """
    One-time auto-conversion: any profile without a `rules` list gets the rule
    set that reproduces its legacy flat-field behaviour. Mirrors the active
    profile's rules into settings so the dashboard reflects them.
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("""
            SELECT id, min_entry_cents, max_entry_cents, proactive_mode,
                   min_time_to_close_secs, max_time_to_close_secs,
                   exit_strategy, limit_sell_price_cents
            FROM profiles
            WHERE rules IS NULL
        """)
        legacy_rows = [dict(r) for r in cur.fetchall()]
        for p in legacy_rows:
            rule_list = rules_engine.legacy_profile_to_rules(p)
            cur.execute("UPDATE profiles SET rules = %s WHERE id = %s",
                        (psycopg2.extras.Json(rule_list), p["id"]))

        cur.execute("""
            UPDATE settings s SET rules = p.rules
            FROM profiles p
            WHERE s.id = 1 AND p.id = s.active_profile_id
        """)
        conn.commit()
        if legacy_rows:
            log.info("Backfilled rules for %d legacy profile(s)", len(legacy_rows))


def init_db():
    execute_sql_file("0_initialization.sql")
    execute_sql_file("1_sync_sequences.sql")

    count_rows = execute_sql_file("2_check_settings_count.sql")
    settings_count = count_rows[0]['count'] if count_rows else 0

    if settings_count == 0:
        now = datetime.utcnow().isoformat()
        profile_rows = execute_sql_file("3_seed_default_profile.sql", (
            "Default", now, config.MIN_ENTRY_CENTS, config.MAX_ENTRY_CENTS, config.PROACTIVE_MODE,
            config.MAX_OPEN_ORDERS, config.MAX_DAILY_SPEND_CENTS,
            ",".join(config.BTC_SERIES_TICKERS),
            'hold_to_expiration', None,
        ))
        default_profile_id = profile_rows[0]['id']

        execute_sql_file("4_seed_default_settings.sql", (
            config.MIN_ENTRY_CENTS, config.MAX_ENTRY_CENTS, config.PROACTIVE_MODE,
            config.MAX_OPEN_ORDERS, config.MAX_DAILY_SPEND_CENTS,
            ",".join(config.BTC_SERIES_TICKERS),
            'hold_to_expiration', None, default_profile_id,
        ))
        execute_sql_file("5_link_orphan_orders.sql", (default_profile_id,))
    else:
        active_rows = execute_sql_file("6_get_active_profile_id.sql")
        active_profile_id = active_rows[0]['active_profile_id'] if active_rows else None

        if active_profile_id is None:
            profile_rows = execute_sql_file("7_get_first_profile.sql")
            if not profile_rows:
                now = datetime.utcnow().isoformat()
                settings_rows = execute_sql_file("8_get_settings_for_migration.sql")
                s = settings_rows[0]
                new_profile_rows = execute_sql_file("3_seed_default_profile.sql", (
                    "Default", now, s['min_entry_cents'], s['max_entry_cents'], s['proactive_mode'],
                    s['max_open_orders'], s['max_daily_spend_cents'],
                    s['btc_series_tickers'], s['exit_strategy'], s['limit_sell_price_cents'],
                ))
                pid = new_profile_rows[0]['id']
            else:
                pid = profile_rows[0]['id']

            execute_sql_file("9_set_active_profile.sql", (pid,))
            execute_sql_file("5_link_orphan_orders.sql", (pid,))

    _backfill_rules()
    log.info("Database ready: %s (postgres)", config.DB_URL)
