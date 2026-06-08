"""
Bot settings persistence.
"""

import psycopg2.extras

from .core import _conn, _lock
from .profiles import create_profile


def get_settings() -> dict:
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT * FROM settings WHERE id = 1")
        row = cur.fetchone()

    if not row:
        return {}

    d = dict(row)
    del d['id']
    if 'btc_series_tickers' in d:
        d['btc_series_tickers'] = [s.strip() for s in d['btc_series_tickers'].split(',') if s.strip()]
    return d


def update_settings(settings: dict):
    if not settings:
        return

    current = get_settings()
    profile_name = settings.get('name')

    allowed_keys = [
        'min_entry_cents', 'max_entry_cents', 'proactive_mode',
        'max_open_orders', 'max_daily_spend_cents',
        'btc_series_tickers', 'exit_strategy', 'limit_sell_price_cents', 'active_profile_id',
        'min_time_to_close_secs', 'max_time_to_close_secs'
    ]
    to_update = {k: v for k, v in settings.items() if k in allowed_keys}
    if not to_update:
        return

    critical_keys = [
        'min_entry_cents', 'max_entry_cents', 'proactive_mode',
        'max_open_orders', 'max_daily_spend_cents',
        'btc_series_tickers', 'exit_strategy', 'limit_sell_price_cents',
        'min_time_to_close_secs', 'max_time_to_close_secs'
    ]
    critical_changed = any(
        k in to_update and to_update[k] != current.get(k)
        for k in critical_keys
    )

    if critical_changed:
        profile_data = current.copy()
        profile_data.update(to_update)
        new_profile_id = create_profile(profile_data, name=profile_name)
        to_update['active_profile_id'] = new_profile_id

    if 'btc_series_tickers' in to_update and isinstance(to_update['btc_series_tickers'], list):
        to_update['btc_series_tickers'] = ",".join(to_update['btc_series_tickers'])

    sets = ", ".join(f"{k} = %s" for k in to_update)
    vals = list(to_update.values())
    query = f"UPDATE settings SET {sets} WHERE id = 1"

    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, vals)
        conn.commit()
