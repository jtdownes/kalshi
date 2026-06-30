"""
Trading routes: balance, quotes, positions, SSE events, health, stats, orders, trades.
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

from flask import Blueprint, Response, jsonify, request, stream_with_context

import database
import ws_worker
from database.core import cursor_conn
from kalshi_client import KalshiClient

trading_bp = Blueprint('trading', __name__)


def _dollars_to_cents(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return round(float(v) * 100, 1)
    except (ValueError, TypeError):
        return None


@trading_bp.get("/api/balance")
def balance():
    try:
        data = KalshiClient().get_balance()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@trading_bp.get("/api/quotes")
def quotes():
    tickers_param = request.args.get("tickers", "")
    if not tickers_param:
        return jsonify({})
    ticker_list = [t.strip() for t in tickers_param.split(",") if t.strip()][:20]

    cached  = ws_worker.get_quotes()
    result  = {t: cached[t] for t in ticker_list if t in cached}
    missing = [t for t in ticker_list if t not in cached]

    if missing:
        try:
            client = KalshiClient()
            def fetch_one(ticker):
                try:
                    data = client.get_market(ticker)
                    m = data.get("market", {})
                    oi_raw = m.get("open_interest_fp")
                    oi = int(float(oi_raw)) if oi_raw else None
                    return ticker, {
                        "yes_ask":       _dollars_to_cents(m.get("yes_ask_dollars")),
                        "no_ask":        _dollars_to_cents(m.get("no_ask_dollars")),
                        "yes_bid":       _dollars_to_cents(m.get("yes_bid_dollars")),
                        "no_bid":        _dollars_to_cents(m.get("no_bid_dollars")),
                        "open_interest": oi,
                    }
                except Exception:
                    return ticker, None
            with ThreadPoolExecutor(max_workers=10) as pool:
                rest = dict(pool.map(fetch_one, missing))
            result.update({k: v for k, v in rest.items() if v is not None})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify(result)


@trading_bp.get("/api/positions")
def positions():
    if ws_worker.is_bootstrapped():
        return jsonify(ws_worker.get_positions())
    try:
        data = KalshiClient().get_positions()
        return jsonify(data.get("market_positions", []))
    except Exception as e:
        return jsonify({"error": str(e)}), 200


@trading_bp.get("/api/events")
def events():
    def generate():
        q = ws_worker.subscribe_events()
        try:
            init = {
                "type": "init",
                "data": {
                    "positions": ws_worker.get_positions(),
                    "quotes":    ws_worker.get_quotes(),
                    "snapshots": ws_worker.get_snapshots(),
                    "connected": ws_worker.is_connected(),
                },
            }
            yield f"data: {json.dumps(init)}\n\n"
            while True:
                try:
                    event = q.get(timeout=25)
                    yield f"data: {json.dumps(event)}\n\n"
                except Exception:
                    yield ": heartbeat\n\n"
        finally:
            ws_worker.unsubscribe_events(q)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@trading_bp.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@trading_bp.get("/api/stats")
def stats():
    today      = date.today().isoformat()
    profile_id = request.args.get("profile_id")

    where_clause = ""
    params = [today]
    if profile_id:
        where_clause = " AND profile_id = %s"
        params.append(profile_id)

    count_where  = "WHERE order_role = 'entry'"
    count_params = []
    if profile_id:
        count_where  += " AND profile_id = %s"
        count_params  = [profile_id]

    with cursor_conn() as c:
        c.execute(f"""
            SELECT COALESCE(SUM(entry_price_cents * count), 0)
            FROM orders
            WHERE order_role = 'entry' AND status IN ('resting','filled') AND DATE(placed_at) = %s {where_clause}
        """, params)
        today_spend = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM orders {count_where} AND status='resting'", count_params)
        resting = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM orders {count_where} AND status='filled'", count_params)
        filled = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM orders {count_where} AND status='canceled'", count_params)
        canceled = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM orders {count_where} AND outcome='win'", count_params)
        wins = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM orders {count_where} AND outcome='loss'", count_params)
        losses = c.fetchone()[0]

        c.execute(f"SELECT COALESCE(SUM(net_profit_cents), 0) FROM orders {count_where} AND net_profit_cents IS NOT NULL", count_params)
        total_pnl = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM orders {count_where}", count_params)
        total = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM market_snapshots")
        snap_count = c.fetchone()[0]

    win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else None
    return jsonify({
        "today_spend_cents": today_spend,
        "resting":           resting,
        "filled":            filled,
        "canceled":          canceled,
        "wins":              wins,
        "losses":            losses,
        "win_rate":          win_rate,
        "total_pnl_cents":   total_pnl,
        "total_orders":      total,
        "snap_count":        snap_count,
    })


@trading_bp.get("/api/pnl/daily")
def pnl_daily():
    """Every settled order's P&L with its settlement timestamp (UTC). The
    frontend groups rows into local-timezone days for the P&L calendar —
    grouping client-side keeps day boundaries correct for the viewer."""
    profile_id = request.args.get("profile_id")

    where_clauses = ["order_role = 'entry'", "net_profit_cents IS NOT NULL"]
    params = []
    if profile_id:
        where_clauses.append("profile_id = %s")
        params.append(profile_id)

    query = f"""
        SELECT id, market_ticker, net_profit_cents,
               COALESCE(closed_at, filled_at, placed_at) AS settled_at
        FROM orders
        WHERE {" AND ".join(where_clauses)}
        ORDER BY settled_at ASC
    """
    with cursor_conn() as c:
        c.execute(query, params)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@trading_bp.get("/api/orders")
def orders():
    limit      = min(int(request.args.get("limit", 100)), 500)
    status     = request.args.get("status", "all")
    profile_id = request.args.get("profile_id")

    where_clauses, params = [], []
    if status != "all":
        where_clauses.append("status = %s")
        params.append(status)
    if profile_id:
        where_clauses.append("profile_id = %s")
        params.append(profile_id)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    query = f"""
        SELECT id, kalshi_order_id, market_ticker, side, order_role,
               entry_price_cents, count, status, placed_at,
               filled_at, market_close_time, time_to_close_at_placement,
               outcome, payout_cents, net_profit_cents
        FROM orders {where_sql} ORDER BY id DESC LIMIT %s
    """
    params.append(limit)

    with cursor_conn() as c:
        c.execute(query, params)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@trading_bp.get("/api/market-stats")
def market_stats():
    """Per-series aggregate across ALL strategies — one row per market series.

    Runs / wins / losses are counted per distinct market_ticker (one "run" per
    market), matching the per-strategy card semantics on the Strategies page.
    Series is derived from the ticker prefix (e.g. KXBTC15M-... -> KXBTC15M)."""
    query = """
        WITH per_market AS (
            SELECT
                split_part(o.market_ticker, '-', 1)                                  AS series,
                COALESCE(SUM(o.net_profit_cents)
                         FILTER (WHERE o.net_profit_cents IS NOT NULL), 0)           AS net_profit_cents,
                COUNT(*) FILTER (WHERE o.net_profit_cents IS NOT NULL)               AS resolved_orders
            FROM orders o
            WHERE o.order_role = 'entry'
            GROUP BY o.market_ticker
        )
        SELECT
            series,
            COUNT(*)                                                  AS run_count,
            COUNT(*) FILTER (WHERE resolved_orders > 0
                                   AND net_profit_cents > 0)          AS win_count,
            COUNT(*) FILTER (WHERE resolved_orders > 0
                                   AND net_profit_cents <= 0)         AS loss_count,
            COALESCE(SUM(net_profit_cents), 0)                        AS total_profit_cents
        FROM per_market
        GROUP BY series
        ORDER BY series
    """
    with cursor_conn() as c:
        c.execute(query)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@trading_bp.get("/api/trades")
def trades():
    """Orders grouped by market ticker — one row per market."""
    limit      = min(int(request.args.get("limit", 200)), 500)
    profile_id = request.args.get("profile_id")

    where_clauses = ["order_role = 'entry'"]
    params = []
    if profile_id:
        where_clauses.append("o.profile_id = %s")
        params.append(profile_id)

    where_sql = "WHERE " + " AND ".join(where_clauses)
    query = f"""
        SELECT
            o.market_ticker,
            COUNT(*)                                                                 AS order_count,
            COUNT(*) FILTER (WHERE o.closed_at IS NOT NULL)                          AS closed_order_count,
            COALESCE(SUM(o.count) FILTER (WHERE o.status = 'filled'
                                              AND o.order_role = 'entry'), 0)        AS total_count,
            MAX(CASE WHEN o.order_role = 'entry' THEN o.side END)                    AS side,
            MIN(o.placed_at)                                                         AS placed_at,
            MIN(CASE WHEN o.status = 'filled' THEN o.filled_at END)                  AS first_entry_filled_at,
            MAX(CASE WHEN o.status = 'filled' THEN o.filled_at END)                  AS last_entry_filled_at,
            MAX(o.closed_at)                                                         AS closed_at,
            MIN(o.market_close_time)                                                  AS market_close_time,
            ROUND(AVG(CASE WHEN o.status = 'filled' THEN o.entry_price_cents END))::int
                                                                                     AS entry_price_cents,
            COALESCE(SUM(o.entry_price_cents * o.count)
                     FILTER (WHERE o.status = 'filled'), 0)                         AS total_entry_cost_cents,
            COALESCE(SUM(o.payout_cents)
                     FILTER (WHERE o.closed_at IS NOT NULL), 0)                     AS total_close_proceeds_cents,
            COALESCE(SUM(o.net_profit_cents)
                     FILTER (WHERE o.net_profit_cents IS NOT NULL), 0)              AS net_profit_cents,
            CASE
                WHEN COUNT(*) FILTER (WHERE o.status IN ('resting', 'pending')) > 0 THEN 'resting'
                WHEN COUNT(*) FILTER (WHERE o.status = 'filled' AND o.closed_at IS NULL) > 0 THEN 'filled'
                WHEN COUNT(*) FILTER (WHERE o.closed_at IS NOT NULL) > 0 THEN 'closed'
                WHEN COUNT(*) FILTER (WHERE o.status = 'canceled') = COUNT(*) THEN 'canceled'
                ELSE 'unknown'
            END AS status,
            CASE
                WHEN COALESCE(SUM(o.net_profit_cents)
                              FILTER (WHERE o.net_profit_cents IS NOT NULL), 0) > 0 THEN 'win'
                WHEN COALESCE(SUM(o.net_profit_cents)
                              FILTER (WHERE o.net_profit_cents IS NOT NULL), 0) < 0 THEN 'loss'
                ELSE NULL
            END AS outcome,
            NULL::int       AS peak_price_cents,
            NULL::timestamp AS peak_time,
            MIN(CASE WHEN o.status = 'filled' THEN o.filled_at END) AS filled_at
        FROM orders o
        {where_sql}
        GROUP BY o.market_ticker
        ORDER BY MAX(o.placed_at) DESC
        LIMIT %s
    """
    params.append(limit)

    with cursor_conn() as c:
        c.execute(query, params)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])
