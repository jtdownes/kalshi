"""
PostgreSQL and SQLite persistence for the Kalshi bot.
"""

import sqlite3
import psycopg2
import psycopg2.extras
import threading
import logging
from datetime import datetime, date
from pathlib import Path

import config

log = logging.getLogger(__name__)
_lock = threading.Lock()

def _conn():
    if config.DB_TYPE == "postgres":
        conn = psycopg2.connect(config.DB_URL)
        return conn
    else:
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

def _execute(conn, query, params=None):
    if config.DB_TYPE == "postgres":
        # Convert ? to %s for psycopg2
        query = query.replace("?", "%s")
        # Handle INSERT OR IGNORE and AUTOINCREMENT differences if needed
        # But for simple cases we just run it.
        # SQLite's INSERT OR IGNORE -> Postgres INSERT ... ON CONFLICT DO NOTHING
        if "INSERT OR IGNORE" in query.upper():
            query = query.upper().replace("INSERT OR IGNORE INTO", "INSERT INTO")
            if "ORDERS" in query:
                query += " ON CONFLICT (client_order_id) DO NOTHING"
        
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, params)
        return cur
    else:
        return conn.execute(query, params or [])

def init_db():
    if config.DB_TYPE == "sqlite":
        Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    
    with _lock, _conn() as conn:
        if config.DB_TYPE == "postgres":
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
            conn.commit()
        else:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS orders (
                    id                              INTEGER PRIMARY KEY AUTOINCREMENT,
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
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
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
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    recorded_at TEXT NOT NULL,
                    price       REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_orders_ticker  ON orders(market_ticker);
                CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(status);
                CREATE INDEX IF NOT EXISTS idx_snaps_ticker   ON market_snapshots(ticker);
                CREATE INDEX IF NOT EXISTS idx_btc_time       ON btc_prices(recorded_at);
            """)
    log.info("Database ready: %s (%s)", config.DB_URL if config.DB_TYPE == "postgres" else config.DB_PATH, config.DB_TYPE)

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
        if config.DB_TYPE == "postgres":
            conn.commit()

def update_order(kalshi_order_id: str, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [kalshi_order_id]
    query = f"UPDATE orders SET {sets} WHERE kalshi_order_id = ?"
    
    with _lock, _conn() as conn:
        _execute(conn, query, vals)
        if config.DB_TYPE == "postgres":
            conn.commit()

def has_open_order(market_ticker: str, side: str) -> bool:
    query = "SELECT 1 FROM orders WHERE market_ticker = ? AND side = ? AND status IN ('resting', 'pending', 'filled')"
    with _lock, _conn() as conn:
        cur = _execute(conn, query, (market_ticker, side))
        row = cur.fetchone()
    return row is not None

def get_today_spend_cents() -> int:
    today = date.today().isoformat()
    query = """
        SELECT COALESCE(SUM(entry_price_cents * count), 0)
        FROM orders
        WHERE status IN ('resting', 'filled') AND DATE(placed_at) = ?
    """
    if config.DB_TYPE == "postgres":
        query = query.replace("DATE(placed_at)", "placed_at::date")

    with _lock, _conn() as conn:
        cur = _execute(conn, query, (today,))
        row = cur.fetchone()
    return row[0] if row else 0

def count_resting_orders() -> int:
    query = "SELECT COUNT(*) FROM orders WHERE status = 'resting'"
    with _lock, _conn() as conn:
        cur = _execute(conn, query)
        row = cur.fetchone()
    return row[0] if row else 0

def get_resting_orders() -> list[dict]:
    query = "SELECT kalshi_order_id, market_ticker, side, entry_price_cents FROM orders WHERE status = 'resting'"
    with _lock, _conn() as conn:
        cur = _execute(conn, query)
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
        cur = _execute(conn, query)
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
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (ticker, title, now, close_time, yes_ask, yes_bid, no_ask, no_bid,
              btc_price, time_to_close_secs, strike_str, volume, open_interest)
    
    with _lock, _conn() as conn:
        _execute(conn, query, params)
        if config.DB_TYPE == "postgres":
            conn.commit()

def log_btc_price(price: float):
    now = datetime.utcnow().isoformat()
    query = "INSERT INTO btc_prices (recorded_at, price) VALUES (?, ?)"
    with _lock, _conn() as conn:
        _execute(conn, query, (now, price))
        if config.DB_TYPE == "postgres":
            conn.commit()
