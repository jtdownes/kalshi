"""
PostgreSQL persistence for the Kalshi bot.
"""

import os
import json
import time
import psycopg2
import psycopg2.extras
import threading
import logging
from datetime import datetime, date

import config
import rules as rules_engine

SQL_QUERIES_PATH = "/data/queries"

log = logging.getLogger(__name__)
_lock = threading.Lock()

def _conn():
    conn = psycopg2.connect(config.DB_URL)
    return conn

def _execute(conn, query, params=None):
    # Handle SQLite's INSERT OR IGNORE -> Postgres INSERT ... ON CONFLICT DO NOTHING
    if "INSERT OR IGNORE" in query.upper():
        import re
        query = re.sub(r"(?i)INSERT OR IGNORE INTO", "INSERT INTO", query)
        if "ORDERS" in query.upper():
            query += " ON CONFLICT (client_order_id) DO NOTHING"
    
    # Convert ? to %s for psycopg2
    query = query.replace("?", "%s")
    
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(query, params)
    return cur

def execute_sql_file(file_name, params=None):
    """Execute a SQL file from SQL_QUERIES_PATH. file_name is relative to that directory."""
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

        # Keep settings.rules in sync with the active profile.
        cur.execute("""
            UPDATE settings s SET rules = p.rules
            FROM profiles p
            WHERE s.id = 1 AND p.id = s.active_profile_id
        """)
        conn.commit()
        if legacy_rows:
            log.info("Backfilled rules for %d legacy profile(s)", len(legacy_rows))

def get_active_profile_id() -> int:
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT active_profile_id FROM settings WHERE id = 1")
        row = cur.fetchone()
    return row[0] if row else None

def create_profile(settings_dict, name=None):
    if not name:
        name = f"Strategy {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"
    
    # Ensure btc_series_tickers is string
    btc_tickers = settings_dict.get('btc_series_tickers', "")
    if isinstance(btc_tickers, list):
        btc_tickers = ",".join(btc_tickers)

    # Every profile carries a rule list. If the caller supplied one use it,
    # otherwise derive the equivalent rules from the flat fields so legacy
    # create paths (env-seeded defaults) still produce a working strategy.
    rule_list = settings_dict.get('rules')
    if rule_list is None:
        rule_list = rules_engine.legacy_profile_to_rules(settings_dict)

    query = """
        INSERT INTO profiles (
            name, created_at, min_entry_cents, max_entry_cents, proactive_mode,
            max_open_orders, max_daily_spend_cents,
            btc_series_tickers, exit_strategy, limit_sell_price_cents,
            min_time_to_close_secs, max_time_to_close_secs, rules
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """
    # Flat fields are vestigial under the rule engine (entry logic lives in
    # `rules`), but the columns are NOT NULL and the safety caps still use
    # max_open_orders / max_daily_spend_cents, so default any the caller omits.
    params = (
        name, datetime.utcnow().isoformat(),
        settings_dict.get('min_entry_cents', config.MIN_ENTRY_CENTS),
        settings_dict.get('max_entry_cents', config.MAX_ENTRY_CENTS),
        settings_dict.get('proactive_mode', config.PROACTIVE_MODE),
        settings_dict.get('max_open_orders', config.MAX_OPEN_ORDERS),
        settings_dict.get('max_daily_spend_cents', config.MAX_DAILY_SPEND_CENTS),
        btc_tickers,
        settings_dict.get('exit_strategy', 'hold_to_expiration'),
        settings_dict.get('limit_sell_price_cents'),
        settings_dict.get('min_time_to_close_secs'),
        settings_dict.get('max_time_to_close_secs'),
        psycopg2.extras.Json(rule_list),
    )
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        profile_id = cur.fetchone()[0]
        conn.commit()
    return profile_id

def update_profile(profile_id: int, settings_dict: dict):
    allowed_keys = [
        'name', 'min_entry_cents', 'max_entry_cents', 'proactive_mode',
        'max_open_orders', 'max_daily_spend_cents',
        'btc_series_tickers', 'exit_strategy', 'limit_sell_price_cents',
        'min_time_to_close_secs', 'max_time_to_close_secs', 'rules'
    ]
    to_update = {k: v for k, v in settings_dict.items() if k in allowed_keys}
    if not to_update:
        return

    if 'btc_series_tickers' in to_update and isinstance(to_update['btc_series_tickers'], list):
        to_update['btc_series_tickers'] = ",".join(to_update['btc_series_tickers'])
    if 'rules' in to_update:
        to_update['rules'] = psycopg2.extras.Json(to_update['rules'])

    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM profiles WHERE id = %s", (profile_id,))
        if not cur.fetchone():
            raise ValueError(f"Profile {profile_id} not found")

        sets = ", ".join(f"{k} = %s" for k in to_update)
        vals = list(to_update.values()) + [profile_id]
        cur.execute(f"UPDATE profiles SET {sets} WHERE id = %s", vals)

        cur.execute("SELECT active_profile_id FROM settings WHERE id = 1")
        row = cur.fetchone()
        if row and row[0] == profile_id:
            cur.execute("""
                UPDATE settings SET
                    min_entry_cents        = p.min_entry_cents,
                    max_entry_cents        = p.max_entry_cents,
                    proactive_mode         = p.proactive_mode,
                    max_open_orders        = p.max_open_orders,
                    max_daily_spend_cents  = p.max_daily_spend_cents,
                    btc_series_tickers     = p.btc_series_tickers,
                    exit_strategy          = p.exit_strategy,
                    limit_sell_price_cents = p.limit_sell_price_cents,
                    min_time_to_close_secs = p.min_time_to_close_secs,
                    max_time_to_close_secs = p.max_time_to_close_secs,
                    rules                  = p.rules
                FROM profiles p
                WHERE settings.id = 1 AND p.id = %s
            """, (profile_id,))
        conn.commit()


def delete_profile(profile_id: int) -> tuple[bool, int | None]:
    """
    Delete a profile only if it has no historical entry orders.
    Returns (True, 0) on success.
    Returns (False, count) if there are existing entry orders (count > 0).
    Returns (False, None) if the profile was not found.
    """
    with _lock, _conn() as conn:
        cur = conn.cursor()
        # Count any entry orders for this profile
        cur.execute("SELECT COUNT(*) FROM orders WHERE profile_id = %s AND order_role = 'entry'", (profile_id,))
        row = cur.fetchone()
        count = row[0] if row else 0
        if count and count > 0:
            return (False, count)

        # Ensure profile exists
        cur.execute("SELECT id FROM profiles WHERE id = %s", (profile_id,))
        if not cur.fetchone():
            return (False, None)

        # Delete profile
        cur.execute("DELETE FROM profiles WHERE id = %s", (profile_id,))

        # If this was the active profile, pick another or null
        cur.execute("SELECT active_profile_id FROM settings WHERE id = 1")
        r = cur.fetchone()
        if r and r[0] == profile_id:
            cur.execute("SELECT id FROM profiles ORDER BY created_at DESC LIMIT 1")
            new = cur.fetchone()
            if new:
                cur.execute("UPDATE settings SET active_profile_id = %s WHERE id = 1", (new[0],))
            else:
                cur.execute("UPDATE settings SET active_profile_id = NULL WHERE id = 1")

        conn.commit()
    return (True, 0)

def save_order(client_order_id: str, market_ticker: str, side: str,
               entry_price_cents: int, kalshi_order_id: str = None,
               btc_price: float = None, distance_to_strike: float = None,
               market_close_time: str = None, time_to_close_seconds: int = None,
               profile_id: int = None, order_role: str = 'entry',
               parent_kalshi_order_id: str = None,
               exit_strategy: str = 'hold_to_expiration',
               exit_target_cents: int = None, count: int = 1,
               entry_rule_id: str = None, cancel_sibling_on_fill: bool = False):
    now = datetime.utcnow().isoformat()
    query = """
        INSERT OR IGNORE INTO orders
          (client_order_id, kalshi_order_id, market_ticker, side,
           entry_price_cents, count, placed_at, btc_price_at_placement,
           distance_to_strike_at_placement, market_close_time,
           time_to_close_at_placement, profile_id, order_role,
           parent_kalshi_order_id, exit_strategy, exit_target_cents,
           entry_rule_id, cancel_sibling_on_fill)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (client_order_id, kalshi_order_id, market_ticker, side,
              entry_price_cents, count, now, btc_price, distance_to_strike,
              market_close_time, time_to_close_seconds, profile_id,
              order_role, parent_kalshi_order_id, exit_strategy,
              exit_target_cents, entry_rule_id, cancel_sibling_on_fill)

    with _lock, _conn() as conn:
        _execute(conn, query, params)
        conn.commit()

def update_order(kalshi_order_id: str, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k} = %s" for k in fields)
    vals = list(fields.values()) + [kalshi_order_id]
    query = f"UPDATE orders SET {sets} WHERE kalshi_order_id = %s"
    
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, vals)
        conn.commit()

def has_open_order(market_ticker: str, side: str, profile_id: int | None = None) -> bool:
    if profile_id is not None:
        query = "SELECT 1 FROM orders WHERE market_ticker = %s AND side = %s AND profile_id = %s AND order_role = 'entry' AND status IN ('resting', 'pending', 'filled')"
        params = (market_ticker, side, profile_id)
    else:
        query = "SELECT 1 FROM orders WHERE market_ticker = %s AND side = %s AND order_role = 'entry' AND status IN ('resting', 'pending', 'filled')"
        params = (market_ticker, side)
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
    return row is not None

def has_open_order_for_rule(market_ticker: str, side: str, entry_rule_id: str,
                            profile_id: int | None = None) -> bool:
    """
    Per-rule dedup for the laddering engine: has THIS rule already rested/filled
    an entry on this market+side? Lets multiple rules ladder the same market
    while each rule places its own rung exactly once.
    """
    clauses = ["market_ticker = %s", "side = %s", "entry_rule_id = %s",
               "order_role = 'entry'", "status IN ('resting', 'pending', 'filled')"]
    params = [market_ticker, side, entry_rule_id]
    if profile_id is not None:
        clauses.append("profile_id = %s")
        params.append(profile_id)
    query = f"SELECT 1 FROM orders WHERE {' AND '.join(clauses)} LIMIT 1"
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
    return row is not None

def has_filled_entry_for_rule(market_ticker: str, entry_rule_id: str,
                              profile_id: int | None = None) -> bool:
    """
    Has any entry leg of this rule already filled on this market? Used to stop
    an OCO rule from re-placing a cancelled sibling leg after its partner filled.
    """
    if not entry_rule_id:
        return False
    clauses = ["market_ticker = %s", "entry_rule_id = %s",
               "order_role = 'entry'", "status = 'filled'"]
    params = [market_ticker, entry_rule_id]
    if profile_id is not None:
        clauses.append("profile_id = %s")
        params.append(profile_id)
    query = f"SELECT 1 FROM orders WHERE {' AND '.join(clauses)} LIMIT 1"
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
    return row is not None

def get_today_spend_cents(profile_id: int | None = None) -> int:
    today = date.today().isoformat()
    if profile_id is not None:
        query = """
            SELECT COALESCE(SUM(entry_price_cents * count), 0)
            FROM orders
            WHERE profile_id = %s AND order_role = 'entry'
              AND status IN ('resting', 'filled') AND placed_at::date = %s
        """
        params = (profile_id, today)
    else:
        query = """
            SELECT COALESCE(SUM(entry_price_cents * count), 0)
            FROM orders
            WHERE order_role = 'entry' AND status IN ('resting', 'filled') AND placed_at::date = %s
        """
        params = (today,)
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
    return row[0] if row else 0

def count_resting_orders(profile_id: int | None = None) -> int:
    if profile_id is not None:
        query = "SELECT COUNT(*) FROM orders WHERE profile_id = %s AND order_role = 'entry' AND status = 'resting'"
        params = (profile_id,)
    else:
        query = "SELECT COUNT(*) FROM orders WHERE order_role = 'entry' AND status = 'resting'"
        params = None
    with _lock, _conn() as conn:
        cur = conn.cursor()
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        row = cur.fetchone()
    return row[0] if row else 0

def get_resting_orders() -> list[dict]:
    query = """
        SELECT kalshi_order_id, market_ticker, side, entry_price_cents,
               count, market_close_time, profile_id, order_role,
               parent_kalshi_order_id, exit_order_kalshi_id,
               exit_strategy, exit_target_cents,
               entry_rule_id, cancel_sibling_on_fill
        FROM orders
        WHERE status = 'resting'
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_sibling_resting_entries(market_ticker: str, entry_rule_id: str,
                                exclude_kalshi_order_id: str,
                                profile_id: int | None = None) -> list[dict]:
    """
    Resting entry orders from the SAME rule on the SAME market, excluding the
    given order — i.e. the other OCO legs to cancel when one fills.
    """
    if not entry_rule_id:
        return []
    clauses = ["market_ticker = %s", "entry_rule_id = %s", "order_role = 'entry'",
               "status = 'resting'", "kalshi_order_id IS DISTINCT FROM %s"]
    params = [market_ticker, entry_rule_id, exclude_kalshi_order_id]
    if profile_id is not None:
        clauses.append("profile_id = %s")
        params.append(profile_id)
    query = f"SELECT kalshi_order_id, side FROM orders WHERE {' AND '.join(clauses)}"
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, params)
        rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_filled_without_outcome() -> list[dict]:
    query = """
        SELECT kalshi_order_id, market_ticker, side, entry_price_cents,
               count, market_close_time
        FROM orders
        WHERE order_role = 'entry'
          AND status = 'filled'
          AND outcome IS NULL
          AND closed_at IS NULL
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_order_by_kalshi_order_id(kalshi_order_id: str) -> dict | None:
    query = "SELECT * FROM orders WHERE kalshi_order_id = %s"
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, (kalshi_order_id,))
        row = cur.fetchone()
    return dict(row) if row else None

def close_entry_order_with_exit(parent_kalshi_order_id: str, close_price_cents: int,
                                closed_at: str = None, close_reason: str = 'limit_sell'):
    parent = get_order_by_kalshi_order_id(parent_kalshi_order_id)
    if not parent:
        return
    if parent.get('closed_at'):
        return

    if closed_at is None:
        closed_at = datetime.utcnow().isoformat()

    count = parent.get('count') or 1
    net_profit_cents = (close_price_cents - parent['entry_price_cents']) * count

    update_order(
        parent_kalshi_order_id,
        closed_at=closed_at,
        close_reason=close_reason,
        close_price_cents=close_price_cents,
        payout_cents=close_price_cents * count,
        net_profit_cents=net_profit_cents,
    )

def save_bitcoin_snapshot(scanned_at: str, coinbase_price: float = None,
                          kraken_price: float = None, bitstamp_price: float = None,
                          gemini_price: float = None, consolidated_price: float = None,
                          coinbase_volume: float = None, kraken_volume: float = None,
                          bitstamp_volume: float = None, gemini_volume: float = None):
    """One bitcoin price/volume row per collection pass. Shares scanned_at with
    all market_snapshots rows from the same pass so they join on the tick."""
    query = """
        INSERT INTO bitcoin_snapshots
          (scanned_at, coinbase_price, kraken_price, bitstamp_price, gemini_price,
           consolidated_price, coinbase_volume, kraken_volume, bitstamp_volume, gemini_volume)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (scanned_at, coinbase_price, kraken_price, bitstamp_price, gemini_price,
              consolidated_price, coinbase_volume, kraken_volume, bitstamp_volume, gemini_volume)
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()


def save_market_snapshot(ticker: str, title: str, close_time: str,
                         yes_ask: float | None, yes_bid: float | None,
                         no_ask: float | None, no_bid: float | None,
                         time_to_close_secs: int, scanned_at: str = None,
                         strike_str: str = None, volume: int = None,
                         open_interest: int = None):
    # Bitcoin price/volume now lives in bitcoin_snapshots, joined on scanned_at.
    # Pass the pass-wide scanned_at so this row shares the tick with its bitcoin row.
    now = scanned_at or datetime.utcnow().isoformat()
    query = """
        INSERT INTO market_snapshots
          (ticker, title, scanned_at, close_time, yes_ask, yes_bid,
           no_ask, no_bid, time_to_close_secs, strike_str, volume, open_interest)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (ticker, title, now, close_time, yes_ask, yes_bid, no_ask, no_bid,
              time_to_close_secs, strike_str, volume, open_interest)

    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()

# ── Weather observations (NWS CLI settlement temps) ───────────────────────────
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


# ── Scanned series (which Kalshi series the snapshot scanner polls) ────────────
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


def get_recent_market_snapshots(limit: int | None = None) -> list[dict]:
    limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""
    query = f"""
        SELECT m.id, m.ticker, m.title, m.scanned_at, m.close_time,
               m.yes_ask, m.no_ask, m.yes_bid, m.no_bid,
               COALESCE(b.consolidated_price, b.coinbase_price) AS btc_price,
               b.consolidated_price AS brti_price,
               b.coinbase_price, b.kraken_price, b.bitstamp_price, b.gemini_price,
               b.coinbase_volume, b.kraken_volume, b.bitstamp_volume, b.gemini_volume,
               m.time_to_close_secs, m.strike_str, m.volume, m.open_interest
        FROM market_snapshots m
        LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
        ORDER BY m.id DESC
        {limit_sql}
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_market_snapshots_for_ticker(ticker: str, limit: int | None = None) -> list[dict]:
    limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""
    query = f"""
        SELECT m.id, m.ticker, m.title, m.scanned_at, m.close_time,
               m.yes_ask, m.no_ask, m.yes_bid, m.no_bid,
               COALESCE(b.consolidated_price, b.coinbase_price) AS btc_price,
               b.consolidated_price AS brti_price,
               b.coinbase_price, b.kraken_price, b.bitstamp_price, b.gemini_price,
               b.coinbase_volume, b.kraken_volume, b.bitstamp_volume, b.gemini_volume,
               m.time_to_close_secs, m.strike_str, m.volume, m.open_interest
        FROM market_snapshots m
        LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
        WHERE m.ticker = %s
        ORDER BY m.id DESC
        {limit_sql}
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, (ticker,))
        rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_latest_snapshots_for_series(series_tickers: list[str], max_age_seconds: int = 15) -> list[dict]:
    if not series_tickers:
        return []

    where = " OR ".join("m.ticker LIKE %s" for _ in series_tickers)
    params = [f"{series}-%" for series in series_tickers]
    params.append(str(max_age_seconds))
    query = f"""
        SELECT DISTINCT ON (m.ticker)
               m.id, m.ticker, m.title, m.scanned_at, m.close_time,
               m.yes_ask, m.no_ask, m.yes_bid, m.no_bid,
               COALESCE(b.consolidated_price, b.coinbase_price) AS btc_price,
               b.consolidated_price AS brti_price,
               b.coinbase_price, b.kraken_price, b.bitstamp_price, b.gemini_price,
               b.coinbase_volume, b.kraken_volume, b.bitstamp_volume, b.gemini_volume,
               m.time_to_close_secs, m.strike_str, m.volume, m.open_interest
        FROM market_snapshots m
        LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
        WHERE ({where})
          AND m.scanned_at::timestamp >= ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - (%s || ' seconds')::interval)
        ORDER BY m.ticker, m.scanned_at DESC
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, params)
        rows = cur.fetchall()
    return [dict(r) for r in rows]

# Resolution of a *closed* 15-min window never changes, so memoise it.
# Key: (series_prefix, window_close_str) -> 1 | 0.
_window_res_cache: dict = {}


def _window_resolution(cur, series_prefix: str, window_close: str):
    """
    Resolve a single window (identified by its close_time string) to 1 (YES) or
    0 (NO) using the *final* snapshot's price, matching the backtest's
    hold-to-expiration settlement (yes_bid, falling back to yes_ask, >= 50).

    Returns None when no snapshot exists for that window. Only windows that have
    actually closed are cached, so an in-progress window isn't pinned early.
    """
    key = (series_prefix, window_close)
    cached = _window_res_cache.get(key)
    if cached is not None:
        return cached

    cur.execute("""
        SELECT yes_bid, yes_ask
        FROM market_snapshots
        WHERE close_time = %s AND ticker LIKE %s
        ORDER BY scanned_at DESC
        LIMIT 1
    """, [window_close, series_prefix + "%"])
    row = cur.fetchone()
    if row is None:
        return None

    ref = row["yes_bid"] if row["yes_bid"] is not None else row["yes_ask"]
    res = 1 if (ref is not None and ref >= 50) else 0

    try:
        if int(window_close) < int(time.time()):
            _window_res_cache[key] = res
    except (TypeError, ValueError):
        pass
    return res


def get_prior_resolutions_for_close(series_prefix: str, close_time_str: str) -> dict:
    """
    Given a series prefix (e.g. 'KXBTC15M') and a market's close_time string
    (Unix seconds as text), look up whether the previous one and two sequential
    15-min windows resolved YES (1) or NO (0).

    Returns {"prior_resolution": 1|0|None, "prev2_resolution": 1|0|None}.
    None means no snapshot data exists for that window.
    """
    try:
        ct = int(float(close_time_str))
    except (TypeError, ValueError):
        return {"prior_resolution": None, "prev2_resolution": None}

    prev1 = str(ct - 900)
    prev2 = str(ct - 1800)

    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        r1 = _window_resolution(cur, series_prefix, prev1)
        r2 = _window_resolution(cur, series_prefix, prev2)

    return {"prior_resolution": r1, "prev2_resolution": r2}


def get_settings() -> dict:
    query = "SELECT * FROM settings WHERE id = 1"
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        row = cur.fetchone()
    
    if not row:
        return {}
    
    d = dict(row)
    del d['id']
    # Convert comma-separated string back to list
    if 'btc_series_tickers' in d:
        d['btc_series_tickers'] = [s.strip() for s in d['btc_series_tickers'].split(',') if s.strip()]
    return d

def update_settings(settings: dict):
    if not settings:
        return
    
    current = get_settings()
    profile_name = settings.get('name')
    
    # Filter settings to only valid columns
    allowed_keys = [
        'min_entry_cents', 'max_entry_cents', 'proactive_mode',
        'max_open_orders', 'max_daily_spend_cents',
        'btc_series_tickers', 'exit_strategy', 'limit_sell_price_cents', 'active_profile_id',
        'min_time_to_close_secs', 'max_time_to_close_secs'
    ]
    to_update = {k: v for k, v in settings.items() if k in allowed_keys}
    if not to_update:
        return

    critical_changed = False
    critical_keys = [
        'min_entry_cents', 'max_entry_cents', 'proactive_mode',
        'max_open_orders', 'max_daily_spend_cents',
        'btc_series_tickers', 'exit_strategy', 'limit_sell_price_cents',
        'min_time_to_close_secs', 'max_time_to_close_secs'
    ]
    
    for k in critical_keys:
        if k in to_update and to_update[k] != current.get(k):
            critical_changed = True
            break
            
    if critical_changed:
        # Merge current settings with updates for profile creation
        profile_data = current.copy()
        profile_data.update(to_update)
        new_profile_id = create_profile(profile_data, name=profile_name)
        to_update['active_profile_id'] = new_profile_id

    # Handle btc_series_tickers list -> string
    if 'btc_series_tickers' in to_update and isinstance(to_update['btc_series_tickers'], list):
        to_update['btc_series_tickers'] = ",".join(to_update['btc_series_tickers'])

    sets = ", ".join(f"{k} = %s" for k in to_update)
    vals = list(to_update.values())
    query = f"UPDATE settings SET {sets} WHERE id = 1"
    
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, vals)
        conn.commit()

def activate_profile(profile_id: int):
    """Mark a profile as active (does not deactivate others) and update settings pointer."""
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM profiles WHERE id = %s", (profile_id,))
        row = cur.fetchone()
        if not row:
            raise ValueError(f"Profile {profile_id} not found")
        p = dict(row)
        cur.execute("UPDATE profiles SET is_active = TRUE WHERE id = %s", (profile_id,))
        cur.execute("""
            UPDATE settings SET
                min_entry_cents        = %s,
                max_entry_cents        = %s,
                proactive_mode         = %s,
                max_open_orders        = %s,
                max_daily_spend_cents  = %s,
                btc_series_tickers     = %s,
                exit_strategy          = %s,
                limit_sell_price_cents = %s,
                min_time_to_close_secs = %s,
                max_time_to_close_secs = %s,
                rules                  = %s,
                active_profile_id      = %s
            WHERE id = 1
        """, (
            p['min_entry_cents'],
            p['max_entry_cents'],
            p['proactive_mode'],
            p['max_open_orders'],
            p['max_daily_spend_cents'],
            p['btc_series_tickers'],
            p['exit_strategy'],
            p['limit_sell_price_cents'],
            p.get('min_time_to_close_secs'),
            p.get('max_time_to_close_secs'),
            psycopg2.extras.Json(p.get('rules')) if p.get('rules') is not None else None,
            profile_id,
        ))
        conn.commit()

def deactivate_profile(profile_id: int):
    """Set is_active = FALSE on a profile. Updates settings.active_profile_id if needed."""
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM profiles WHERE id = %s", (profile_id,))
        if not cur.fetchone():
            raise ValueError(f"Profile {profile_id} not found")
        cur.execute("UPDATE profiles SET is_active = FALSE WHERE id = %s", (profile_id,))
        cur.execute("SELECT active_profile_id FROM settings WHERE id = 1")
        row = cur.fetchone()
        if row and row[0] == profile_id:
            cur.execute(
                "SELECT id FROM profiles WHERE is_active = TRUE AND id != %s ORDER BY id LIMIT 1",
                (profile_id,)
            )
            next_row = cur.fetchone()
            next_id = next_row[0] if next_row else None
            cur.execute("UPDATE settings SET active_profile_id = %s WHERE id = 1", (next_id,))
        conn.commit()

def get_active_profiles() -> list[dict]:
    """Return all profiles where is_active = TRUE, with btc_series_tickers as a list."""
    query = """
        SELECT id, name, created_at, is_active,
               min_entry_cents, max_entry_cents, proactive_mode,
               max_open_orders, max_daily_spend_cents,
               btc_series_tickers, exit_strategy, limit_sell_price_cents,
               min_time_to_close_secs, max_time_to_close_secs, rules
        FROM profiles
        WHERE is_active = TRUE
        ORDER BY id
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        rows = cur.fetchall()
    result = []
    for r in rows:
        d = dict(r)
        if 'btc_series_tickers' in d:
            d['btc_series_tickers'] = [s.strip() for s in d['btc_series_tickers'].split(',') if s.strip()]
        result.append(d)
    return result
