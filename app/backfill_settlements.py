#!/usr/bin/env python3
"""Backfill official Kalshi settlement results for every crypto 15-min window we
have snapshots for (BTC/ETH/SOL — all series in crypto_assets). Source of truth =
market.result ('yes'/'no') from Kalshi, which is the settlement index outcome —
not our last-order-book-snapshot heuristic."""
import os, sys, time
import psycopg2
from kalshi_client import KalshiClient
from crypto_assets import TICKER_PREFIX_TO_ASSET

DB = os.environ["DB_URL"]
def out(*a): print(*a); sys.stdout.flush()

# Every tracked crypto 15-min series (KXBTC15M, KXETH15M, KXSOL15M, ...).
SERIES = [f"{prefix}15M" for prefix, _asset in TICKER_PREFIX_TO_ASSET]

conn = psycopg2.connect(DB); conn.autocommit = True
cur = conn.cursor()
cur.execute("""
  CREATE TABLE IF NOT EXISTS market_settlements (
    ticker      text PRIMARY KEY,
    result      text,
    close_time  text,
    floor_strike numeric,
    fetched_at  text
  )""")

c = KalshiClient()
now = time.strftime("%Y-%m-%dT%H:%M:%S")
found = {}
want = set()
for series in SERIES:
    like = f"{series}-%"
    # tickers we actually care about + bound the close-time window to our data range
    cur.execute("SELECT DISTINCT ticker FROM market_snapshots WHERE ticker LIKE %s", (like,))
    series_want = {r[0] for r in cur.fetchall()}
    if not series_want:
        out(f"{series}: no snapshots, skipping")
        continue
    want |= series_want
    cur.execute("SELECT MIN(close_time::bigint), MAX(close_time::bigint) FROM market_snapshots "
                "WHERE ticker LIKE %s AND close_time ~ '^[0-9]+$'", (like,))
    min_ct, max_ct = cur.fetchone()
    out(f"{series}: want {len(series_want)} tickers; close_ts range {min_ct}..{max_ct}")

    cursor = None; pages = 0
    while True:
        r = c.get_markets(series_ticker=series, status="settled", limit=1000,
                          cursor=cursor, min_close_ts=min_ct-60, max_close_ts=max_ct+60)
        ms = r.get("markets", []) or []
        for m in ms:
            tk = m.get("ticker"); res = m.get("result")
            if tk in series_want and res in ("yes", "no"):
                found[tk] = (res, m.get("close_time"), m.get("floor_strike"))
        pages += 1
        cursor = r.get("cursor")
        out(f"  {series} page={pages} markets={len(ms)} matched_total={len(found)}")
        if not cursor or not ms:
            break

# upsert
rows = [(tk, res, ct, fs, now) for tk, (res, ct, fs) in found.items()]
cur.executemany("""
  INSERT INTO market_settlements (ticker,result,close_time,floor_strike,fetched_at)
  VALUES (%s,%s,%s,%s,%s)
  ON CONFLICT (ticker) DO UPDATE SET
    result=EXCLUDED.result, close_time=EXCLUDED.close_time,
    floor_strike=EXCLUDED.floor_strike, fetched_at=EXCLUDED.fetched_at
""", rows)
out(f"upserted {len(rows)} settlements")
missing = want - set(found)
out(f"still missing official result for {len(missing)} of {len(want)} tickers")
if missing:
    out("  sample missing: " + ", ".join(list(missing)[:5]))

# how often did our OLD heuristic disagree with official? (across all tracked
# series; skip the close-time 0/100/0/100 no-book placeholder so the last real
# quote drives the heuristic — same exclusion the backtester now applies)
like_clauses = " OR ".join("ticker LIKE %s" for _ in SERIES)
cur.execute(f"""
  WITH finals AS (
    SELECT DISTINCT ON (ticker) ticker,
           CASE WHEN COALESCE(yes_bid,yes_ask) >= 50 THEN 'yes' ELSE 'no' END AS heur
    FROM market_snapshots
    WHERE ({like_clauses})
      AND NOT (yes_bid = 0 AND yes_ask = 100 AND no_bid = 0 AND no_ask = 100)
    ORDER BY ticker, scanned_at DESC
  )
  SELECT COUNT(*),
         SUM(CASE WHEN f.heur <> s.result THEN 1 ELSE 0 END)
  FROM finals f JOIN market_settlements s ON s.ticker=f.ticker
""", [f"{s}-%" for s in SERIES])
tot, disagree = cur.fetchone()
out(f"\nHEURISTIC vs OFFICIAL: {disagree}/{tot} windows disagreed ({100*disagree/tot:.1f}%)")
out("DONE")
