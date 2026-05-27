"""
Kalshi Dashboard API — reads from Postgres, serves JSON for the React frontend.
"""

from contextlib import contextmanager
from flask import Flask, jsonify, request
import psycopg2
import psycopg2.extras
from datetime import date

import config

app = Flask(__name__)


@contextmanager
def _conn():
    conn = psycopg2.connect(config.DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            yield cur
    finally:
        conn.close()


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/stats")
def stats():
    today = date.today().isoformat()
    with _conn() as c:
        c.execute("""
            SELECT COALESCE(SUM(entry_price_cents * count), 0)
            FROM orders
            WHERE status IN ('resting','filled') AND DATE(placed_at) = %s
        """, (today,))
        today_spend = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM orders WHERE status='resting'")
        resting = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM orders WHERE status='filled'")
        filled = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM orders WHERE status='canceled'")
        canceled = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM orders WHERE outcome='win'")
        wins = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM orders WHERE outcome='loss'")
        losses = c.fetchone()[0]

        c.execute("SELECT COALESCE(SUM(net_profit_cents), 0) FROM orders WHERE net_profit_cents IS NOT NULL")
        total_pnl = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM orders")
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
    with _conn() as c:
        if status == "all":
            c.execute("""
                SELECT id, kalshi_order_id, market_ticker, side,
                       entry_price_cents, count, status, placed_at,
                       filled_at, market_close_time,
                       time_to_close_at_placement,
                       outcome, payout_cents, net_profit_cents
                FROM orders ORDER BY id DESC LIMIT %s
            """, (limit,))
        else:
            c.execute("""
                SELECT id, kalshi_order_id, market_ticker, side,
                       entry_price_cents, count, status, placed_at,
                       filled_at, market_close_time,
                       time_to_close_at_placement,
                       outcome, payout_cents, net_profit_cents
                FROM orders WHERE status=%s ORDER BY id DESC LIMIT %s
            """, (status, limit))
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8820, debug=False)
