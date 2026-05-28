"""
Kalshi Dashboard API — reads from Postgres, serves JSON for the React frontend.
"""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, Response, jsonify, request, stream_with_context
import psycopg2
import psycopg2.extras
from datetime import date
import json

import config
import database
import ws_worker
from kalshi_client import KalshiClient

database.init_db()
ws_worker.start()

app = Flask(__name__)


@contextmanager
def _conn():
    conn = psycopg2.connect(config.DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            yield cur
    finally:
        conn.close()


def _dollars_to_cents(v) -> int | None:
    if v is None or v == "":
        return None
    try:
        return round(float(v) * 100)
    except (ValueError, TypeError):
        return None


@app.get("/api/quotes")
def quotes():
    tickers_param = request.args.get("tickers", "")
    if not tickers_param:
        return jsonify({})
    ticker_list = [t.strip() for t in tickers_param.split(",") if t.strip()][:20]

    cached = ws_worker.get_quotes()
    result = {t: cached[t] for t in ticker_list if t in cached}
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
                        "yes_ask":      _dollars_to_cents(m.get("yes_ask_dollars")),
                        "no_ask":       _dollars_to_cents(m.get("no_ask_dollars")),
                        "yes_bid":      _dollars_to_cents(m.get("yes_bid_dollars")),
                        "no_bid":       _dollars_to_cents(m.get("no_bid_dollars")),
                        "open_interest": oi,
                    }
                except Exception:
                    return ticker, None
            with ThreadPoolExecutor(max_workers=10) as pool:
                rest = dict(pool.map(lambda t: fetch_one(t), missing))
            result.update({k: v for k, v in rest.items() if v is not None})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    return jsonify(result)


@app.get("/api/positions")
def positions():
    if ws_worker.is_bootstrapped():
        return jsonify(ws_worker.get_positions())
    try:
        client = KalshiClient()
        data = client.get_positions()
        return jsonify(data.get("market_positions", []))
    except Exception as e:
        return jsonify({"error": str(e)}), 200


@app.get("/api/events")
def events():
    def generate():
        q = ws_worker.subscribe_events()
        try:
            # Send current state immediately so the client is never blank
            init = {
                "type": "init",
                "data": {
                    "positions":  ws_worker.get_positions(),
                    "quotes":     ws_worker.get_quotes(),
                    "connected":  ws_worker.is_connected(),
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


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/stats")
def stats():
    today = date.today().isoformat()
    profile_id = request.args.get("profile_id")
    
    where_clause = ""
    params = [today]
    if profile_id:
        where_clause = " AND profile_id = %s"
        params.append(profile_id)
        
    with _conn() as c:
        c.execute(f"""
            SELECT COALESCE(SUM(entry_price_cents * count), 0)
            FROM orders
            WHERE status IN ('resting','filled') AND DATE(placed_at) = %s {where_clause}
        """, params)
        today_spend = c.fetchone()[0]

        # Reset params for counts, keeping only profile_id if present
        count_where = ""
        count_params = []
        if profile_id:
            count_where = " WHERE profile_id = %s"
            count_params = [profile_id]

        c.execute(f"SELECT COUNT(*) FROM orders WHERE status='resting' {where_clause if profile_id else ''}", count_params)
        resting = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM orders WHERE status='filled' {where_clause if profile_id else ''}", count_params)
        filled = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM orders WHERE status='canceled' {where_clause if profile_id else ''}", count_params)
        canceled = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM orders WHERE outcome='win' {where_clause if profile_id else ''}", count_params)
        wins = c.fetchone()[0]

        c.execute(f"SELECT COUNT(*) FROM orders WHERE outcome='loss' {where_clause if profile_id else ''}", count_params)
        losses = c.fetchone()[0]

        c.execute(f"SELECT COALESCE(SUM(net_profit_cents), 0) FROM orders WHERE net_profit_cents IS NOT NULL {where_clause if profile_id else ''}", count_params)
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


@app.get("/api/orders")
def orders():
    limit  = min(int(request.args.get("limit", 100)), 500)
    status = request.args.get("status", "all")
    profile_id = request.args.get("profile_id")
    
    where_clauses = []
    params = []
    
    if status != "all":
        where_clauses.append("status = %s")
        params.append(status)
        
    if profile_id:
        where_clauses.append("profile_id = %s")
        params.append(profile_id)
        
    where_sql = ""
    if where_clauses:
        where_sql = "WHERE " + " AND ".join(where_clauses)
        
    query = f"""
        SELECT id, kalshi_order_id, market_ticker, side,
               entry_price_cents, count, status, placed_at,
               filled_at, market_close_time,
               time_to_close_at_placement,
               outcome, payout_cents, net_profit_cents
        FROM orders {where_sql} ORDER BY id DESC LIMIT %s
    """
    params.append(limit)
    
    with _conn() as c:
        c.execute(query, params)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/trades")
def trades():
    """
    Orders grouped by market ticker — one row per market showing aggregate
    lifecycle: order count, fill status, peak yes_bid after first fill, P&L.
    """
    limit = min(int(request.args.get("limit", 200)), 500)
    profile_id = request.args.get("profile_id")

    where_clauses = []
    params = []
    if profile_id:
        where_clauses.append("o.profile_id = %s")
        params.append(profile_id)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Params list is used twice: once for the inner grouped query, once for LIMIT
    query = f"""
        SELECT
            g.*,
            (
                SELECT MAX(s.yes_bid)
                FROM market_snapshots s
                WHERE s.ticker = g.market_ticker
                  AND g.filled_at IS NOT NULL
                  AND s.scanned_at >= g.filled_at
            ) AS peak_price_cents,
            (
                SELECT s.scanned_at
                FROM market_snapshots s
                WHERE s.ticker = g.market_ticker
                  AND g.filled_at IS NOT NULL
                  AND s.scanned_at >= g.filled_at
                ORDER BY s.yes_bid DESC
                LIMIT 1
            ) AS peak_time
        FROM (
            SELECT
                o.market_ticker,
                COUNT(*)                                                             AS order_count,
                MIN(o.placed_at)                                                     AS placed_at,
                MIN(CASE WHEN o.status = 'filled' THEN o.filled_at END)              AS filled_at,
                MIN(o.market_close_time)                                              AS market_close_time,
                ROUND(AVG(CASE WHEN o.status = 'filled' THEN o.entry_price_cents END))::int
                                                                                     AS entry_price_cents,
                SUM(o.net_profit_cents)                                              AS net_profit_cents,
                CASE MAX(
                    CASE o.status
                        WHEN 'filled'   THEN 3
                        WHEN 'resting'  THEN 2
                        WHEN 'pending'  THEN 2
                        WHEN 'canceled' THEN 1
                        ELSE 0
                    END
                )
                    WHEN 3 THEN 'filled'
                    WHEN 2 THEN 'resting'
                    WHEN 1 THEN 'canceled'
                    ELSE 'unknown'
                END AS status,
                CASE
                    WHEN COUNT(CASE WHEN o.outcome = 'win'  THEN 1 END) > 0 THEN 'win'
                    WHEN COUNT(CASE WHEN o.outcome = 'loss' THEN 1 END) > 0 THEN 'loss'
                    ELSE NULL
                END AS outcome
            FROM orders o
            {where_sql}
            GROUP BY o.market_ticker
            ORDER BY MAX(o.placed_at) DESC
            LIMIT %s
        ) g
    """
    params.append(limit)

    with _conn() as c:
        c.execute(query, params)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/snapshots")
def snapshots():
    limit = min(int(request.args.get("limit", 100)), 500)
    with _conn() as c:
        c.execute("""
            SELECT id, ticker, title, scanned_at, close_time,
                   yes_ask, no_ask, yes_bid, no_bid,
                   time_to_close_secs, strike_str, volume, open_interest
            FROM market_snapshots ORDER BY id DESC LIMIT %s
        """, (limit,))
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/profiles")
def get_profiles():
    with _conn() as c:
        c.execute("""
            SELECT p.*,
                   COUNT(o.id) AS order_count
            FROM profiles p
            LEFT JOIN orders o ON o.profile_id = p.id
            GROUP BY p.id
            ORDER BY p.created_at DESC
        """)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/profiles")
def create_profile():
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    profile_id = database.create_profile(data, name=data.get("name"))
    database.activate_profile(profile_id)
    return jsonify({"status": "success", "profile_id": profile_id, "active_profile_id": profile_id})


@app.put("/api/profiles/<int:profile_id>")
def update_profile(profile_id: int):
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    try:
        database.update_profile(profile_id, data)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"status": "success", "profile_id": profile_id})


@app.get("/api/settings")
def get_settings():
    return jsonify(database.get_settings())


@app.post("/api/settings")
def update_settings():
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400
    
    # Validation/Type conversion could be added here
    database.update_settings(data)
    return jsonify({"status": "success"})


@app.post("/api/profiles/<int:profile_id>/activate")
def activate_profile(profile_id: int):
    try:
        database.activate_profile(profile_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"status": "success", "active_profile_id": profile_id})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8820, debug=False)
