"""
PostgreSQL persistence for the Kalshi bot.
"""

import psycopg2
import psycopg2.extras
import threading
import logging
from datetime import datetime, date

import config

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

def init_db():
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS profiles (
                id                      SERIAL PRIMARY KEY,
                name                    TEXT NOT NULL,
                created_at              TEXT NOT NULL,
                min_entry_cents         INTEGER NOT NULL,
                max_entry_cents         INTEGER NOT NULL,
                proactive_mode          BOOLEAN NOT NULL,
                max_open_orders         INTEGER NOT NULL,
                max_daily_spend_cents   INTEGER NOT NULL,
                scan_interval_seconds   INTEGER NOT NULL,
                btc_series_tickers      TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS orders (
                id                              SERIAL PRIMARY KEY,
                kalshi_order_id                 TEXT UNIQUE,
                client_order_id                 TEXT UNIQUE NOT NULL,
                market_ticker                   TEXT NOT NULL,
                side                            TEXT NOT NULL,
                entry_price_cents               INTEGER NOT NULL,
                count                           INTEGER NOT NULL DEFAULT 1,
                status                          TEXT NOT NULL DEFAULT 'resting',
                placed_at                       TEXT NOT NULL,
                filled_at                       TEXT,
                btc_price_at_placement          REAL,
                btc_price_at_fill               REAL,
                distance_to_strike_at_placement REAL,
                market_close_time               TEXT,
                time_to_close_at_placement      INTEGER,
                outcome                         TEXT,
                payout_cents                    INTEGER,
                fee_cents                       INTEGER,
                net_profit_cents                INTEGER,
                notes                           TEXT,
                profile_id                      INTEGER
            );

            -- Add profile_id to orders if it doesn't exist
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='profile_id') THEN
                    ALTER TABLE orders ADD COLUMN profile_id INTEGER;
                END IF;
            END $$;

            CREATE TABLE IF NOT EXISTS market_snapshots (
                id                   SERIAL PRIMARY KEY,
                ticker               TEXT NOT NULL,
                title                TEXT,
                scanned_at           TEXT NOT NULL,
                close_time           TEXT,
                yes_ask              INTEGER,
                yes_bid              INTEGER,
                no_ask               INTEGER,
                no_bid               INTEGER,
                btc_price            REAL,
                time_to_close_secs   INTEGER,
                strike_str           TEXT,
                volume               INTEGER,
                open_interest        INTEGER
            );

            CREATE TABLE IF NOT EXISTS btc_prices (
                id          SERIAL PRIMARY KEY,
                recorded_at TEXT NOT NULL,
                price       REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                id                     INTEGER PRIMARY KEY CHECK (id = 1),
                min_entry_cents        INTEGER NOT NULL,
                max_entry_cents        INTEGER NOT NULL,
                proactive_mode         BOOLEAN NOT NULL,
                max_open_orders        INTEGER NOT NULL,
                max_daily_spend_cents  INTEGER NOT NULL,
                scan_interval_seconds  INTEGER NOT NULL,
                btc_series_tickers     TEXT NOT NULL,
                active_profile_id      INTEGER
            );

            -- Add active_profile_id to settings if it doesn't exist
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='settings' AND column_name='active_profile_id') THEN
                    ALTER TABLE settings ADD COLUMN active_profile_id INTEGER;
                END IF;
            END $$;

            CREATE INDEX IF NOT EXISTS idx_orders_ticker  ON orders(market_ticker);
            CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_snaps_ticker   ON market_snapshots(ticker);
            CREATE INDEX IF NOT EXISTS idx_btc_time       ON btc_prices(recorded_at);
        """)
        
        # Sync sequences in case rows were manually inserted
        cur.execute("SELECT setval(pg_get_serial_sequence('orders', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM orders")
        cur.execute("SELECT setval(pg_get_serial_sequence('market_snapshots', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM market_snapshots")
        cur.execute("SELECT setval(pg_get_serial_sequence('btc_prices', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM btc_prices")
        
        # Initial settings if empty
        cur.execute("SELECT COUNT(*) FROM settings")
        if cur.fetchone()[0] == 0:
            # Create default profile
            now = datetime.utcnow().isoformat()
            cur.execute("""
                INSERT INTO profiles (
                    name, created_at, min_entry_cents, max_entry_cents, proactive_mode,
                    max_open_orders, max_daily_spend_cents, scan_interval_seconds,
                    btc_series_tickers
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
            """, ("Default", now, config.MIN_ENTRY_CENTS, config.MAX_ENTRY_CENTS, config.PROACTIVE_MODE,
                   config.MAX_OPEN_ORDERS, config.MAX_DAILY_SPEND_CENTS, 
                   config.SCAN_INTERVAL_SECONDS, ",".join(config.BTC_SERIES_TICKERS)))
            default_profile_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO settings (
                    id, min_entry_cents, max_entry_cents, proactive_mode, 
                    max_open_orders, max_daily_spend_cents, scan_interval_seconds, 
                    btc_series_tickers, active_profile_id
                ) VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                config.MIN_ENTRY_CENTS, config.MAX_ENTRY_CENTS, config.PROACTIVE_MODE,
                config.MAX_OPEN_ORDERS, config.MAX_DAILY_SPEND_CENTS, 
                config.SCAN_INTERVAL_SECONDS, ",".join(config.BTC_SERIES_TICKERS),
                default_profile_id
            ))
            
            # Link existing orders if any
            cur.execute("UPDATE orders SET profile_id = %s WHERE profile_id IS NULL", (default_profile_id,))
        else:
            # Migration: Ensure at least one profile exists and is linked if active_profile_id is NULL
            cur.execute("SELECT active_profile_id FROM settings WHERE id = 1")
            row = cur.fetchone()
            if row and row[0] is None:
                # Check if any profile exists
                cur.execute("SELECT id FROM profiles LIMIT 1")
                profile_row = cur.fetchone()
                if not profile_row:
                    now = datetime.utcnow().isoformat()
                    cur.execute("SELECT min_entry_cents, max_entry_cents, proactive_mode, max_open_orders, max_daily_spend_cents, scan_interval_seconds, btc_series_tickers FROM settings WHERE id = 1")
                    s = cur.fetchone()
                    cur.execute("""
                        INSERT INTO profiles (
                            name, created_at, min_entry_cents, max_entry_cents, proactive_mode,
                            max_open_orders, max_daily_spend_cents, scan_interval_seconds,
                            btc_series_tickers
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                    """, ("Default", now, s[0], s[1], s[2], s[3], s[4], s[5], s[6]))
                    pid = cur.fetchone()[0]
                else:
                    pid = profile_row[0]
                
                cur.execute("UPDATE settings SET active_profile_id = %s WHERE id = 1", (pid,))
                cur.execute("UPDATE orders SET profile_id = %s WHERE profile_id IS NULL", (pid,))
        
        conn.commit()
    log.info("Database ready: %s (postgres)", config.DB_URL)

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
        
    query = """
        INSERT INTO profiles (
            name, created_at, min_entry_cents, max_entry_cents, proactive_mode,
            max_open_orders, max_daily_spend_cents, scan_interval_seconds,
            btc_series_tickers
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    """
    params = (
        name, datetime.utcnow().isoformat(),
        settings_dict['min_entry_cents'], settings_dict['max_entry_cents'],
        settings_dict['proactive_mode'], settings_dict['max_open_orders'],
        settings_dict['max_daily_spend_cents'], settings_dict['scan_interval_seconds'],
        btc_tickers
    )
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        profile_id = cur.fetchone()[0]
        conn.commit()
    return profile_id

def save_order(client_order_id: str, market_ticker: str, side: str,
               entry_price_cents: int, kalshi_order_id: str = None,
               btc_price: float = None, distance_to_strike: float = None,
               market_close_time: str = None, time_to_close_seconds: int = None,
               profile_id: int = None):
    now = datetime.utcnow().isoformat()
    query = """
        INSERT OR IGNORE INTO orders
          (client_order_id, kalshi_order_id, market_ticker, side,
           entry_price_cents, placed_at, btc_price_at_placement,
           distance_to_strike_at_placement, market_close_time,
           time_to_close_at_placement, profile_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (client_order_id, kalshi_order_id, market_ticker, side,
              entry_price_cents, now, btc_price, distance_to_strike,
              market_close_time, time_to_close_seconds, profile_id)
    
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

def has_open_order(market_ticker: str, side: str) -> bool:
    query = "SELECT 1 FROM orders WHERE market_ticker = %s AND side = %s AND status IN ('resting', 'pending', 'filled')"
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, (market_ticker, side))
        row = cur.fetchone()
    return row is not None

def get_today_spend_cents() -> int:
    today = date.today().isoformat()
    query = """
        SELECT COALESCE(SUM(entry_price_cents * count), 0)
        FROM orders
        WHERE status IN ('resting', 'filled') AND placed_at::date = %s
    """
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, (today,))
        row = cur.fetchone()
    return row[0] if row else 0

def count_resting_orders() -> int:
    query = "SELECT COUNT(*) FROM orders WHERE status = 'resting'"
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query)
        row = cur.fetchone()
    return row[0] if row else 0

def get_resting_orders() -> list[dict]:
    query = "SELECT kalshi_order_id, market_ticker, side, entry_price_cents FROM orders WHERE status = 'resting'"
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        rows = cur.fetchall()
    return [dict(r) for r in rows]

def get_filled_without_outcome() -> list[dict]:
    query = """
        SELECT kalshi_order_id, market_ticker, side, entry_price_cents,
               market_close_time
        FROM orders
        WHERE status = 'filled' AND outcome IS NULL
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        rows = cur.fetchall()
    return [dict(r) for r in rows]

def save_market_snapshot(ticker: str, title: str, close_time: str,
                         yes_ask: int, yes_bid: int, no_ask: int, no_bid: int,
                         btc_price: float, time_to_close_secs: int,
                         strike_str: str = None, volume: int = None,
                         open_interest: int = None):
    now = datetime.utcnow().isoformat()
    query = """
        INSERT INTO market_snapshots
          (ticker, title, scanned_at, close_time, yes_ask, yes_bid,
           no_ask, no_bid, btc_price, time_to_close_secs, strike_str,
           volume, open_interest)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (ticker, title, now, close_time, yes_ask, yes_bid, no_ask, no_bid,
              btc_price, time_to_close_secs, strike_str, volume, open_interest)
    
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        conn.commit()

def log_btc_price(price: float):
    now = datetime.utcnow().isoformat()
    query = "INSERT INTO btc_prices (recorded_at, price) VALUES (%s, %s)"
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, (now, price))
        conn.commit()

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
        'max_open_orders', 'max_daily_spend_cents', 'scan_interval_seconds',
        'btc_series_tickers', 'active_profile_id'
    ]
    to_update = {k: v for k, v in settings.items() if k in allowed_keys}
    if not to_update:
        return

    critical_changed = False
    critical_keys = [
        'min_entry_cents', 'max_entry_cents', 'proactive_mode', 
        'max_open_orders', 'max_daily_spend_cents', 'scan_interval_seconds',
        'btc_series_tickers'
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
