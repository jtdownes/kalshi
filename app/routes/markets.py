"""
Markets routes: snapshots, scanned-series management, weather.
"""

import time
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

import database
from database.core import cursor_conn
from crypto_assets import CRYPTO_ASSETS, DEFAULT_ASSET
from kalshi_client import KalshiClient

markets_bp = Blueprint('markets', __name__)


def _parse_close_ts(ct: str | None) -> int | None:
    if not ct:
        return None
    try:
        return int(datetime.fromisoformat(ct.replace("Z", "+00:00")).timestamp())
    except (ValueError, TypeError):
        return None


@markets_bp.get("/api/weather")
def weather_list():
    limit = min(int(request.args.get("limit", 100)), 500)
    return jsonify(database.get_recent_weather_snapshots(limit))


@markets_bp.get("/api/scanned-series")
def scanned_series_list():
    return jsonify(database.get_scanned_series())


@markets_bp.post("/api/scanned-series")
def scanned_series_add():
    body   = request.get_json(silent=True) or {}
    series = (body.get("series_ticker") or "").strip().upper()
    if not series or not series.replace("_", "").isalnum():
        return jsonify({"error": "invalid series ticker"}), 400

    try:
        data = KalshiClient().get_markets(series_ticker=series, status="open", limit=200)
    except Exception as e:
        return jsonify({"error": f"could not reach Kalshi: {e}"}), 502
    markets = data.get("markets", []) or []
    if not markets:
        return jsonify({"error": f"no open markets found for series '{series}'"}), 404

    now_ts  = int(time.time())
    closes  = [c for c in (_parse_close_ts(m.get("close_time") or m.get("expiration_time")) for m in markets) if c]
    farthest = max(closes) if closes else now_ts + 1200
    suggested = min(max(farthest - now_ts + 3600, 600), 7 * 86400)

    try:
        look_ahead = int(body.get("look_ahead_seconds") or suggested)
        interval   = max(1, int(body.get("interval_seconds") or 1))
    except (TypeError, ValueError):
        return jsonify({"error": "look_ahead_seconds / interval_seconds must be integers"}), 400
    label = (body.get("label") or markets[0].get("title") or series)[:120]

    row = database.add_scanned_series(series, label, look_ahead, interval)
    row["market_count"] = len(markets)
    row["sample_title"] = markets[0].get("title", "")
    return jsonify(row), 201


@markets_bp.patch("/api/scanned-series/<series>")
def scanned_series_toggle(series):
    body    = request.get_json(silent=True) or {}
    enabled = bool(body.get("enabled", True))
    if not database.set_scanned_series_enabled(series.upper(), enabled):
        return jsonify({"error": "series not found"}), 404
    return jsonify({"series_ticker": series.upper(), "enabled": enabled})


@markets_bp.delete("/api/scanned-series/<series>")
def scanned_series_delete(series):
    if not database.remove_scanned_series(series.upper()):
        return jsonify({"error": "series not found"}), 404
    return jsonify({"ok": True})


@markets_bp.get("/api/snapshots")
def snapshots():
    limit_param = request.args.get("limit")
    limit  = int(limit_param) if limit_param else None
    ticker = (request.args.get("ticker") or "").strip().upper()
    if ticker:
        return jsonify(database.get_market_snapshots_for_ticker(ticker, limit))
    return jsonify(database.get_recent_market_snapshots(limit))


@markets_bp.get("/api/snapshots/tickers")
def snapshot_tickers():
    """One summary row per distinct ticker, ordered by most recent scan.

    `result` is the market's yes/no outcome: the official settlement when it's
    been backfilled, otherwise derived from the final quote once the market has
    closed (last bid/ask >= 50 ⇒ yes), the same way the backtester settles.
    It's null only while a market is still open. The settlements table covers a
    historical window, so most recent markets rely on the derived value."""
    with cursor_conn() as c:
        c.execute("""
            SELECT latest.ticker, latest.title, latest.strike_str,
                   latest.yes_ask, latest.yes_bid, latest.no_ask,
                   latest.volume, latest.open_interest, latest.time_to_close_secs,
                   latest.scanned_at,
                   COALESCE(
                       s.result,
                       CASE
                           WHEN latest.close_time ~ '^[0-9]+$'
                                AND latest.close_time::bigint < EXTRACT(EPOCH FROM now())
                           THEN CASE WHEN COALESCE(latest.yes_bid, latest.yes_ask) >= 50
                                     THEN 'yes' ELSE 'no' END
                       END
                   ) AS result
            FROM (
                SELECT DISTINCT ON (ticker)
                       ticker, title, strike_str,
                       yes_ask, yes_bid, no_ask,
                       volume, open_interest, time_to_close_secs,
                       scanned_at, close_time
                FROM market_snapshots
                ORDER BY ticker, id DESC
            ) latest
            LEFT JOIN market_settlements s ON s.ticker = latest.ticker
            ORDER BY latest.scanned_at DESC
        """)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@markets_bp.get("/api/snapshots/series")
def snapshot_series():
    ticker = request.args.get("ticker", "").strip().upper()
    try:
        limit = min(int(request.args.get("limit", 1000)), 1000)
    except ValueError:
        limit = 1000

    if not ticker:
        return jsonify({"error": "ticker required"}), 400

    with cursor_conn() as c:
        c.execute("""
            SELECT m.scanned_at, m.yes_bid, m.no_bid, m.time_to_close_secs,
                   COALESCE(b.consolidated_price, b.coinbase_price) AS btc_price,
                   b.consolidated_price AS brti_price,
                   b.coinbase_price, b.kraken_price, b.bitstamp_price, b.gemini_price, m.strike_str,
                   COALESCE(e.consolidated_price, e.coinbase_price) AS eth_price,
                   e.coinbase_price AS eth_coinbase_price,
                   e.kraken_price   AS eth_kraken_price,
                   e.bitstamp_price AS eth_bitstamp_price,
                   e.gemini_price   AS eth_gemini_price,
                   COALESCE(s.consolidated_price, s.coinbase_price) AS sol_price,
                   s.coinbase_price AS sol_coinbase_price,
                   s.kraken_price   AS sol_kraken_price,
                   s.bitstamp_price AS sol_bitstamp_price,
                   s.gemini_price   AS sol_gemini_price
            FROM market_snapshots m
            LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
            LEFT JOIN ethereum_snapshots e ON e.scanned_at = m.scanned_at
            LEFT JOIN solana_snapshots s ON s.scanned_at = m.scanned_at
            WHERE m.ticker = %s
            ORDER BY m.id DESC
            LIMIT %s
        """, (ticker, limit))
        rows = c.fetchall()

    return jsonify([dict(r) for r in reversed(rows)])


@markets_bp.get("/api/crypto/ohlc")
def crypto_ohlc():
    """Broad-scale OHLC candles for a crypto asset, aggregated straight from
    the 1-second snapshot table (not tied to any single market's life).

    Query params:
      asset    — BTC / ETH (default BTC)
      interval — candle width in seconds (default 60)
      lookback — how far back to look, in seconds (default 14400 = 4h)
    """
    asset = request.args.get("asset", DEFAULT_ASSET).strip().upper()
    cfg = CRYPTO_ASSETS.get(asset)
    if not cfg:
        return jsonify({"error": f"unknown asset '{asset}'"}), 400

    try:
        interval = max(1, min(int(request.args.get("interval", 60)), 3600))
    except ValueError:
        interval = 60
    try:
        lookback = max(60, min(int(request.args.get("lookback", 14400)), 7 * 86400))
    except ValueError:
        lookback = 14400

    table = cfg["snapshot_table"]  # registry-controlled, not user input
    cutoff = (datetime.utcnow() - timedelta(seconds=lookback)).isoformat()

    # scanned_at is a UTC ISO string (no tz); cast as plain timestamp so epoch
    # bucketing is consistent. ISO strings sort lexically, so the >= cutoff
    # filter rides the scanned_at index.
    with cursor_conn() as c:
        c.execute(f"""
            WITH pts AS (
                SELECT consolidated_price AS price,
                       extract(epoch FROM scanned_at::timestamp) AS ts
                FROM {table}
                WHERE scanned_at >= %s AND consolidated_price IS NOT NULL
            )
            SELECT (floor(ts / %s) * %s)::bigint           AS bucket,
                   (array_agg(price ORDER BY ts ASC))[1]   AS open,
                   max(price)                              AS high,
                   min(price)                              AS low,
                   (array_agg(price ORDER BY ts DESC))[1]  AS close,
                   count(*)                                AS n
            FROM pts
            GROUP BY bucket
            ORDER BY bucket
        """, (cutoff, interval, interval))
        rows = c.fetchall()

    return jsonify([
        {
            "bucket": int(r["bucket"]),
            "open": r["open"],
            "high": r["high"],
            "low": r["low"],
            "close": r["close"],
            "n": int(r["n"]),
        }
        for r in rows
    ])
