"""
Profile CRUD and activation.
"""

import psycopg2.extras
import logging
from datetime import datetime

import config
import rules as rules_engine
from .core import _conn, _lock

log = logging.getLogger(__name__)


def get_active_profile_id() -> int:
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT active_profile_id FROM settings WHERE id = 1")
        row = cur.fetchone()
    return row[0] if row else None


def create_profile(settings_dict, name=None):
    if not name:
        name = f"Strategy {datetime.utcnow().strftime('%Y-%m-%d %H:%M')}"

    btc_tickers = settings_dict.get('btc_series_tickers', "")
    if isinstance(btc_tickers, list):
        btc_tickers = ",".join(btc_tickers)

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
    """Delete a profile only if it has no historical entry orders."""
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM orders WHERE profile_id = %s AND order_role = 'entry'", (profile_id,))
        count = cur.fetchone()[0]
        if count and count > 0:
            return (False, count)

        cur.execute("SELECT id FROM profiles WHERE id = %s", (profile_id,))
        if not cur.fetchone():
            return (False, None)

        cur.execute("DELETE FROM profiles WHERE id = %s", (profile_id,))

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


def activate_profile(profile_id: int):
    """Mark a profile as active and update the settings pointer."""
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
            p['min_entry_cents'], p['max_entry_cents'], p['proactive_mode'],
            p['max_open_orders'], p['max_daily_spend_cents'], p['btc_series_tickers'],
            p['exit_strategy'], p['limit_sell_price_cents'],
            p.get('min_time_to_close_secs'), p.get('max_time_to_close_secs'),
            psycopg2.extras.Json(p.get('rules')) if p.get('rules') is not None else None,
            profile_id,
        ))
        conn.commit()


def deactivate_profile(profile_id: int):
    """Set is_active = FALSE on a profile; updates settings.active_profile_id if needed."""
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
