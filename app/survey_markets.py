#!/usr/bin/env python3
"""Survey ALL open Kalshi markets, group by series, and rank by inefficiency:
wide spread (room to profit / less HFT) but enough volume to actually trade.
This is where a retail edge can live — unlike the HFT-saturated BTC 15-min book."""
import sys, statistics
from collections import defaultdict
from kalshi_client import KalshiClient
def out(*a): print(*a); sys.stdout.flush()

c=KalshiClient()
agg=defaultdict(lambda: {"n":0,"spreads":[],"vols":[],"oi":[],"prices":[]})
cursor=None; pages=0; total=0
while True:
    r=c.get_markets(status="open", limit=1000, cursor=cursor)
    ms=r.get("markets",[]) or []
    for m in ms:
        tk=m.get("ticker","")
        series=tk.split("-")[0] if "-" in tk else tk
        ya=m.get("yes_ask"); yb=m.get("yes_bid")
        vol=m.get("volume") or 0; oi=m.get("open_interest") or 0
        a=agg[series]; a["n"]+=1; a["vols"].append(vol); a["oi"].append(oi)
        if ya and yb and 0<yb<=ya<=100:
            a["spreads"].append(ya-yb); a["prices"].append((ya+yb)/2)
    total+=len(ms); pages+=1; cursor=r.get("cursor")
    out(f"  page {pages}: +{len(ms)} (total {total})")
    if not cursor or not ms: break

rows=[]
for s,a in agg.items():
    if a["n"]<5 or not a["spreads"]: continue
    medspread=statistics.median(a["spreads"])
    totvol=sum(a["vols"]); medvol=statistics.median(a["vols"])
    medoi=statistics.median(a["oi"])
    # tradeable = some volume; inefficient = wide spread. score favors both.
    rows.append((s,a["n"],medspread,medvol,totvol,medoi))

out(f"\n{total} open markets across {len(rows)} series with quotes\n")
out(f"{'series':<14} {'#mkts':>5} {'medSpread':>9} {'medVol':>8} {'totVol':>10} {'medOI':>8}")
out("-"*64)
# show widest-spread series that still have meaningful volume
cand=[r for r in rows if r[3]>=20]          # median volume >= 20 contracts (tradeable)
cand.sort(key=lambda r:r[2], reverse=True)   # widest spread first
for s,n,ms_,mv,tv,moi in cand[:30]:
    out(f"{s:<14} {n:>5} {ms_:>7.1f}c {mv:>8.0f} {tv:>10.0f} {moi:>8.0f}")
out("\n-- highest-volume series (most liquid / where the action is) --")
rows.sort(key=lambda r:r[4], reverse=True)
for s,n,ms_,mv,tv,moi in rows[:15]:
    out(f"{s:<14} {n:>5} {ms_:>7.1f}c {mv:>8.0f} {tv:>10.0f} {moi:>8.0f}")
out("\nSURVEY_DONE")
