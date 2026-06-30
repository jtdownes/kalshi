"""
Backtest route: replay a rule list over historical market_snapshots.
"""

from flask import Blueprint, jsonify, request

import config
import crypto_assets
import database
from database.core import cursor_conn

backtest_bp = Blueprint('backtest', __name__)

# The alias `b` in the queries below joins the series' UNDERLYING asset
# snapshot table (bitcoin_snapshots for KXBTC*, ethereum_snapshots for
# KXETH*, ...), so btc_price / distance_to_strike / craziness fields are
# computed against the right asset. The table name always comes from the
# crypto_assets registry — never from request input.

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

# Data-quality gate: the simulator replays each market's 1s snapshot series
# tick-by-tick, so bad coverage produces fabricated fills/exits that skew
# results. A market is dropped when:
#   - its largest inter-snapshot gap exceeds _BT_MAX_GAP_SECS (collector was
#     down/restarting — a hole the replay flies blind through), or
#   - it has fewer than _BT_MIN_SNAPS snapshots (barely tracked), or
#   - its quote is frozen: the same yes_bid repeats for >= _BT_MAX_FROZEN_FRAC of
#     its life at a mid-range (undecided) value. That's a stale feed (e.g. during
#     a Kalshi outage) where the rows keep landing but the price stops updating,
#     so the simulator reads the frozen final bid as a bogus win/loss. Pinning at
#     an extreme (<=_BT_FROZEN_LO or >=_BT_FROZEN_HI) is a genuinely-decided
#     market and left alone.
#   - it has a long opening dead-zone: yes_ask sits at 0 (the 0/100 placeholder
#     stored before the order book exists — no real two-sided market, volume 0)
#     for more than _BT_OPEN_DEADZONE_SECS at the open. Normal markets get real
#     quotes within ~1-3s; a multi-minute dead-zone is the obvious "0/100 for the
#     first few minutes" error. This is keyed on the OPENING stretch specifically
#     so a genuine loser (real quotes throughout, settles to 0 at the end) is not
#     touched.
# Healthy 15-min markets have ~280+ snapshots, sub-30s gaps, hold any single
# quote ~12% of the time, and open within seconds, so these thresholds only catch
# the broken ones. The gap/count cutoffs are overridable per-request
# (max_gap_secs / min_snaps).
_BT_MAX_GAP_SECS       = 120
_BT_MIN_SNAPS          = 60
_BT_MAX_FROZEN_FRAC    = 0.5
_BT_FROZEN_LO          = 10
_BT_FROZEN_HI          = 90
_BT_OPEN_DEADZONE_SECS = 30


def _bt_market_quality(cur, series_like, max_gap_secs, min_snaps, tickers=None):
    """Return {ticker: {snaps, max_gap, frozen_frac, bad, reason}} for the series.

    Scoped to `tickers` when given, else the whole series (via the LIKE pattern).
    See the module-level note for what flags a market bad."""
    where, params = ("m.ticker = ANY(%s)", [list(tickers)]) if tickers is not None \
        else ("m.ticker LIKE %s", [series_like])
    # Gaps-and-islands: a new "run" starts whenever yes_bid changes, so the
    # largest run per ticker is its longest stretch of an unchanged quote.
    cur.execute(f"""
        WITH lagged AS (
            SELECT m.ticker, m.scanned_at, m.yes_bid, m.yes_ask, m.time_to_close_secs AS ttc,
                   EXTRACT(EPOCH FROM (m.scanned_at::timestamp - lag(m.scanned_at::timestamp)
                       OVER (PARTITION BY m.ticker ORDER BY m.scanned_at::timestamp))) AS gap,
                   lag(m.yes_bid) OVER (PARTITION BY m.ticker ORDER BY m.scanned_at::timestamp) AS prev_bid
            FROM market_snapshots m
            WHERE {where}
        ),
        base AS (
            SELECT ticker, scanned_at, yes_bid, yes_ask, ttc, gap,
                   sum(CASE WHEN yes_bid IS DISTINCT FROM prev_bid THEN 1 ELSE 0 END)
                       OVER (PARTITION BY ticker ORDER BY scanned_at::timestamp
                             ROWS UNBOUNDED PRECEDING) AS grp
            FROM lagged
        ),
        runs AS (
            SELECT ticker, yes_bid, count(*) AS run_len FROM base GROUP BY ticker, grp, yes_bid
        ),
        toprun AS (
            SELECT DISTINCT ON (ticker) ticker, run_len AS max_run, yes_bid AS frozen_val
            FROM runs ORDER BY ticker, run_len DESC
        ),
        agg AS (
            SELECT ticker, count(*) AS snaps, COALESCE(max(gap), 0)::int AS max_gap,
                   max(ttc) AS open_ttc, max(ttc) FILTER (WHERE yes_ask > 0) AS first_real_ttc
            FROM base GROUP BY ticker
        )
        SELECT a.ticker, a.snaps, a.max_gap, a.open_ttc, a.first_real_ttc, tr.max_run, tr.frozen_val
        FROM agg a JOIN toprun tr ON tr.ticker = a.ticker
    """, params)
    out = {}
    for r in cur.fetchall():
        snaps, max_gap = r["snaps"], r["max_gap"]
        frozen_frac = (r["max_run"] / snaps) if snaps else 0.0
        fval = r["frozen_val"]
        # Opening dead-zone: seconds at the open with no real yes_ask (0/100
        # placeholder). first_real_ttc is None if the market never had a quote.
        if r["first_real_ttc"] is None:
            open_dead = r["open_ttc"] or 0
        else:
            open_dead = (r["open_ttc"] or 0) - r["first_real_ttc"]
        reason = None
        if snaps < min_snaps:
            reason = f"only {snaps} snapshots"
        elif max_gap > max_gap_secs:
            reason = f"{max_gap}s data gap"
        elif open_dead > _BT_OPEN_DEADZONE_SECS:
            reason = f"no quotes for first {open_dead}s (0/100 at open)"
        elif (frozen_frac >= _BT_MAX_FROZEN_FRAC and fval is not None
              and _BT_FROZEN_LO <= float(fval) <= _BT_FROZEN_HI):
            reason = f"quote frozen {round(frozen_frac * 100)}% of life at {round(float(fval))}¢"
        out[r["ticker"]] = {"snaps": snaps, "max_gap": max_gap,
                            "frozen_frac": round(frozen_frac, 3),
                            "open_dead_secs": open_dead,
                            "bad": reason is not None, "reason": reason}
    return out


def _bt_craze_cte(series_like, window_secs, need_cross, snap_table, pc_windows=None, bands=None):
    """Build the `craze` CTE for windowed underlying-price stats (volatility, range, drift, crossings, buffer).

    `pc_windows` adds one signed-drift column per distinct price_change lookback
    (pc_<secs>), each over its own RANGE window — the tunable counterpart to the
    fixed-window btc_drift.

    `bands` adds one strike_crossings_band column per distinct band ($): zone
    changes around a ±band zone, running from the market's first snapshot — the
    exact mirror of db.get_strike_crossings(band) so live and sim agree."""
    px     = "COALESCE(b.consolidated_price, b.coinbase_price)"
    strike = "NULLIF(m.strike_str, '')::numeric"
    win    = (f"PARTITION BY ticker ORDER BY scanned_at::timestamp "
              f"RANGE BETWEEN INTERVAL '{int(window_secs)} seconds' PRECEDING AND CURRENT ROW")
    win_full = ("PARTITION BY ticker ORDER BY scanned_at::timestamp "
                "ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW")

    pc_windows = sorted({int(w) for w in (pc_windows or [])})
    pc_cols = "".join(
        f"(px - first_value(px) OVER w_{_pc_col(w)}) AS {_pc_col(w)}, "
        for w in pc_windows)
    pc_win_defs = "".join(
        f", w_{_pc_col(w)} AS (PARTITION BY ticker ORDER BY scanned_at::timestamp "
        f"RANGE BETWEEN INTERVAL '{w} seconds' PRECEDING AND CURRENT ROW)"
        for w in pc_windows)

    bands = sorted({round(abs(float(b)), 6) for b in (bands or []) if float(b) > 0})
    need_rich  = need_cross or bool(bands)
    need_wfull = need_cross or bool(bands)
    order = "OVER (PARTITION BY ticker ORDER BY scanned_at::timestamp)"

    # innermost: per-row zone / above flags;  middle: change flags vs previous row.
    inner_cols, mid_cols, out_cols = "", "", ""
    if need_cross:
        inner_cols += f", CASE WHEN {px} > {strike} THEN 1 ELSE 0 END AS above_int"
        mid_cols   += (f", CASE WHEN above_int <> lag(above_int) {order} "
                       "THEN 1 ELSE 0 END AS cross_flag")
        out_cols   += "COALESCE(sum(cross_flag) OVER wfull, 0) AS strike_crossings,"
    for b in bands:
        col, z = _bt_band_col(b), f"zone_{_bt_band_col(b)}"
        inner_cols += (f", CASE WHEN {px} > {strike} + {b:.6f} THEN 1 "
                       f"WHEN {px} < {strike} - {b:.6f} THEN -1 ELSE 0 END AS {z}")
        mid_cols   += f", CASE WHEN {z} <> lag({z}) {order} THEN 1 ELSE 0 END AS {col}_flag"
        out_cols   += f"COALESCE(sum({col}_flag) OVER wfull, 0) AS {col},"

    if need_rich:
        inner = f"""
            SELECT ticker, scanned_at, px, strike{mid_cols}
            FROM (
                SELECT m.ticker, m.scanned_at, {px} AS px, {strike} AS strike{inner_cols}
                FROM market_snapshots m
                LEFT JOIN {snap_table} b ON b.scanned_at = m.scanned_at
                WHERE m.ticker LIKE %s
                  AND COALESCE(b.consolidated_price, b.coinbase_price) IS NOT NULL
            ) z
        """
    else:
        inner = f"""
            SELECT m.ticker, m.scanned_at, {px} AS px, {strike} AS strike
            FROM market_snapshots m
            LEFT JOIN {snap_table} b ON b.scanned_at = m.scanned_at
            WHERE m.ticker LIKE %s
        """

    cte = f"""
        craze AS (
            SELECT ticker, scanned_at,
                   stddev_pop(px) OVER w                       AS btc_volatility,
                   (max(px) OVER w - min(px) OVER w)           AS btc_range,
                   (px - first_value(px) OVER w)               AS btc_drift,
                   {out_cols}
                   {pc_cols}
                   (abs(px - strike) / NULLIF(stddev_pop(px) OVER w, 0)) AS buffer_ratio
            FROM ( {inner} ) zz
            WINDOW w AS ({win}){(", wfull AS (" + win_full + ")") if need_wfull else ""}{pc_win_defs}
        )"""
    return cte, [series_like]


def _pc_col(window_secs):
    """SQL column name for a price_change condition's windowed drift in the craze CTE."""
    return f"pc_{int(window_secs)}"


def _bt_pc_windows(conditions):
    """Distinct, valid trailing windows (secs) referenced by price_change conditions."""
    windows = set()
    for c in conditions or []:
        if c.get("field") != "price_change":
            continue
        try:
            w = int(c.get("window_secs"))
        except (TypeError, ValueError):
            continue
        if w > 0:
            windows.add(w)
    return sorted(windows)


def _bt_band_col(band):
    """SQL column name for a strike_crossings_band count at this band ($)."""
    return "xb_" + f"{abs(float(band)):.6f}".replace(".", "_")


def _bt_xc_bands(conditions):
    """Distinct, valid bands ($) referenced by strike_crossings conditions."""
    bands = set()
    for c in conditions or []:
        if c.get("field") != "strike_crossings":
            continue
        try:
            b = round(abs(float(c.get("band"))), 6)
        except (TypeError, ValueError):
            continue
        if b > 0:
            bands.add(b)
    return sorted(bands)


def _bt_conditions_sql(conditions):
    """Build an extra SQL WHERE clause + params from a rule's condition list."""
    clauses, params = [], []
    for c in conditions or []:
        field = c.get("field")
        if field == "price_change":
            try:
                w = int(c.get("window_secs"))
            except (TypeError, ValueError):
                continue
            col = f"cz.{_pc_col(w)}" if w > 0 else None
        elif field == "strike_crossings":
            # optional band ($): band>0 -> per-band column; else the exact count.
            try:
                b = round(abs(float(c.get("band"))), 6)
            except (TypeError, ValueError):
                b = 0
            col = f"cz.{_bt_band_col(b)}" if b > 0 else _BT_COL.get(field)
        else:
            col = _BT_COL.get(field)
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


def _bt_clean_legs(legs, quantity):
    """Mirror of the live engine's ladder validation (rules in bot.py)."""
    if not isinstance(legs, list) or not legs:
        return None
    clean, total = [], 0
    for leg in legs:
        try:
            q = int(leg.get("qty"))
            p = int(leg.get("price_cents"))
        except (TypeError, ValueError, AttributeError):
            return None
        if q < 1 or not (1 <= p <= 99):
            return None
        if total + q > quantity:
            q = quantity - total
            if q < 1:
                break
        clean.append({"qty": q, "price_cents": p})
        total += q
    return clean or None


def _bt_walk_rich_exits(cur, fills_cte, params, series_like, side, bid_col,
                        qty, legs, stop_cents, stop_pct, time_exit_secs):
    """Replay rich exits (scale-out ladder / %-stop / time exit / stop alongside
    a limit sell) by walking each filled market's snapshot series after the fill.

    Per tick, in priority order: stop fires first (sell remainder at the bid),
    then the time exit, then any ladder rung whose price the bid has reached.
    Whatever remains at the end settles on the official result.
    """
    sql = fills_cte + """,
        finals AS (
            SELECT DISTINCT ON (ticker)
                ticker, yes_bid AS final_bid, yes_ask AS final_ask
            FROM market_snapshots
            WHERE ticker LIKE %s
              -- skip the close-time "no book" placeholder (0/100/0/100), which
              -- otherwise reads as final_bid=0 and inverts the settled outcome
              AND NOT (yes_bid = 0 AND yes_ask = 100 AND no_bid = 0 AND no_ask = 100)
            ORDER BY ticker, scanned_at DESC
        )
        SELECT f.ticker, f.fill_time, f.fill_price, f.ttc_at_fill,
               fin.final_bid, fin.final_ask, ms.result AS official
        FROM fills f
        LEFT JOIN finals fin ON fin.ticker = f.ticker
        LEFT JOIN market_settlements ms ON ms.ticker = f.ticker
    """
    cur.execute(sql, params + [series_like])
    fills = cur.fetchall()
    if not fills:
        return []

    min_fill = min(r["fill_time"] for r in fills)
    cur.execute(f"""
        SELECT ticker, scanned_at, {bid_col} AS bid, time_to_close_secs AS ttc
        FROM market_snapshots
        WHERE ticker = ANY(%s) AND scanned_at > %s
        ORDER BY ticker, scanned_at
    """, ([r["ticker"] for r in fills], min_fill))
    series = {}
    for r in cur.fetchall():
        series.setdefault(r["ticker"], []).append(r)

    trades = []
    for f in fills:
        fill = float(f["fill_price"])
        stop = stop_cents
        if stop is None and stop_pct is not None:
            stop = int(fill * (1 - stop_pct / 100.0))
            if not (1 <= stop <= 99):
                stop = None

        remaining  = qty
        proceeds   = 0.0
        pending    = [dict(l) for l in legs]
        outcome    = None
        exit_time  = None
        exit_price = None
        for snap in series.get(f["ticker"], []):
            if snap["scanned_at"] <= f["fill_time"]:
                continue
            bid = snap["bid"]
            if bid is None or float(bid) <= 0:
                continue
            bid = float(bid)
            if stop is not None and bid <= stop:
                proceeds += bid * remaining
                remaining = 0
                outcome, exit_time, exit_price = "stopped", snap["scanned_at"], bid
                break
            if time_exit_secs is not None and snap["ttc"] is not None \
                    and int(snap["ttc"]) <= time_exit_secs:
                proceeds += bid * remaining
                remaining = 0
                outcome, exit_time, exit_price = "time_exit", snap["scanned_at"], bid
                break
            still = []
            for leg in pending:
                if bid >= leg["price_cents"]:
                    proceeds += leg["price_cents"] * leg["qty"]
                    remaining -= leg["qty"]
                    exit_time, exit_price = snap["scanned_at"], float(leg["price_cents"])
                else:
                    still.append(leg)
            pending = still
            if remaining <= 0:
                outcome = "sold"
                break

        settle_win = None
        if remaining > 0:
            official = f["official"]
            if official in ("yes", "no"):
                resolved_yes = official == "yes"
            else:
                ref = f["final_bid"] if f["final_bid"] is not None else f["final_ask"]
                resolved_yes = ref is not None and float(ref) >= 50
            settle = (100 if resolved_yes else 0) if side == "yes" else (0 if resolved_yes else 100)
            settle_win = (settle - fill) > 0
            proceeds += settle * remaining

        pnl = proceeds - fill * qty
        if outcome is None:
            outcome = "won" if pnl > 0 else "lost"
        trades.append({
            "ticker":      f["ticker"],
            "side":        side,
            "fill_time":   f["fill_time"],
            "fill_price":  round(fill, 1),
            "ttc_at_fill": int(f["ttc_at_fill"]) if f["ttc_at_fill"] is not None else None,
            "exit_kind":   "scale_out" if len(legs) > 1 else ("limit_sell" if legs else "hold"),
            "exit_price":  round(exit_price, 1) if exit_price is not None else None,
            "exit_time":   exit_time,
            "pnl_cents":   round(pnl, 1),
            "qty":         qty,
            "outcome":     outcome,
            "stopped":     outcome == "stopped",
            "settle_win":  settle_win,
        })
    return trades


def _bt_simulate_rule(cur, series_like, rule, side, snap_table, tickers=None):
    """Simulate one rule on one side. Returns a list of trade dicts, or None if
    the rule is incomplete (missing required entry/exit price).

    When `tickers` is given, only those markets are considered (used to scope
    the simulation to the most-recent N markets)."""
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

    entry_type = entry.get("type", "limit")

    # The resting limit, in YES/NO ask cents, as an SQL expression fixed at the
    # snapshot where the rule's conditions first pass. Every entry type resolves
    # to one so they all share the two-stage resting-limit fill model below.
    limit_expr, limit_params = None, []
    if entry_type == "ask":
        # Place a limit at the ask we saw; it rests there and only fills if the
        # ask is still <= that level on a later tick.
        limit_expr = f"m.{ask_col}"
    elif entry_type == "ask_minus":
        offset = entry.get("offset_cents")
        if offset is None:
            return None
        limit_expr   = f"(m.{ask_col} - %s)"
        limit_params = [offset]
    elif entry_type == "ask_minus_pct":
        pct = entry.get("offset_pct")
        if pct is None:
            return None
        limit_expr   = f"FLOOR(m.{ask_col} * (1 - %s / 100.0))"
        limit_params = [pct]
    else:
        price = entry.get("price_cents")
        if price is None:
            return None
        limit_expr   = "%s"
        limit_params = [price]

    is_limit_sell = exit_.get("type") == "limit_sell"
    is_scale_out  = exit_.get("type") == "scale_out"
    sell_price = exit_.get("price_cents") if is_limit_sell else None
    if is_limit_sell and sell_price is None:
        return None

    legs = None
    if is_scale_out:
        legs = _bt_clean_legs(exit_.get("legs"), qty)
        if not legs:
            return None

    stop_cents = exit_.get("stop_cents")
    try:
        stop_cents = int(stop_cents) if stop_cents not in (None, "") else None
    except (TypeError, ValueError):
        stop_cents = None
    if stop_cents is not None and not (1 <= stop_cents <= 99):
        stop_cents = None

    stop_pct = exit_.get("stop_pct") if stop_cents is None else None
    try:
        stop_pct = float(stop_pct) if stop_pct not in (None, "") else None
    except (TypeError, ValueError):
        stop_pct = None
    if stop_pct is not None and not (0 < stop_pct < 100):
        stop_pct = None

    time_exit_secs = exit_.get("time_exit_secs")
    try:
        time_exit_secs = int(time_exit_secs) if time_exit_secs not in (None, "") else None
    except (TypeError, ValueError):
        time_exit_secs = None
    if time_exit_secs is not None and time_exit_secs <= 0:
        time_exit_secs = None

    # Exit combinations the single-pass SQL can't express get a Python walk
    # over each filled market's post-fill bid series instead.
    rich_exit = (is_scale_out or time_exit_secs is not None or stop_pct is not None
                 or (stop_cents is not None and is_limit_sell))

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
    pc_windows = _bt_pc_windows(rule.get("conditions"))
    xc_bands   = _bt_xc_bands(rule.get("conditions"))
    if (fields_used & _BT_CRAZE_FIELDS) or pc_windows or xc_bands:
        craze_sql, craze_params = _bt_craze_cte(
            series_like, config.CRAZINESS_LOOKBACK_SECONDS,
            need_cross="strike_crossings" in fields_used,
            snap_table=snap_table, pc_windows=pc_windows, bands=xc_bands)
        cte_defs.append(craze_sql)
        cte_params.extend(craze_params)
        join_parts.append(
            "LEFT JOIN craze cz ON cz.ticker = m.ticker AND cz.scanned_at = m.scanned_at")

    ticker_filter, ticker_params = "", []
    if tickers is not None:
        ticker_filter = " AND m.ticker = ANY(%s)"
        ticker_params = [list(tickers)]

    # Resting-limit fill model (all entry types). The first snapshot where the
    # conditions hold fixes the resting limit (= ask for an "ask" entry, the
    # configured price for a "limit" entry, ask−offset for a relative entry).
    # The order then fills at the first *later* snapshot whose ask has reached
    # that limit — modelling a real resting bid that only fills when the market
    # trades to it. A market whose ask never returns to the limit simply never
    # fills (no phantom instant win), exactly like a live order that rests and is
    # auto-cancelled at settlement. Fill is gated on scanned_at > signal_time so
    # an "ask" entry (whose limit equals the signal ask) can't trivially self-fill
    # on the signal tick — it must survive at least one tick, the realistic
    # minimum for an order that has to be placed after the signal is seen.
    fills_def = f"""
        signals AS (
            SELECT DISTINCT ON (m.ticker)
                m.ticker,
                m.scanned_at AS signal_time,
                {limit_expr} AS limit_price
            FROM market_snapshots m
            LEFT JOIN {snap_table} b ON b.scanned_at = m.scanned_at
            {' '.join(join_parts)}
            WHERE m.ticker LIKE %s{ticker_filter}
              AND m.{ask_col} > 0
              {cond_clause}
            ORDER BY m.ticker, m.scanned_at
        ),
        fills AS (
            SELECT DISTINCT ON (s.ticker)
                s.ticker,
                s.scanned_at         AS fill_time,
                sg.limit_price       AS fill_price,
                s.time_to_close_secs AS ttc_at_fill
            FROM signals sg
            JOIN market_snapshots s
              ON s.ticker = sg.ticker
             AND s.scanned_at > sg.signal_time
             AND s.{ask_col} > 0
             AND s.{ask_col} <= sg.limit_price
            WHERE sg.limit_price >= 1
            ORDER BY s.ticker, s.scanned_at
        )"""
    params = cte_params + limit_params + [series_like] + ticker_params + cond_params
    fills_cte = "WITH " + ",".join(cte_defs + [fills_def])

    if rich_exit:
        if is_limit_sell:
            legs = [{"qty": qty, "price_cents": int(sell_price)}]
        return _bt_walk_rich_exits(
            cur, fills_cte, params, series_like, side, bid_col, qty,
            legs or [], stop_cents, stop_pct, time_exit_secs)

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
        stop_cte, stop_sel, stop_time_sel, stop_join = "", "NULL", "NULL", ""
        if stop_cents is not None:
            stop_cte = f""",
        stops AS (
            SELECT DISTINCT ON (s.ticker) s.ticker, s.{bid_col} AS stop_bid,
                   s.scanned_at AS stop_time
            FROM fills f
            JOIN market_snapshots s
              ON s.ticker = f.ticker
             AND s.scanned_at > f.fill_time
             AND s.{bid_col} <= %s AND s.{bid_col} > 0
            ORDER BY s.ticker, s.scanned_at
        )"""
            stop_sel      = "st.stop_bid"
            stop_time_sel = "st.stop_time"
            stop_join = "LEFT JOIN stops st ON st.ticker = f.ticker"
        sql = fills_cte + f""",
        finals AS (
            SELECT DISTINCT ON (ticker)
                ticker, yes_bid AS final_bid, yes_ask AS final_ask
            FROM market_snapshots
            WHERE ticker LIKE %s
              -- skip the close-time "no book" placeholder (0/100/0/100), which
              -- otherwise reads as final_bid=0 and inverts the settled outcome
              AND NOT (yes_bid = 0 AND yes_ask = 100 AND no_bid = 0 AND no_ask = 100)
            ORDER BY ticker, scanned_at DESC
        ){stop_cte}
        SELECT f.ticker, f.fill_time, f.fill_price, f.ttc_at_fill,
               NULL AS exit_time, fin.final_bid, fin.final_ask,
               ms.result AS official, {stop_sel} AS stop_bid,
               {stop_time_sel} AS stop_time
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
        exit_time  = None
        exit_price = None
        if is_limit_sell:
            if r["exit_time"] is not None:
                pnl = (float(sell_price) - fill) * qty
                outcome = "sold"
                exit_time  = r["exit_time"]
                exit_price = float(sell_price)
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
                exit_time  = r["stop_time"]
                exit_price = float(stop_bid)
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
            "exit_price":  round(exit_price, 1) if exit_price is not None else None,
            "exit_time":   exit_time,
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
    snap_table = crypto_assets.snapshot_table_for_ticker(series)

    # When market_limit is set the simulator scopes the run to the most-recent
    # N markets and surfaces a "skipped" row for every one that no rule filled —
    # so the feed shows all markets, not just the ones that traded.
    try:
        market_limit = int(body.get("market_limit") or 0) or None
    except (TypeError, ValueError):
        market_limit = None

    try:
        max_gap_secs = int(body.get("max_gap_secs") or _BT_MAX_GAP_SECS)
    except (TypeError, ValueError):
        max_gap_secs = _BT_MAX_GAP_SECS
    try:
        min_snaps = int(body.get("min_snaps") or _BT_MIN_SNAPS)
    except (TypeError, ValueError):
        min_snaps = _BT_MIN_SNAPS

    rule_results = []
    all_trades   = []
    tickers      = None      # markets actually simulated (good data only)
    scoped        = None     # all markets in scope (good + bad), for the feed
    ticker_meta  = {}
    quality      = {}
    resolved     = {}        # ticker -> 'yes'/'no' winning side, for non-fill feed rows
    with cursor_conn() as cur:
        # The replay queries are big window-function CTEs over market_snapshots.
        # Postgres plans them with parallel workers, which allocate dynamic
        # shared memory in /dev/shm — capped at 64MB inside the DB container — and
        # intermittently fail mid-query with "could not resize shared memory
        # segment / No space left on device" (surfacing here as a 500 whenever a
        # param tweak pushes the plan over the limit). Run the backtest session
        # serially: it sidesteps the DSM allocation entirely and these queries
        # gain little from parallelism anyway.
        cur.execute("SET max_parallel_workers_per_gather = 0")
        if market_limit:
            cur.execute("""
                SELECT ticker, MAX(scanned_at) AS last_seen
                FROM market_snapshots
                WHERE ticker LIKE %s
                GROUP BY ticker
                ORDER BY MAX(scanned_at) DESC
                LIMIT %s
            """, [series_like, market_limit])
            rows = cur.fetchall()
            scoped      = [r["ticker"] for r in rows]
            ticker_meta = {r["ticker"]: r["last_seen"] for r in rows}

        # Flag markets whose snapshot coverage is too holed/sparse to replay, and
        # simulate only the good ones so fabricated fills/exits can't skew results.
        quality   = _bt_market_quality(cur, series_like, max_gap_secs, min_snaps, tickers=scoped)
        bad_set   = {tk for tk, q in quality.items() if q["bad"]}
        if scoped is not None:
            tickers = [tk for tk in scoped if tk not in bad_set]
        else:
            # No market_limit: scope the run to the good markets explicitly so
            # the bad ones drop out of the LIKE-everything scan.
            tickers = [tk for tk, q in quality.items() if not q["bad"]]

        # Resolve each scoped market's winning side so non-fill feed rows
        # (skipped / bad_data) can still show which side settled YES vs NO.
        # Prefer the official settlement; fall back to the final non-placeholder
        # bid (>= 50 => yes won), mirroring the settle logic used for fills.
        if scoped:
            cur.execute("""
                WITH finals AS (
                    SELECT DISTINCT ON (ticker)
                        ticker, yes_bid AS final_bid, yes_ask AS final_ask
                    FROM market_snapshots
                    WHERE ticker LIKE %s
                      AND NOT (yes_bid = 0 AND yes_ask = 100 AND no_bid = 0 AND no_ask = 100)
                    ORDER BY ticker, scanned_at DESC
                )
                SELECT f.ticker, f.final_bid, f.final_ask, ms.result AS official
                FROM finals f
                LEFT JOIN market_settlements ms ON ms.ticker = f.ticker
            """, [series_like])
            for r in cur.fetchall():
                official = r["official"]
                if official in ("yes", "no"):
                    resolved[r["ticker"]] = official
                else:
                    ref = r["final_bid"] if r["final_bid"] is not None else r["final_ask"]
                    if ref is not None:
                        resolved[r["ticker"]] = "yes" if float(ref) >= 50 else "no"

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
                t = _bt_simulate_rule(cur, series_like, rule, side, snap_table, tickers=tickers)
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

    # Feed rows: every execution, plus a row for each scoped market that didn't
    # trade — "bad_data" if it was excluded for poor coverage, else "skipped".
    # Sorted newest-first (non-fill rows fall back to the market's last-seen time).
    feed = list(all_trades)
    if market_limit and scoped:
        filled = {t["ticker"] for t in all_trades}
        for tk in scoped:
            if tk in filled:
                continue
            q = quality.get(tk, {})
            if q.get("bad"):
                feed.append({
                    "ticker": tk, "side": resolved.get(tk), "fill_time": None, "fill_price": None,
                    "ttc_at_fill": None, "exit_kind": None, "exit_price": None,
                    "exit_time": None, "pnl_cents": None, "qty": 1, "outcome": "bad_data",
                    "reason": q.get("reason"), "event_time": ticker_meta.get(tk),
                })
            else:
                feed.append({
                    "ticker": tk, "side": resolved.get(tk), "fill_time": None, "fill_price": None,
                    "ttc_at_fill": None, "exit_kind": None, "exit_price": None,
                    "exit_time": None, "pnl_cents": None, "qty": 1, "outcome": "skipped",
                    "event_time": ticker_meta.get(tk),
                })
    feed.sort(key=lambda t: t.get("fill_time") or t.get("event_time") or "", reverse=True)

    excluded = sum(1 for q in quality.values() if q["bad"])
    return jsonify({
        "summary": _bt_aggregate(all_trades),
        "rules":   rule_results,
        "trades":  feed,
        "excluded_markets": excluded,
        "data_quality": {"max_gap_secs": max_gap_secs, "min_snaps": min_snaps},
    })
