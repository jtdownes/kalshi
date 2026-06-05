#!/usr/bin/env python3
"""Backfill official Kalshi settlement results for every KXBTC15M window we have
snapshots for. Source of truth = market.result ('yes'/'no') from Kalshi, which is
the settlement index outcome — not our last-order-book-snapshot heuristic."""
import os, sys, time
import psycopg2
from kalshi_client import KalshiClient

DB = os.environ["DB_URL"]
def out(*a): print(*a); sys.stdout.flush()

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

# tickers we actually care about + bound the close-time window to our data range
cur.execute("""
  SELECT DISTINCT ticker FROM market_snapshots WHERE ticker LIKE 'KXBTC15M-%'
""")
want = {r[0] for r in cur.fetchall()}
cur.execute("SELECT MIN(close_time::bigint), MAX(close_time::bigint) FROM market_snapshots WHERE ticker LIKE 'KXBTC15M-%' AND close_time ~ '^[0-9]+$'")
min_ct, max_ct = cur.fetchone()
out(f"want {len(want)} tickers; close_ts range {min_ct}..{max_ct}")

c = KalshiClient()
now = time.strftime("%Y-%m-%dT%H:%M:%S")
found = {}
for status in ("settled",):
    cursor = None; pages = 0
    while True:
        r = c.get_markets(series_ticker="KXBTC15M", status=status, limit=1000,
                          cursor=cursor, min_close_ts=min_ct-60, max_close_ts=max_ct+60)
        ms = r.get("markets", []) or []
        for m in ms:
            tk = m.get("ticker"); res = m.get("result")
            if tk in want and res in ("yes", "no"):
                found[tk] = (res, m.get("close_time"), m.get("floor_strike"))
        pages += 1
        cursor = r.get("cursor")
        out(f"  status={status} page={pages} markets={len(ms)} matched_total={len(found)}")
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

# how often did our OLD heuristic disagree with official?
cur.execute("""
  WITH finals AS (
    SELECT DISTINCT ON (ticker) ticker,
           CASE WHEN COALESCE(yes_bid,yes_ask) >= 50 THEN 'yes' ELSE 'no' END AS heur
    FROM market_snapshots WHERE ticker LIKE 'KXBTC15M-%'
    ORDER BY ticker, scanned_at DESC
  )
  SELECT COUNT(*),
         SUM(CASE WHEN f.heur <> s.result THEN 1 ELSE 0 END)
  FROM finals f JOIN market_settlements s ON s.ticker=f.ticker
""")
tot, disagree = cur.fetchone()
out(f"\nHEURISTIC vs OFFICIAL: {disagree}/{tot} windows disagreed ({100*disagree/tot:.1f}%)")
out("DONE")
