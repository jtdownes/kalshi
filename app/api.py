"""
Kalshi Dashboard API — reads SQLite, serves JSON for the React frontend.
Runs as a separate service sharing the same /data volume as the bot.
"""

from flask import Flask, jsonify, request
import sqlite3
from datetime import date

import config

app = Flask(__name__)


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/stats")
def stats():
    today = date.today().isoformat()
    with _conn() as c:
        today_spend = c.execute("""
            SELECT COALESCE(SUM(entry_price_cents * count), 0)
            FROM orders
            WHERE status IN ('resting','filled') AND DATE(placed_at) = ?
        """, (today,)).fetchone()[0]

        resting  = c.execute("SELECT COUNT(*) FROM orders WHERE status='resting'").fetchone()[0]
        filled   = c.execute("SELECT COUNT(*) FROM orders WHERE status='filled'").fetchone()[0]
        canceled = c.execute("SELECT COUNT(*) FROM orders WHERE status='canceled'").fetchone()[0]
        wins     = c.execute("SELECT COUNT(*) FROM orders WHERE outcome='win'").fetchone()[0]
        losses   = c.execute("SELECT COUNT(*) FROM orders WHERE outcome='loss'").fetchone()[0]

        total_pnl = c.execute(
            "SELECT COALESCE(SUM(net_profit_cents), 0) FROM orders WHERE net_profit_cents IS NOT NULL"
        ).fetchone()[0]

        total      = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        snap_count = c.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0]

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
            rows = c.execute("""
                SELECT id, kalshi_order_id, market_ticker, side,
                       entry_price_cents, count, status, placed_at,
                       filled_at, market_close_time,
                       time_to_close_at_placement,
                       outcome, payout_cents, net_profit_cents
                FROM orders ORDER BY id DESC LIMIT ?
            """, (limit,)).fetchall()
        else:
            rows = c.execute("""
                SELECT id, kalshi_order_id, market_ticker, side,
                       entry_price_cents, count, status, placed_at,
                       filled_at, market_close_time,
                       time_to_close_at_placement,
                       outcome, payout_cents, net_profit_cents
                FROM orders WHERE status=? ORDER BY id DESC LIMIT ?
            """, (status, limit)).fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/snapshots")
def snapshots():
    limit = min(int(request.args.get("limit", 100)), 500)
    with _conn() as c:
        rows = c.execute("""
            SELECT id, ticker, title, scanned_at, close_time,
                   yes_ask, no_ask, yes_bid, no_bid,
                   time_to_close_secs, strike_str, volume, open_interest
            FROM market_snapshots ORDER BY id DESC LIMIT ?
        """, (limit,)).fetchall()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8820, debug=False)
