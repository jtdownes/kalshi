#!/usr/bin/env python3
"""
Reusable scalp backtester for KXBTC15M (and any series) snapshot history.

WHY THIS EXISTS
---------------
Naive backtests over 1-second tick data lie, because one 15-minute window sits in
the same price bucket for dozens of consecutive ticks. Counting ticks as
independent trades inflated a noise cell ("YES @ 43c") to a fake +10c/contract.
This harness enforces the honest accounting:

  * ONE trade per window (first qualifying entry), so N = independent windows.
  * Settlement taken from the market's OWN terminal verdict (last tick yes>=50),
    NOT our consolidated BTC price (which disagrees with Kalshi's settlement
    index ~1/3 of the time near-the-money and silently flips outcomes).
  * Realistic fills: enter as a taker (pay the ask). Exit is a RESTING LIMIT that
    only fills when the *bid* on our side reaches the target. Stops cross the
    spread (sell at the bid). Unfilled at the cutoff -> hold to settlement.
  * Kalshi fees charged on every execution: ceil(0.07 * p * (1-p)) cents.
  * Regime split (FLAT 05-28..05-31 vs the 06-01/02 crash) + standard error,
    because an "edge" that flips sign across regimes is just noise.

USAGE
  python /app/backtest_scalp.py                 # default: scalp the user's 82-88c / 2-4min idea
  python /app/backtest_scalp.py --side no --entry-lo 80 --entry-hi 85 --target 4 --stop 6
  python /app/backtest_scalp.py --sweep         # grid-sweep entry bands x targets, print leaderboard

All knobs are CLI flags; see --help. Read-only against the DB.
"""

import os
import sys
import math
import argparse
from collections import defaultdict
from datetime import datetime

import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DB_URL") or "postgresql://admin:r7cLy3F0A2VzPL@192.168.1.10:5433/a-kalshi"


def fee_cents(price):
    """Kalshi trading fee for 1 contract at `price` cents: ceil(0.07 * p * (1-p))."""
    if price <= 0 or price >= 100:
        return 0
    return math.ceil(0.07 * price * (100 - price) / 100.0)


def regime_of(dt_str):
    """FLAT = the choppy/sideways window 05-28..05-31; CRASH = the 06-01/02 selloff."""
    d = dt_str[:10]
    return "FLAT" if "2026-05-28" <= d <= "2026-05-31" else "CRASH"


def load_windows(series_prefix):
    """
    Returns {ticker: {"ticks": [...sorted by scanned_at...], "yes_win": 0/1, "regime": str}}
    Only windows we tracked to the bell (last tick within 20s of close) get a verdict.
    """
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(
        """
        SELECT ticker, scanned_at, time_to_close_secs AS ttc,
               yes_ask, yes_bid, no_ask, no_bid
        FROM market_snapshots
        WHERE ticker LIKE %s AND yes_ask IS NOT NULL
        ORDER BY ticker, scanned_at
        """,
        (series_prefix + "-%",),
    )
    by_ticker = defaultdict(list)
    for r in cur.fetchall():
        by_ticker[r["ticker"]].append(dict(r))
    cur.close()
    conn.close()

    windows = {}
    for ticker, ticks in by_ticker.items():
        last = ticks[-1]
        if last["ttc"] is None or last["ttc"] >= 20:
            continue  # never saw the close; can't settle honestly
        ref = last["yes_bid"] if last["yes_bid"] is not None else last["yes_ask"]
        yes_win = 1 if (ref is not None and ref >= 50) else 0
        windows[ticker] = {
            "ticks": ticks,
            "yes_win": yes_win,
            "regime": regime_of(ticks[0]["scanned_at"]),
        }
    return windows


def simulate(window, p):
    """
    Simulate ONE window under params p. Returns a trade dict or None (no entry).

    p keys: side('yes'|'no'), entry_lo, entry_hi, ttc_lo, ttc_hi,
            target(cents), stop(cents|None), exit_floor_ttc(int), settle_if_unfilled(bool)
    """
    side = p["side"]
    ask_k = "yes_ask" if side == "yes" else "no_ask"
    bid_k = "yes_bid" if side == "yes" else "no_bid"
    won_side = window["yes_win"] if side == "yes" else (1 - window["yes_win"])
    ticks = window["ticks"]

    # --- ENTRY: first tick inside the price band AND the time band (taker, pay ask) ---
    entry_i = None
    for i, t in enumerate(ticks):
        a = t[ask_k]
        if a is None or t["ttc"] is None:
            continue
        if p["ttc_lo"] <= t["ttc"] <= p["ttc_hi"] and p["entry_lo"] <= a <= p["entry_hi"]:
            entry_i = i
            break
    if entry_i is None:
        return None

    entry = ticks[entry_i]
    cost = entry[ask_k]
    target_price = cost + p["target"]
    stop_price = (cost - p["stop"]) if p["stop"] is not None else None

    # --- FORWARD WALK: resting limit-sell at target; stop crosses the spread ---
    for t in ticks[entry_i + 1:]:
        if t["ttc"] is None:
            continue
        bid = t[bid_k]
        # must be flat by the exit floor -> stop scanning for limit/stop fills
        if t["ttc"] <= p["exit_floor_ttc"]:
            break
        if bid is None:
            continue
        # target hit: our resting sell limit fills at target_price
        if bid >= target_price:
            pnl = target_price - cost - fee_cents(cost) - fee_cents(target_price)
            return {"regime": window["regime"], "outcome": "target", "pnl": pnl,
                    "cost": cost, "won_side": won_side}
        # stop hit: market-sell at the bid (cross the spread)
        if stop_price is not None and bid <= stop_price:
            pnl = bid - cost - fee_cents(cost) - fee_cents(bid)
            return {"regime": window["regime"], "outcome": "stop", "pnl": pnl,
                    "cost": cost, "won_side": won_side}

    # --- UNFILLED at the cutoff ---
    if p["settle_if_unfilled"]:
        payout = 100 if won_side else 0
        pnl = payout - cost - fee_cents(cost)  # settlement has no exit fee
        return {"regime": window["regime"], "outcome": "settle", "pnl": pnl,
                "cost": cost, "won_side": won_side}
    else:
        # market-exit at the last bid we saw before the floor
        last_bid = None
        for t in ticks[entry_i + 1:]:
            if t["ttc"] is not None and t["ttc"] > p["exit_floor_ttc"] and t[bid_k] is not None:
                last_bid = t[bid_k]
        if last_bid is None:
            return None
        pnl = last_bid - cost - fee_cents(cost) - fee_cents(last_bid)
        return {"regime": window["regime"], "outcome": "market", "pnl": pnl,
                "cost": cost, "won_side": won_side}


def run(windows, p, label=""):
    trades = [tr for tr in (simulate(w, p) for w in windows.values()) if tr is not None]
    if not trades:
        print(f"  {label}: no trades matched.")
        return None

    n = len(trades)
    pnls = [tr["pnl"] for tr in trades]
    total = sum(pnls)
    mean = total / n
    var = sum((x - mean) ** 2 for x in pnls) / n
    se = math.sqrt(var / n)
    by_outcome = defaultdict(int)
    for tr in trades:
        by_outcome[tr["outcome"]] += 1

    def regime_stats(rg):
        rp = [tr["pnl"] for tr in trades if tr["regime"] == rg]
        if not rp:
            return "    n/a"
        m = sum(rp) / len(rp)
        s = math.sqrt((sum((x - m) ** 2 for x in rp) / len(rp)) / len(rp))
        return f"n={len(rp):4d}  mean={m:+6.2f}c  ±{s:4.2f}"

    print(f"\n=== {label} ===")
    print(f"  trades(windows)={n}   total={total:+.0f}c (${total/100:+.2f})   "
          f"mean={mean:+.2f}c  ±{se:.2f}  t={mean/se if se else 0:+.2f}")
    print(f"  outcomes: " + "  ".join(f"{k}={v}" for k, v in sorted(by_outcome.items())))
    print(f"  FLAT : {regime_stats('FLAT')}")
    print(f"  CRASH: {regime_stats('CRASH')}")
    return {"n": n, "mean": mean, "se": se, "total": total}


def default_params(args):
    return {
        "side": args.side, "entry_lo": args.entry_lo, "entry_hi": args.entry_hi,
        "ttc_lo": args.ttc_lo, "ttc_hi": args.ttc_hi, "target": args.target,
        "stop": args.stop, "exit_floor_ttc": args.exit_floor,
        "settle_if_unfilled": not args.market_exit,
    }


def main():
    ap = argparse.ArgumentParser(description="Honest scalp backtester for KXBTC15M.")
    ap.add_argument("--series", default="KXBTC15M")
    ap.add_argument("--side", choices=["yes", "no"], default="no")
    ap.add_argument("--entry-lo", type=int, default=82, dest="entry_lo")
    ap.add_argument("--entry-hi", type=int, default=88, dest="entry_hi")
    ap.add_argument("--ttc-lo", type=int, default=120, dest="ttc_lo")
    ap.add_argument("--ttc-hi", type=int, default=240, dest="ttc_hi")
    ap.add_argument("--target", type=int, default=4, help="cents above entry to rest the sell limit")
    ap.add_argument("--stop", type=int, default=None, help="cents below entry to bail (default: none)")
    ap.add_argument("--exit-floor", type=int, default=10, dest="exit_floor",
                    help="must be flat by this many seconds to close")
    ap.add_argument("--market-exit", action="store_true",
                    help="if unfilled, market-sell at the last bid instead of holding to settlement")
    ap.add_argument("--sweep", action="store_true", help="grid-sweep entry bands x targets")
    args = ap.parse_args()

    print(f"Loading {args.series} windows from {DB_URL.split('@')[-1]} ...")
    windows = load_windows(args.series)
    print(f"Loaded {len(windows)} settled windows "
          f"(FLAT={sum(w['regime']=='FLAT' for w in windows.values())}, "
          f"CRASH={sum(w['regime']=='CRASH' for w in windows.values())})")

    if not args.sweep:
        p = default_params(args)
        run(windows, p, label=f"{args.side.upper()} entry {args.entry_lo}-{args.entry_hi}c "
                              f"ttc {args.ttc_lo}-{args.ttc_hi}s  target+{args.target} "
                              f"stop {args.stop}  exit@{args.exit_floor}s "
                              f"{'(settle)' if not args.market_exit else '(mkt-exit)'}")
        return

    # ---- SWEEP: scan the landscape, print a leaderboard sorted by t-stat ----
    print("\nSweeping entry bands x targets (one trade/window, fees in, regime-split)...")
    results = []
    for side in ("yes", "no"):
        for lo in range(2, 92, 6):
            hi = lo + 6
            for target in (2, 3, 4, 6, 8):
                for stop in (None, 6, 12):
                    p = {"side": side, "entry_lo": lo, "entry_hi": hi,
                         "ttc_lo": args.ttc_lo, "ttc_hi": args.ttc_hi, "target": target,
                         "stop": stop, "exit_floor_ttc": args.exit_floor,
                         "settle_if_unfilled": not args.market_exit}
                    trades = [tr for tr in (simulate(w, p) for w in windows.values()) if tr]
                    if len(trades) < 40:
                        continue
                    pnls = [tr["pnl"] for tr in trades]
                    n = len(pnls); m = sum(pnls) / n
                    se = math.sqrt((sum((x - m) ** 2 for x in pnls) / n) / n)
                    # regime means, to flag sign-flips
                    fm = [tr["pnl"] for tr in trades if tr["regime"] == "FLAT"]
                    cm = [tr["pnl"] for tr in trades if tr["regime"] == "CRASH"]
                    fmean = sum(fm) / len(fm) if fm else 0
                    cmean = sum(cm) / len(cm) if cm else 0
                    robust = "Y" if (fmean > 0 and cmean > 0) else ("y" if fmean * cmean > 0 else "-")
                    results.append((m / se if se else 0, m, se, n, side, lo, hi,
                                    target, stop, fmean, cmean, robust))

    results.sort(key=lambda r: r[0], reverse=True)
    print(f"\n{'t':>5} {'mean':>6} {'se':>5} {'n':>4}  side band   tgt stop  FLAT  CRASH  robust")
    print("-" * 74)
    for t, m, se, n, side, lo, hi, target, stop, fmean, cmean, robust in results[:25]:
        print(f"{t:+5.2f} {m:+6.2f} {se:5.2f} {n:4d}  {side:3s} {lo:2d}-{hi:2d} "
              f"+{target:<2d} {str(stop):>4}  {fmean:+5.1f} {cmean:+6.1f}   {robust}")
    print("\nReading it: t = mean/se (need ~>3 to believe, after remembering we tested",
          f"{len(results)} combos -> expect ~{len(results)//100} false +ve at t>2.3 by chance).")
    print("robust=Y means positive in BOTH regimes. Anything that flips sign is noise.")


if __name__ == "__main__":
    main()
