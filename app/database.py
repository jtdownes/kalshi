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
                notes                           TEXT
            );

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

            CREATE INDEX IF NOT EXISTS idx_orders_ticker  ON orders(market_ticker);
            CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(status);
            CREATE INDEX IF NOT EXISTS idx_snaps_ticker   ON market_snapshots(ticker);
            CREATE INDEX IF NOT EXISTS idx_btc_time       ON btc_prices(recorded_at);
        """)
        
        # Sync sequences in case rows were manually inserted
        cur.execute("SELECT setval(pg_get_serial_sequence('orders', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM orders")
        cur.execute("SELECT setval(pg_get_serial_sequence('market_snapshots', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM market_snapshots")
        cur.execute("SELECT setval(pg_get_serial_sequence('btc_prices', 'id'), coalesce(max(id), 1), max(id) IS NOT null) FROM btc_prices")
        
        conn.commit()
    log.info("Database ready: %s (postgres)", config.DB_URL)

def save_order(client_order_id: str, market_ticker: str, side: str,
               entry_price_cents: int, kalshi_order_id: str = None,
               btc_price: float = None, distance_to_strike: float = None,
               market_close_time: str = None, time_to_close_seconds: int = None):
    now = datetime.utcnow().isoformat()
    query = """
        INSERT OR IGNORE INTO orders
          (client_order_id, kalshi_order_id, market_ticker, side,
           entry_price_cents, placed_at, btc_price_at_placement,
           distance_to_strike_at_placement, market_close_time,
           time_to_close_at_placement)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (client_order_id, kalshi_order_id, market_ticker, side,
              entry_price_cents, now, btc_price, distance_to_strike,
              market_close_time, time_to_close_seconds)
    
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
