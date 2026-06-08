"""
Backtest route: replay a rule list over historical market_snapshots.
"""

from flask import Blueprint, jsonify, request

import config
import database
from database.core import cursor_conn

backtest_bp = Blueprint('backtest', __name__)

# ── SQL column map ────────────────────────────────────────────────────────────
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
    "btc_volatility":     "cz.btc_volatility",
    "btc_range":          "cz.btc_range",
    "btc_drift":          "cz.btc_drift",
    "strike_crossings":   "cz.strike_crossings",
    "buffer_ratio":       "cz.buffer_ratio",
}
_BT_OP = {"lt": "<", "lte": "<=", "gt": ">", "gte": ">=", "eq": "="}
_BT_CRAZE_FIELDS = {"btc_volatility", "btc_range", "btc_drift", "strike_crossings", "buffer_ratio"}


def _bt_craze_cte(series_like, window_secs, need_cross):
    """Build the `craze` CTE for windowed BTC stats (volatility, range, drift, crossings, buffer)."""
    px     = "COALESCE(b.consolidated_price, b.coinbase_price)"
    strike = "NULLIF(m.strike_str, '')::numeric"
    win    = (f"PARTITION BY ticker ORDER BY scanned_at::timestamp "
              f"RANGE BETWEEN INTERVAL '{int(window_secs)} seconds' PRECEDING AND CURRENT ROW")
    win_full = ("PARTITION BY ticker ORDER BY scanned_at::timestamp "
                "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW")

    if need_cross:
        inner = f"""
            SELECT ticker, scanned_at, px, strike, above_int,
                   CASE WHEN above_int <> lag(above_int)
                            OVER (PARTITION BY ticker ORDER BY scanned_at::timestamp)
                        THEN 1 ELSE 0 END AS cross_flag
            FROM (
                SELECT m.ticker, m.scanned_at, {px} AS px, {strike} AS strike,
                       CASE WHEN {px} > {strike} THEN 1 ELSE 0 END AS above_int
                FROM market_snapshots m
                LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
                WHERE m.ticker LIKE %s
                  AND COALESCE(b.consolidated_price, b.coinbase_price) IS NOT NULL
            ) z
        """
        cross_col = "COALESCE(sum(cross_flag) OVER wfull, 0) AS strike_crossings,"
    else:
        inner = f"""
            SELECT m.ticker, m.scanned_at, {px} AS px, {strike} AS strike
            FROM market_snapshots m
            LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
            WHERE m.ticker LIKE %s
        """
        cross_col = ""

    cte = f"""
        craze AS (
            SELECT ticker, scanned_at,
                   stddev_pop(px) OVER w                       AS btc_volatility,
                   (max(px) OVER w - min(px) OVER w)           AS btc_range,
                   (px - first_value(px) OVER w)               AS btc_drift,
                   {cross_col}
                   (abs(px - strike) / NULLIF(stddev_pop(px) OVER w, 0)) AS buffer_ratio
            FROM ( {inner} ) zz
            WINDOW w AS ({win}){(", wfull AS (" + win_full + ")") if need_cross else ""}
        )"""
    return cte, [series_like]


def _bt_conditions_sql(conditions):
    """Build an extra SQL WHERE clause + params from a rule's condition list."""
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
    the rule is incomplete (missing required entry/exit price)."""
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

    stop_cents = exit_.get("stop_cents")
    try:
        stop_cents = int(stop_cents) if stop_cents not in (None, "") else None
    except (TypeError, ValueError):
        stop_cents = None
    if stop_cents is not None and not (1 <= stop_cents <= 99):
        stop_cents = None

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
    if fields_used & _BT_CRAZE_FIELDS:
        craze_sql, craze_params = _bt_craze_cte(
            series_like, config.CRAZINESS_LOOKBACK_SECONDS,
            need_cross="strike_crossings" in fields_used)
        cte_defs.append(craze_sql)
        cte_params.extend(craze_params)
        join_parts.append(
            "LEFT JOIN craze cz ON cz.ticker = m.ticker AND cz.scanned_at = m.scanned_at")

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
        SELECT f.ticker, f.fill_time, f.fill_price, f.ttc_at_fill,
               e.exit_time, NULL AS final_bid, NULL AS final_ask
        FROM fills f
        LEFT JOIN exits e ON e.ticker = f.ticker
        """
        params.append(sell_price)
    else:
        stop_cte, stop_sel, stop_join = "", "NULL", ""
        if stop_cents is not None:
            stop_cte = f""",
        stops AS (
            SELECT DISTINCT ON (s.ticker) s.ticker, s.{bid_col} AS stop_bid
            FROM fills f
            JOIN market_snapshots s
              ON s.ticker = f.ticker
             AND s.scanned_at > f.fill_time
             AND s.{bid_col} <= %s AND s.{bid_col} > 0
            ORDER BY s.ticker, s.scanned_at
        )"""
            stop_sel  = "st.stop_bid"
            stop_join = "LEFT JOIN stops st ON st.ticker = f.ticker"
        sql = fills_cte + f""",
        finals AS (
            SELECT DISTINCT ON (ticker)
                ticker, yes_bid AS final_bid, yes_ask AS final_ask
            FROM market_snapshots
            WHERE ticker LIKE %s
            ORDER BY ticker, scanned_at DESC
        ){stop_cte}
        SELECT f.ticker, f.fill_time, f.fill_price, f.ttc_at_fill,
               NULL AS exit_time, fin.final_bid, fin.final_ask,
               ms.result AS official, {stop_sel} AS stop_bid
        FROM fills f
        LEFT JOIN finals fin ON fin.ticker = f.ticker
        LEFT JOIN market_settlements ms ON ms.ticker = f.ticker
        {stop_join}
        """
        params.append(series_like)
        if stop_cents is not None:
            params.append(stop_cents)

    cur.execute(sql, params)
    rows = cur.fetchall()

    trades = []
    for r in rows:
        fill = float(r["fill_price"])
        settle_win = None
        stopped = False
        if is_limit_sell:
            if r["exit_time"] is not None:
                pnl = (float(sell_price) - fill) * qty
                outcome = "sold"
            else:
                pnl = -fill * qty
                outcome = "expired"
        else:
            official = r.get("official") if hasattr(r, "get") else r["official"]
            if official in ("yes", "no"):
                resolved_yes = official == "yes"
            else:
                ref = r["final_bid"] if r["final_bid"] is not None else r["final_ask"]
                resolved_yes = ref is not None and float(ref) >= 50
            settle = (100 if resolved_yes else 0) if side == "yes" else (0 if resolved_yes else 100)
            settle_win = (settle - fill) > 0
            stop_bid = r["stop_bid"] if r["stop_bid"] is not None else None
            if stop_bid is not None:
                pnl = (float(stop_bid) - fill) * qty
                outcome = "stopped"
                stopped = True
            else:
                pnl = (settle - fill) * qty
                outcome = "won" if pnl > 0 else "lost"
        trades.append({
            "ticker":      r["ticker"],
            "side":        side,
            "fill_time":   r["fill_time"],
            "fill_price":  round(fill, 1),
            "ttc_at_fill": int(r["ttc_at_fill"]) if r["ttc_at_fill"] is not None else None,
            "exit_kind":   "limit_sell" if is_limit_sell else "hold",
            "exit_price":  float(sell_price) if is_limit_sell else None,
            "pnl_cents":   round(pnl, 1),
            "qty":         qty,
            "outcome":     outcome,
            "stopped":     stopped,
            "settle_win":  settle_win,
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


@backtest_bp.post("/api/backtest/strategy")
def backtest_strategy():
    body   = request.get_json(silent=True) or {}
    rules  = body.get("rules") or []
    series = (body.get("series") or "KXBTC15M").strip().upper()
    if not series.replace("_", "").isalnum():
        return jsonify({"error": "invalid series"}), 400
    series_like = f"{series}-%"

    rule_results = []
    all_trades   = []
    with cursor_conn() as cur:
        for idx, rule in enumerate(rules):
            if not rule.get("enabled", True):
                continue
            action    = rule.get("action") or {}
            side_spec = action.get("side", "yes")
            sides     = ("yes", "no") if side_spec == "both" else (side_spec,)

            rule_trades = []
            simulated_any = False
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
