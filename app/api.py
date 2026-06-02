"""
Kalshi Dashboard API — reads from Postgres, serves JSON for the React frontend.
"""

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, Response, jsonify, request, session, stream_with_context
import psycopg2
import psycopg2.extras
import bcrypt
from datetime import date
import json
import time
from collections import defaultdict
from threading import Lock
from werkzeug.middleware.proxy_fix import ProxyFix

import config
import database
import ws_worker
from kalshi_client import KalshiClient

database.init_db()
ws_worker.start()

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
app.config['SESSION_COOKIE_DOMAIN']    = '.jtdownes.com'
app.config['SESSION_COOKIE_SAMESITE']  = 'Lax'
app.config['SESSION_COOKIE_SECURE']    = True
app.config['SESSION_COOKIE_HTTPONLY']  = True
app.config['PERMANENT_SESSION_LIFETIME'] = 43200  # 12 hours
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)

# ── Brute-force rate limiter ──────────────────────────────────────────────────
# Tracks failed attempts per IP. After _MAX_ATTEMPTS failures within _WINDOW
# seconds, the IP is locked out for _LOCKOUT seconds.
_MAX_ATTEMPTS = 10
_WINDOW       = 300   # 5 minutes
_LOCKOUT      = 900   # 15 minutes
_attempts: dict[str, list[float]] = defaultdict(list)
_attempts_lock = Lock()

_DUMMY_HASH = bcrypt.hashpw(b'dummy', bcrypt.gensalt())

def _get_client_ip() -> str:
    return request.headers.get('X-Forwarded-For', request.remote_addr or '').split(',')[0].strip()

def _check_rate_limit(ip: str) -> bool:
    """Return True if the IP is currently locked out."""
    now = time.time()
    with _attempts_lock:
        _attempts[ip] = [t for t in _attempts[ip] if now - t < _WINDOW]
        return len(_attempts[ip]) >= _MAX_ATTEMPTS

def _record_failure(ip: str):
    now = time.time()
    with _attempts_lock:
        _attempts[ip].append(now)

def _clear_attempts(ip: str):
    with _attempts_lock:
        _attempts.pop(ip, None)

# ── Auth helpers ──────────────────────────────────────────────────────────────

@contextmanager
def _users_conn():
    conn = psycopg2.connect(config.USERS_DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            yield cur
    finally:
        conn.close()

@contextmanager
def _conn():
    conn = psycopg2.connect(config.DB_URL)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            yield cur
    finally:
        conn.close()

def _get_user_key_by_email(email: str):
    with _users_conn() as cur:
        cur.execute("SELECT user_key FROM users.profiles WHERE email = %s", (email,))
        row = cur.fetchone()
        return row['user_key'] if row else None

def _get_user_key_by_username(username: str):
    with _users_conn() as cur:
        cur.execute("SELECT user_key FROM users.profiles WHERE username = %s LIMIT 1", (username,))
        row = cur.fetchone()
        return row['user_key'] if row else None

def _get_password_hash(user_key) -> str | None:
    with _users_conn() as cur:
        cur.execute(
            "SELECT password_hash FROM users.credentials WHERE user_key = %s AND is_active = TRUE LIMIT 1",
            (user_key,)
        )
        row = cur.fetchone()
        return row['password_hash'] if row else None

def _get_login_info(user_key):
    with _users_conn() as cur:
        cur.execute(
            """SELECT p.user_key, p.username, p.email, p.first_name, p.last_name
               FROM users.profiles p
               JOIN users.credentials c ON p.user_key = c.user_key
               WHERE p.user_key = %s AND c.is_active = TRUE""",
            (user_key,)
        )
        return cur.fetchone()

# ── Auth guard ────────────────────────────────────────────────────────────────

@app.before_request
def require_login():
    if request.path.startswith('/api/auth'):
        return None
    if not session.get('username'):
        return jsonify({'error': 'unauthenticated'}), 401

# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.post('/api/auth/login')
def auth_login():
    ip = _get_client_ip()

    if _check_rate_limit(ip):
        # Still run a dummy bcrypt check so timing is indistinguishable from a real attempt
        bcrypt.checkpw(b'x', _DUMMY_HASH)
        return jsonify({'status': 'error', 'message': 'Too many attempts. Try again in 15 minutes.'}), 429

    data = request.get_json() or {}
    email    = data.get('email')
    username = data.get('username')
    password = data.get('password', '')

    if not password or (not email and not username):
        return jsonify({'status': 'error', 'message': 'Username or email and password required.'}), 400

    if email:
        user_key = _get_user_key_by_email(email)
        not_found_status = 'incorrect_email'
    else:
        user_key = _get_user_key_by_username(username)
        not_found_status = 'incorrect_username'

    if not user_key:
        # Run dummy bcrypt so missing-user responses take the same time as wrong-password
        bcrypt.checkpw(password.encode(), _DUMMY_HASH)
        _record_failure(ip)
        return jsonify({'status': not_found_status, 'message': 'Invalid credentials.'}), 401

    pw_hash = _get_password_hash(user_key)
    if not pw_hash or not bcrypt.checkpw(password.encode(), pw_hash.encode()):
        _record_failure(ip)
        return jsonify({'status': 'incorrect_password', 'message': 'Invalid credentials.'}), 401

    user = _get_login_info(user_key)
    if not user:
        return jsonify({'status': 'error', 'message': 'Login error.'}), 500

    _clear_attempts(ip)
    session.permanent = True
    session['username'] = user['username']
    session['user_key'] = user['user_key']
    return jsonify({'status': 'success', 'username': user['username']}), 200

@app.get('/api/auth/logout')
def auth_logout():
    session.clear()
    return jsonify({'status': 'success'}), 200

@app.get('/api/auth/status')
def auth_status():
    if session.get('username'):
        return jsonify({'logged_in': True, 'username': session['username']})
    return jsonify({'logged_in': False})


def _dollars_to_cents(v) -> float | None:
    if v is None or v == "":
        return None
    try:
        return round(float(v) * 100, 1)
    except (ValueError, TypeError):
        return None


@app.get("/api/balance")
def balance():
    try:
        data = KalshiClient().get_balance()
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/backtest")
def backtest():
    try:
        detail      = request.args.get("detail") == "true"
        limit_price = request.args.get("limit_price")
        min_limit   = max(1, min(99, int(request.args.get("min_limit", 1))))
        max_limit   = max(min_limit, min(99, int(request.args.get("max_limit", 50))))
    except ValueError:
        return jsonify({"error": "invalid params"}), 400

    if limit_price and detail:
        lp = max(1, min(99, int(limit_price)))
        with _conn() as c:
            c.execute("""
                WITH fills AS (
                    SELECT DISTINCT ON (ticker)
                        ticker,
                        scanned_at         AS fill_time,
                        yes_ask            AS fill_price,
                        time_to_close_secs AS ttc_at_fill
                    FROM market_snapshots
                    WHERE yes_ask <= %s AND yes_ask > 0
                    ORDER BY ticker, scanned_at
                ),
                peaks AS (
                    SELECT
                        f.ticker,
                        f.fill_price,
                        f.ttc_at_fill,
                        MAX(s.yes_ask) AS peak_ask,
                        COUNT(s.id)    AS post_snaps
                    FROM fills f
                    JOIN market_snapshots s
                      ON s.ticker = f.ticker AND s.scanned_at > f.fill_time
                    WHERE s.yes_ask IS NOT NULL AND s.yes_ask > 0
                    GROUP BY f.ticker, f.fill_price, f.ttc_at_fill
                )
                SELECT
                    ticker,
                    ROUND(fill_price::numeric, 1)                                AS fill_price,
                    ttc_at_fill,
                    ROUND(peak_ask::numeric, 1)                                  AS peak_ask,
                    ROUND((peak_ask - fill_price)::numeric, 1)                   AS gain,
                    post_snaps,
                    CASE
                        WHEN peak_ask >= fill_price + 50 THEN 'gain_50'
                        WHEN peak_ask >= fill_price + 25 THEN 'gain_25'
                        WHEN peak_ask >= fill_price + 10 THEN 'gain_10'
                        WHEN peak_ask >= fill_price +  5 THEN 'gain_5'
                        WHEN peak_ask > fill_price       THEN 'profit'
                        ELSE 'loss'
                    END AS outcome
                FROM peaks
                ORDER BY gain DESC NULLS LAST
            """, (lp,))
            rows = c.fetchall()
        return jsonify([dict(r) for r in rows])

    # Sweep mode — compare limit prices across the full range
    with _conn() as c:
        c.execute("""
            WITH fills AS (
                SELECT DISTINCT ON (p.limit_price, s.ticker)
                    p.limit_price,
                    s.ticker,
                    s.scanned_at AS fill_time,
                    s.yes_ask    AS fill_price
                FROM (SELECT generate_series(%s::int, %s::int) AS limit_price) p
                CROSS JOIN market_snapshots s
                WHERE s.yes_ask <= p.limit_price AND s.yes_ask > 0
                ORDER BY p.limit_price, s.ticker, s.scanned_at
            ),
            peaks AS (
                SELECT
                    f.limit_price,
                    f.ticker,
                    f.fill_price,
                    MAX(s.yes_ask) AS peak_ask
                FROM fills f
                JOIN market_snapshots s
                  ON s.ticker = f.ticker AND s.scanned_at > f.fill_time
                WHERE s.yes_ask IS NOT NULL AND s.yes_ask > 0
                GROUP BY f.limit_price, f.ticker, f.fill_price
            )
            SELECT
                limit_price,
                COUNT(*)                                                                              AS fill_count,
                ROUND(AVG(fill_price)::numeric, 1)                                                   AS avg_fill_price,
                ROUND(AVG(peak_ask - fill_price)::numeric, 1)                                        AS avg_gain,
                ROUND(AVG(CASE WHEN peak_ask > fill_price THEN 1.0 ELSE 0 END) * 100, 1)             AS pct_goes_up,
                ROUND(AVG(CASE WHEN peak_ask > fill_price THEN peak_ask END)::numeric, 1)             AS avg_peak_wins,
                ROUND(AVG(peak_ask)::numeric, 1)                                                      AS avg_peak_all,
                ROUND(MAX(peak_ask)::numeric, 1)                                                      AS max_peak,
                ROUND(AVG(CASE WHEN peak_ask >= fill_price +  5 THEN 1.0 ELSE 0 END) * 100, 1)       AS pct_gain_5,
                ROUND(AVG(CASE WHEN peak_ask >= fill_price + 10 THEN 1.0 ELSE 0 END) * 100, 1)       AS pct_gain_10,
                ROUND(AVG(CASE WHEN peak_ask >= fill_price + 25 THEN 1.0 ELSE 0 END) * 100, 1)       AS pct_gain_25,
                ROUND(AVG(CASE WHEN peak_ask >= fill_price + 50 THEN 1.0 ELSE 0 END) * 100, 1)       AS pct_gain_50
            FROM peaks
            GROUP BY limit_price
            ORDER BY limit_price
        """, (min_limit, max_limit))
        rows = c.fetchall()
    return jsonify([{
        "limit_price":    int(r["limit_price"]),
        "fill_count":     int(r["fill_count"]),
        "avg_fill_price": float(r["avg_fill_price"]) if r["avg_fill_price"] is not None else None,
        "avg_gain":       float(r["avg_gain"])       if r["avg_gain"]       is not None else None,
        "pct_goes_up":    float(r["pct_goes_up"])    if r["pct_goes_up"]    is not None else None,
        "avg_peak_wins":  float(r["avg_peak_wins"])  if r["avg_peak_wins"]  is not None else None,
        "avg_peak_all":   float(r["avg_peak_all"])   if r["avg_peak_all"]   is not None else None,
        "max_peak":       float(r["max_peak"])        if r["max_peak"]       is not None else None,
        "pct_gain_5":     float(r["pct_gain_5"])     if r["pct_gain_5"]     is not None else None,
        "pct_gain_10":    float(r["pct_gain_10"])    if r["pct_gain_10"]    is not None else None,
        "pct_gain_25":    float(r["pct_gain_25"])    if r["pct_gain_25"]    is not None else None,
        "pct_gain_50":    float(r["pct_gain_50"])    if r["pct_gain_50"]    is not None else None,
    } for r in rows])


# ── Strategy backtester ───────────────────────────────────────────────────────
# Replays a rule list against historical 1-second snapshots: for each rule we
# find the first snapshot per market where its conditions pass AND the entry
# fills, then simulate the exit (limit-sell fill, or hold-to-settlement) and
# tally P&L. One entry per (market, rule, side) — matches the live bot's dedup.

_BT_COL = {
    "time_to_close":      "m.time_to_close_secs",
    "distance_to_strike": "(COALESCE(b.consolidated_price, b.coinbase_price) - NULLIF(m.strike_str, '')::numeric)",
    "yes_ask":            "m.yes_ask",
    "yes_bid":            "m.yes_bid",
    "no_ask":             "m.no_ask",
    "no_bid":             "m.no_bid",
    "btc_price":          "COALESCE(b.consolidated_price, b.coinbase_price)",
    "spread":             "(m.yes_ask - m.yes_bid)",
    "volume":             "m.volume",
    "open_interest":      "m.open_interest",
    "prior_resolution":   "pr.res",
    "prev2_resolution":   "p2r.res",
}
_BT_OP = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">=", "eq": "="}


def _bt_conditions_sql(conditions):
    """Build an extra SQL clause + params from a rule's condition list."""
    clauses, params = [], []
    for c in conditions or []:
        col = _BT_COL.get(c.get("field"))
        if not col:
            continue
        op = c.get("op")
        v  = c.get("value")
        if v is None:
            continue
        if op == "between":
            v2 = c.get("value2")
            if v2 is None:
                continue
            lo, hi = (v, v2) if float(v) <= float(v2) else (v2, v)
            clauses.append(f"{col} BETWEEN %s AND %s")
            params.extend([lo, hi])
        elif op in _BT_OP:
            clauses.append(f"{col} {_BT_OP[op]} %s")
            params.append(v)
    clause = (" AND " + " AND ".join(clauses)) if clauses else ""
    return clause, params


def _bt_simulate_rule(cur, series_like, rule, side):
    """Simulate one rule on one side. Returns a list of trade dicts, or None if
    the rule is too incomplete to simulate (missing entry/exit price)."""
    action = rule.get("action") or {}
    entry  = action.get("entry") or {}
    exit_  = action.get("exit")  or {"type": "hold"}
    try:
        qty = max(1, int(action.get("quantity", 1)))
    except (TypeError, ValueError):
        qty = 1

    ask_col = "yes_ask" if side == "yes" else "no_ask"
    bid_col = "yes_bid" if side == "yes" else "no_bid"

    cond_clause, cond_params = _bt_conditions_sql(rule.get("conditions"))

    if entry.get("type") == "ask":
        entry_clause = f"m.{ask_col} IS NOT NULL AND m.{ask_col} > 0"
        entry_params = []
    else:
        price = entry.get("price_cents")
        if price is None:
            return None
        entry_clause = f"m.{ask_col} <= %s AND m.{ask_col} > 0"
        entry_params = [price]

    is_limit_sell = exit_.get("type") == "limit_sell"
    sell_price = exit_.get("price_cents") if is_limit_sell else None
    if is_limit_sell and sell_price is None:
        return None

    # Cross-window resolution CTEs are expensive full-series scans; only build
    # them when a condition actually references the corresponding field. Each
    # window resolves on its FINAL snapshot (yes_bid, else yes_ask, >= 50) — the
    # same definition as hold-to-expiration settlement below. The regex guard
    # skips non-numeric close_time rows so the ::bigint cast can't throw.
    fields_used = {c.get("field") for c in (rule.get("conditions") or [])}

    def _res_cte(name, offset):
        return f"""
        {name} AS (
            SELECT (w.close_time::bigint + {offset})::text AS ct,
                   CASE WHEN COALESCE(w.last_bid, w.last_ask) >= 50 THEN 1 ELSE 0 END AS res
            FROM (
                SELECT DISTINCT ON (close_time)
                    close_time, yes_bid AS last_bid, yes_ask AS last_ask
                FROM market_snapshots
                WHERE ticker LIKE %s AND close_time ~ '^[0-9]+$'
                ORDER BY close_time, scanned_at DESC
            ) w
        )"""

    cte_defs, cte_params, join_parts = [], [], []
    if "prior_resolution" in fields_used:
        cte_defs.append(_res_cte("prior_res", 900))
        cte_params.append(series_like)
        join_parts.append("LEFT JOIN prior_res  pr  ON pr.ct  = m.close_time")
    if "prev2_resolution" in fields_used:
        cte_defs.append(_res_cte("prev2_res", 1800))
        cte_params.append(series_like)
        join_parts.append("LEFT JOIN prev2_res  p2r ON p2r.ct = m.close_time")

    fills_def = f"""
        fills AS (
            SELECT DISTINCT ON (m.ticker)
                m.ticker,
                m.scanned_at         AS fill_time,
                m.{ask_col}          AS fill_price,
                m.time_to_close_secs AS ttc_at_fill
            FROM market_snapshots m
            LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
            {' '.join(join_parts)}
            WHERE m.ticker LIKE %s
              AND {entry_clause}
              {cond_clause}
            ORDER BY m.ticker, m.scanned_at
        )"""
    fills_cte = "WITH " + ",".join(cte_defs + [fills_def])
    params = cte_params + [series_like] + entry_params + cond_params

    if is_limit_sell:
        sql = fills_cte + f""",
        exits AS (
            SELECT f.ticker, MIN(s.scanned_at) AS exit_time
            FROM fills f
            JOIN market_snapshots s
              ON s.ticker = f.ticker
             AND s.scanned_at > f.fill_time
             AND s.{bid_col} >= %s
            GROUP BY f.ticker
        )
        SELECT f.ticker, f.fill_price, f.ttc_at_fill,
               e.exit_time, NULL AS final_bid, NULL AS final_ask
        FROM fills f
        LEFT JOIN exits e ON e.ticker = f.ticker
        """
        params.append(sell_price)
    else:
        sql = fills_cte + f""",
        finals AS (
            SELECT DISTINCT ON (ticker)
                ticker, {bid_col} AS final_bid, {ask_col} AS final_ask
            FROM market_snapshots
            WHERE ticker LIKE %s
            ORDER BY ticker, scanned_at DESC
        )
        SELECT f.ticker, f.fill_price, f.ttc_at_fill,
               NULL AS exit_time, fin.final_bid, fin.final_ask
        FROM fills f
        LEFT JOIN finals fin ON fin.ticker = f.ticker
        """
        params.append(series_like)

    cur.execute(sql, params)
    rows = cur.fetchall()

    trades = []
    for r in rows:
        fill = float(r["fill_price"])
        if is_limit_sell:
            if r["exit_time"] is not None:
                pnl = (float(sell_price) - fill) * qty
                outcome = "sold"
            else:
                pnl = -fill * qty                 # conservative: full loss on no-sell
                outcome = "expired"
        else:
            ref = r["final_bid"] if r["final_bid"] is not None else r["final_ask"]
            resolved_yes = ref is not None and float(ref) >= 50
            if side == "yes":
                settle = 100 if resolved_yes else 0
            else:
                settle = 0 if resolved_yes else 100
            pnl = (settle - fill) * qty
            outcome = "won" if pnl > 0 else "lost"
        trades.append({
            "ticker":      r["ticker"],
            "side":        side,
            "fill_price":  round(fill, 1),
            "ttc_at_fill": int(r["ttc_at_fill"]) if r["ttc_at_fill"] is not None else None,
            "exit_kind":   "limit_sell" if is_limit_sell else "hold",
            "exit_price":  float(sell_price) if is_limit_sell else None,
            "pnl_cents":   round(pnl, 1),
            "qty":         qty,
            "outcome":     outcome,
        })
    return trades


def _bt_aggregate(trades):
    n = len(trades)
    if n == 0:
        return {
            "trade_count": 0, "win_count": 0, "loss_count": 0, "win_rate": None,
            "total_pnl_cents": 0, "total_cost_cents": 0, "roi_pct": None,
            "avg_pnl_cents": None, "avg_fill_price": None,
            "sold_count": 0, "expired_count": 0,
        }
    wins       = sum(1 for t in trades if t["pnl_cents"] > 0)
    losses     = sum(1 for t in trades if t["pnl_cents"] < 0)
    total_pnl  = sum(t["pnl_cents"] for t in trades)
    total_cost = sum(t["fill_price"] * t["qty"] for t in trades)
    return {
        "trade_count":     n,
        "win_count":       wins,
        "loss_count":      losses,
        "win_rate":        round(wins / n * 100, 1),
        "total_pnl_cents":  round(total_pnl, 1),
        "total_cost_cents": round(total_cost, 1),
        "roi_pct":         round(total_pnl / total_cost * 100, 1) if total_cost else None,
        "avg_pnl_cents":   round(total_pnl / n, 1),
        "avg_fill_price":  round(sum(t["fill_price"] for t in trades) / n, 1),
        "sold_count":      sum(1 for t in trades if t["outcome"] == "sold"),
        "expired_count":   sum(1 for t in trades if t["outcome"] == "expired"),
    }


@app.post("/api/backtest/strategy")
def backtest_strategy():
    body   = request.get_json(silent=True) or {}
    rules  = body.get("rules") or []
    series = (body.get("series") or "KXBTC15M").strip().upper()
    if not series.replace("_", "").isalnum():
        return jsonify({"error": "invalid series"}), 400
    series_like = f"{series}-%"

    rule_results = []
    all_trades   = []
    with _conn() as cur:
        for idx, rule in enumerate(rules):
            if not rule.get("enabled", True):
                continue
            action = rule.get("action") or {}
            side_spec = action.get("side", "yes")
            sides = ("yes", "no") if side_spec == "both" else (side_spec,)

            simulated_any = False
            rule_trades = []
            for side in sides:
                if side not in ("yes", "no"):
                    continue
                t = _bt_simulate_rule(cur, series_like, rule, side)
                if t is None:
                    continue
                simulated_any = True
                rule_trades.extend(t)

            if not simulated_any:
                continue
            rule_results.append({
                "rule_id":   rule.get("id") or f"idx{idx}",
                "rule_name": rule.get("name") or "",
                **_bt_aggregate(rule_trades),
            })
            all_trades.extend(rule_trades)

    sample = sorted(all_trades, key=lambda t: t["pnl_cents"], reverse=True)[:200]
    return jsonify({
        "summary": _bt_aggregate(all_trades),
        "rules":   rule_results,
        "trades":  sample,
    })


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
                    "snapshots":  ws_worker.get_snapshots(),
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
            WHERE order_role = 'entry' AND status IN ('resting','filled') AND DATE(placed_at) = %s {where_clause}
        """, params)
        today_spend = c.fetchone()[0]

        # Reset params for counts, keeping only profile_id if present
        count_where = "WHERE order_role = 'entry'"
        count_params = []
        if profile_id:
            count_where += " AND profile_id = %s"
            count_params = [profile_id]

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
        SELECT id, kalshi_order_id, market_ticker, side, order_role,
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
    lifecycle: order count, entry cost, close proceeds, and realized P&L.
    """
    limit = min(int(request.args.get("limit", 200)), 500)
    profile_id = request.args.get("profile_id")

    where_clauses = ["order_role = 'entry'"]
    params = []
    if profile_id:
        where_clauses.append("o.profile_id = %s")
        params.append(profile_id)

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    query = f"""
        SELECT
            o.market_ticker,
            COUNT(*)                                                                 AS order_count,
            COUNT(*) FILTER (WHERE o.closed_at IS NOT NULL)                          AS closed_order_count,
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

    with _conn() as c:
        c.execute(query, params)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/snapshots")
def snapshots():
    limit_param = request.args.get("limit")
    limit = int(limit_param) if limit_param else None
    ticker = (request.args.get("ticker") or "").strip().upper()
    if ticker:
        return jsonify(database.get_market_snapshots_for_ticker(ticker, limit))
    return jsonify(database.get_recent_market_snapshots(limit))


@app.get("/api/snapshots/tickers")
def snapshot_tickers():
    """Return one summary row per distinct ticker in market_snapshots, ordered by most recent scan."""
    with _conn() as c:
        c.execute("""
            SELECT ticker, title, strike_str,
                   yes_ask, yes_bid, no_ask,
                   volume, open_interest, time_to_close_secs,
                   scanned_at
            FROM (
                SELECT DISTINCT ON (ticker)
                       ticker, title, strike_str,
                       yes_ask, yes_bid, no_ask,
                       volume, open_interest, time_to_close_secs,
                       scanned_at
                FROM market_snapshots
                ORDER BY ticker, id DESC
            ) latest
            ORDER BY scanned_at DESC
        """)
        rows = c.fetchall()
    return jsonify([dict(r) for r in rows])


@app.get("/api/profiles")
def get_profiles():
    with _conn() as c:
        c.execute("""
            SELECT p.*,
                   COUNT(DISTINCT o.market_ticker)                                                           AS order_count,
                   COUNT(DISTINCT o.market_ticker) FILTER (WHERE o.net_profit_cents > 0)               AS win_count,
                   COUNT(DISTINCT o.market_ticker) FILTER (WHERE o.net_profit_cents IS NOT NULL
                                                               AND o.net_profit_cents <= 0)            AS loss_count,
                   COALESCE(SUM(o.entry_price_cents * o.count) FILTER (WHERE o.status = 'filled'), 0) AS total_spend_cents,
                   COALESCE(SUM(o.net_profit_cents) FILTER (WHERE o.net_profit_cents IS NOT NULL), 0) AS total_profit_cents
            FROM profiles p
                 LEFT JOIN orders o ON o.profile_id = p.id AND o.order_role = 'entry'
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


@app.post("/api/profiles/<int:profile_id>/deactivate")
def deactivate_profile(profile_id: int):
    try:
        database.deactivate_profile(profile_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"status": "success"})


@app.delete("/api/profiles/<int:profile_id>")
def delete_profile(profile_id: int):
    try:
        ok, count = database.delete_profile(profile_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not ok:
        if count is None:
            return jsonify({"error": "Profile not found"}), 404
        return jsonify({"error": "Profile has historical runs and cannot be deleted", "order_count": count}), 409

    return jsonify({"status": "success", "deleted_profile_id": profile_id}), 200


@app.get("/api/snapshots/series")
def snapshot_series():
    ticker = request.args.get("ticker", "").strip().upper()
    try:
        limit = min(int(request.args.get("limit", 300)), 1000)
    except ValueError:
        limit = 300

    if not ticker:
        return jsonify({"error": "ticker required"}), 400

    # We want them ascending for the chart
    with _conn() as c:
        c.execute("""
            SELECT m.scanned_at, m.yes_bid, m.no_bid,
                   COALESCE(b.consolidated_price, b.coinbase_price) AS btc_price,
                   b.consolidated_price AS brti_price,
                   b.coinbase_price, b.kraken_price, b.bitstamp_price, b.gemini_price, m.strike_str
            FROM market_snapshots m
            LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
            WHERE m.ticker = %s
            ORDER BY m.id DESC
            LIMIT %s
        """, (ticker, limit))
        rows = c.fetchall()

    # Reverse to get chronological order
    data = [dict(r) for r in reversed(rows)]
    return jsonify(data)


# ── Analytics ────────────────────────────────────────────────────────────


@app.get("/api/analytics/overview")
def analytics_overview():
    with _conn() as c:
        c.execute("""
            SELECT
                COUNT(*)::bigint            AS total_snapshots,
                COUNT(DISTINCT ticker)::int AS unique_markets,
                MIN(scanned_at)             AS first_snapshot,
                MAX(scanned_at)             AS last_snapshot
            FROM market_snapshots
        """)
        overview = dict(c.fetchone())

        c.execute("""
            WITH final AS (
                SELECT DISTINCT ON (ticker)
                    ticker, yes_ask, time_to_close_secs
                FROM market_snapshots
                WHERE time_to_close_secs IS NOT NULL
                ORDER BY ticker, time_to_close_secs ASC
            )
            SELECT
                COUNT(*) FILTER (
                    WHERE time_to_close_secs < 120
                      AND (yes_ask >= 85 OR yes_ask <= 15)
                )::int AS resolved_markets,
                COUNT(*) FILTER (
                    WHERE time_to_close_secs < 120 AND yes_ask >= 85
                )::int AS yes_wins,
                COUNT(*) FILTER (
                    WHERE time_to_close_secs < 120 AND yes_ask <= 15
                )::int AS no_wins
            FROM final
        """)
        resolution = dict(c.fetchone())

    overview.update(resolution)
    return jsonify(overview)


@app.get("/api/analytics/edge-matrix")
def analytics_edge_matrix():
    """Price x Time-to-Close matrix showing actual win rates vs implied probability."""
    with _conn() as c:
        c.execute("""
            WITH resolved AS (
                SELECT DISTINCT ON (ticker)
                    ticker,
                    CASE WHEN yes_ask >= 85 THEN true ELSE false END AS won_yes
                FROM market_snapshots
                WHERE time_to_close_secs IS NOT NULL
                  AND time_to_close_secs < 120
                  AND (yes_ask >= 85 OR yes_ask <= 15)
                ORDER BY ticker, time_to_close_secs ASC
            )
            SELECT
                (FLOOR(s.yes_ask / 10)::int * 10) AS price_bucket,
                CASE
                    WHEN s.time_to_close_secs <= 120 THEN '0-2m'
                    WHEN s.time_to_close_secs <= 300 THEN '2-5m'
                    WHEN s.time_to_close_secs <= 600 THEN '5-10m'
                    ELSE '10-15m'
                END AS ttc_bucket,
                CASE
                    WHEN s.time_to_close_secs <= 120 THEN 1
                    WHEN s.time_to_close_secs <= 300 THEN 2
                    WHEN s.time_to_close_secs <= 600 THEN 3
                    ELSE 4
                END AS ttc_order,
                COUNT(DISTINCT s.ticker)::int AS market_count,
                ROUND(AVG(CASE WHEN r.won_yes THEN 1.0 ELSE 0.0 END) * 100, 1) AS actual_win_pct
            FROM market_snapshots s
            JOIN resolved r ON r.ticker = s.ticker
            WHERE s.yes_ask IS NOT NULL
              AND s.yes_ask > 0
              AND s.yes_ask < 100
              AND s.time_to_close_secs IS NOT NULL
              AND s.time_to_close_secs > 0
            GROUP BY 1, 2, 3
            HAVING COUNT(DISTINCT s.ticker) >= 3
            ORDER BY 1, 3
        """)
        rows = c.fetchall()
    return jsonify([{
        "price_bucket":   int(r["price_bucket"]),
        "ttc_bucket":     r["ttc_bucket"],
        "ttc_order":      int(r["ttc_order"]),
        "market_count":   int(r["market_count"]),
        "actual_win_pct": float(r["actual_win_pct"]) if r["actual_win_pct"] else 0,
    } for r in rows])


@app.get("/api/analytics/ev-curve")
def analytics_ev_curve():
    """Per-cent expected value curve for low-price YES entries."""
    try:
        max_price = min(int(request.args.get("max_price", 50)), 99)
    except ValueError:
        max_price = 50

    with _conn() as c:
        c.execute("""
            WITH resolved AS (
                SELECT DISTINCT ON (ticker)
                    ticker,
                    CASE WHEN yes_ask >= 85 THEN true ELSE false END AS won_yes
                FROM market_snapshots
                WHERE time_to_close_secs IS NOT NULL
                  AND time_to_close_secs < 120
                  AND (yes_ask >= 85 OR yes_ask <= 15)
                ORDER BY ticker, time_to_close_secs ASC
            )
            SELECT
                FLOOR(s.yes_ask)::int        AS price_cent,
                COUNT(DISTINCT s.ticker)::int AS market_count,
                ROUND(AVG(CASE WHEN r.won_yes THEN 1.0 ELSE 0.0 END) * 100, 2) AS win_pct
            FROM market_snapshots s
            JOIN resolved r ON r.ticker = s.ticker
            WHERE s.yes_ask IS NOT NULL
              AND s.yes_ask >= 1
              AND s.yes_ask <= %s
              AND s.time_to_close_secs IS NOT NULL
            GROUP BY 1
            HAVING COUNT(DISTINCT s.ticker) >= 2
            ORDER BY 1
        """, (max_price,))
        rows = c.fetchall()

    return jsonify([{
        "price":    int(r["price_cent"]),
        "markets":  int(r["market_count"]),
        "win_pct":  float(r["win_pct"]),
        "ev_cents": round(float(r["win_pct"]) - int(r["price_cent"]), 2),
    } for r in rows])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8820, debug=False)
