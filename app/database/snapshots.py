"""
Market and crypto (per-asset) snapshot persistence and queries.
"""

import psycopg2.extras
import logging
import time
from datetime import datetime

import crypto_assets
from .core import _conn, _lock

log = logging.getLogger(__name__)

# Resolution of a *closed* 15-min window never changes, so memoise it.
_window_res_cache: dict = {}


def save_crypto_snapshot(asset: str, scanned_at: str, coinbase_price: float = None,
                         kraken_price: float = None, bitstamp_price: float = None,
                         gemini_price: float = None, consolidated_price: float = None,
                         coinbase_volume: float = None, kraken_volume: float = None,
                         bitstamp_volume: float = None, gemini_volume: float = None):
    """One price/volume row per asset per collection pass. The table name comes
    from the crypto_assets registry (never from user input)."""
    table = crypto_assets.CRYPTO_ASSETS[asset]["snapshot_table"]
    query = f"""
        INSERT INTO {table}
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


def get_latest_snapshot_for_ticker(ticker: str) -> dict | None:
    """Most recent market_snapshots row for one ticker (freshest bid/ask)."""
    query = """
        SELECT ticker, yes_ask, yes_bid, no_ask, no_bid, scanned_at, time_to_close_secs
        FROM market_snapshots WHERE ticker = %s ORDER BY scanned_at DESC LIMIT 1
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, (ticker,))
        row = cur.fetchone()
    return dict(row) if row else None


def get_recent_market_snapshots(limit: int | None = None) -> list[dict]:
    limit_sql = f"LIMIT {int(limit)}" if limit is not None else ""
    query = f"""
        SELECT m.id, m.ticker, m.title, m.scanned_at, m.close_time,
               m.yes_ask, m.no_ask, m.yes_bid, m.no_bid,
               COALESCE(b.consolidated_price, b.coinbase_price) AS btc_price,
               b.consolidated_price AS brti_price,
               b.coinbase_price, b.kraken_price, b.bitstamp_price, b.gemini_price,
               b.coinbase_volume, b.kraken_volume, b.bitstamp_volume, b.gemini_volume,
               COALESCE(e.consolidated_price, e.coinbase_price) AS eth_price,
               m.time_to_close_secs, m.strike_str, m.volume, m.open_interest
        FROM market_snapshots m
        LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
        LEFT JOIN ethereum_snapshots e ON e.scanned_at = m.scanned_at
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
               COALESCE(e.consolidated_price, e.coinbase_price) AS eth_price,
               m.time_to_close_secs, m.strike_str, m.volume, m.open_interest
        FROM market_snapshots m
        LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
        LEFT JOIN ethereum_snapshots e ON e.scanned_at = m.scanned_at
        WHERE m.ticker = %s
        ORDER BY m.id DESC
        {limit_sql}
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, (ticker,))
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_recent_crypto_prices(asset: str, window_seconds: int = 180) -> list[float]:
    """Consolidated prices for one asset over the trailing `window_seconds`,
    oldest first. Table name comes from the crypto_assets registry."""
    table = crypto_assets.CRYPTO_ASSETS[asset]["snapshot_table"]
    query = f"""
        SELECT COALESCE(consolidated_price, coinbase_price) AS price
        FROM {table}
        WHERE scanned_at::timestamp >= ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - (%s || ' seconds')::interval)
        ORDER BY scanned_at ASC
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, (str(int(window_seconds)),))
        rows = cur.fetchall()
    return [float(r["price"]) for r in rows if r["price"] is not None]


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
               COALESCE(e.consolidated_price, e.coinbase_price) AS eth_price,
               m.time_to_close_secs, m.strike_str, m.volume, m.open_interest
        FROM market_snapshots m
        LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
        LEFT JOIN ethereum_snapshots e ON e.scanned_at = m.scanned_at
        WHERE ({where})
          AND m.scanned_at::timestamp >= ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC') - (%s || ' seconds')::interval)
        ORDER BY m.ticker, m.scanned_at DESC
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, params)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def _window_resolution(cur, series_prefix: str, window_close: str):
    """
    Resolve a single window to 1 (YES) or 0 (NO) using the final snapshot's price.
    Returns None when no snapshot exists. Only closed windows are cached.
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
    """Look up whether the previous one and two 15-min windows resolved YES or NO."""
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
