"""
Kalshi Dashboard API — reads from Postgres, serves JSON for the React frontend.
"""

from contextlib import contextmanager
from flask import Flask, jsonify, request
import psycopg2
import psycopg2.extras
from datetime import date

import config
import database

database.init_db()

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
        c.execute("SELECT * FROM profiles ORDER BY created_at DESC")
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8820, debug=False)
