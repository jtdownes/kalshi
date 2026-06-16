"""Reconcile live vs simulation strike_crossings on every historical rule-driven
order.

For each order whose strategy rule has a strike_crossings condition, recompute the
count two ways AT the order's placement time:

  A_old : the OLD live method -- Python count over a trailing `now - age` window
          (age = MARKET_DURATION - time_to_close), skipping ticks exactly at the
          strike. This is what live actually did when the order was placed.
  B_new : the backtest / new-live method -- running count from the market's first
          snapshot, `px > strike` equality, via SQL. This is what the simulator
          computed (and what live now computes after the fix).

Flags every order where the two counts differ, and -- more importantly -- every
order whose PASS/FAIL decision against the rule's threshold flips between the two.
A flip means the trade was a false entry: live took it, the sim would not have.

Run:  docker exec kalshi-api python /app/../data/queries/strike_crossings_reconcile.py
(or from the app dir with PYTHONPATH=/app)
"""
import os
import sys
import json

import psycopg2
import psycopg2.extras

sys.path.insert(0, "/app")
import crypto_assets  # noqa: E402

MARKET_DURATION = int(os.environ.get("MARKET_DURATION_SECONDS", "900"))

conn = psycopg2.connect(os.environ["DB_URL"])
conn.autocommit = True


def _cur():
    return conn.cursor(cursor_factory=psycopg2.extras.DictCursor)


def rule_crossing_cond(rules, rule_id):
    """Return (op, value) of the strike_crossings condition in this rule, or None."""
    for r in (rules or []):
        if str(r.get("id")) != str(rule_id):
            continue
        for c in (r.get("conditions") or []):
            if c.get("field") == "strike_crossings":
                try:
                    return c.get("op"), float(c.get("value"))
                except (TypeError, ValueError):
                    return None
    return None


def cond_pass(lhs, op, rhs):
    if lhs is None:
        return False
    return {
        "lt": lhs < rhs, "lte": lhs <= rhs, "gt": lhs > rhs,
        "gte": lhs >= rhs, "eq": lhs == rhs,
    }.get(op, False)


def b_new(ticker, table, placed_at):
    """Backtest-definition running count up to placed_at."""
    q = f"""
        SELECT COALESCE(SUM(cross_flag), 0) AS c FROM (
          SELECT CASE WHEN above_int <> lag(above_int)
                              OVER (ORDER BY scanned_at::timestamp)
                      THEN 1 ELSE 0 END AS cross_flag
          FROM (
            SELECT m.scanned_at,
                   CASE WHEN COALESCE(b.consolidated_price, b.coinbase_price)
                             > NULLIF(m.strike_str, '')::numeric
                        THEN 1 ELSE 0 END AS above_int
            FROM market_snapshots m
            LEFT JOIN {table} b ON b.scanned_at = m.scanned_at
            WHERE m.ticker = %s
              AND COALESCE(b.consolidated_price, b.coinbase_price) IS NOT NULL
              AND m.scanned_at::timestamp <= %s
          ) z
        ) zz
    """
    with _cur() as cur:
        cur.execute(q, (ticker, placed_at))
        row = cur.fetchone()
    return int(row["c"]) if row and row["c"] is not None else 0


def a_old(ticker, table, placed_at, ttc):
    """Old-live count: trailing now-age window, Python skip-equal."""
    if ttc is None:
        age = MARKET_DURATION
    else:
        age = MARKET_DURATION - int(ttc)
    age = max(2, min(age, MARKET_DURATION))
    # strike for this market
    with _cur() as cur:
        cur.execute(
            "SELECT NULLIF(strike_str,'')::numeric AS s FROM market_snapshots "
            "WHERE ticker=%s AND NULLIF(strike_str,'') IS NOT NULL LIMIT 1",
            (ticker,))
        srow = cur.fetchone()
        if not srow or srow["s"] is None:
            return None
        strike = float(srow["s"])
        cur.execute(
            f"SELECT COALESCE(consolidated_price, coinbase_price) AS p FROM {table} "
            "WHERE scanned_at::timestamp >= (%s::timestamp - (%s || ' seconds')::interval) "
            "AND scanned_at::timestamp <= %s ORDER BY scanned_at::timestamp",
            (placed_at, str(age), placed_at))
        series = [float(r["p"]) for r in cur.fetchall() if r["p"] is not None]
    if len(series) < 2:
        return None
    crossings, prev = 0, None
    for p in series:
        d = p - strike
        if d == 0:
            continue
        sign = d > 0
        if prev is not None and sign != prev:
            crossings += 1
        prev = sign
    return crossings


def main():
    with _cur() as cur:
        cur.execute("""
            SELECT o.market_ticker, o.placed_at, o.time_to_close_at_placement AS ttc,
                   o.entry_rule_id, o.outcome, o.net_profit_cents, p.rules
            FROM orders o JOIN profiles p ON p.id = o.profile_id
            WHERE o.entry_rule_id IS NOT NULL AND o.placed_at IS NOT NULL
            ORDER BY o.placed_at
        """)
        orders = cur.fetchall()

    considered = mismatch = flips = 0
    flip_pnl = 0
    flip_rows = []
    for o in orders:
        rules = o["rules"]
        if isinstance(rules, str):
            rules = json.loads(rules)
        cond = rule_crossing_cond(rules, o["entry_rule_id"])
        if not cond:
            continue
        op, rhs = cond
        tk = o["market_ticker"]
        asset = crypto_assets.detect_asset(tk) or crypto_assets.DEFAULT_ASSET
        table = crypto_assets.CRYPTO_ASSETS[asset]["snapshot_table"]
        a = a_old(tk, table, o["placed_at"], o["ttc"])
        b = b_new(tk, table, o["placed_at"])
        considered += 1
        if a != b:
            mismatch += 1
        pa, pb = cond_pass(a, op, rhs), cond_pass(b, op, rhs)
        if pa != pb:
            flips += 1
            pnl = o["net_profit_cents"] or 0
            flip_pnl += pnl
            flip_rows.append((tk, op, rhs, a, b, o["outcome"], pnl))

    print("=" * 78)
    print(f"orders with a strike_crossings condition : {considered}")
    print(f"count differs (A_old != B_new)           : {mismatch}")
    print(f"DECISION FLIPS (live took, sim rejects)   : {flips}")
    print(f"net P&L of flipped trades                 : {flip_pnl/100:+.2f} USD")
    print("=" * 78)
    if flip_rows:
        print(f"{'ticker':32} {'cond':>10} {'A':>3} {'B':>3} {'outcome':>8} {'pnl¢':>7}")
        for tk, op, rhs, a, b, out, pnl in flip_rows:
            print(f"{tk:32} {op+' '+str(rhs):>10} {a:>3} {b:>3} {str(out):>8} {pnl:>7}")


if __name__ == "__main__":
    main()
