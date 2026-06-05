#!/usr/bin/env python3
"""Final-seconds convergence edge: in the last T seconds, if BTC is clearly on one
side of the strike (|distance|>=safety), the outcome is near-certain and the fee up
there is ~1c. If the market price hasn't fully converged to 100, buy the sure side
cheap. Measure realized EV on OFFICIAL settlement, both halves + per-day robustness."""
import os, math, sys
from collections import defaultdict
import psycopg2, psycopg2.extras
DB=os.environ["DB_URL"]
def fee(p): p=float(p); return 0 if p<=0 or p>=100 else math.ceil(0.07*p*(100-p)/100.0)
def out(*a): print(*a); sys.stdout.flush()

out("loading...")
conn=psycopg2.connect(DB); cur=conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
cur.execute("""
  SELECT m.ticker,m.scanned_at,m.time_to_close_secs AS ttc,m.yes_ask,m.no_ask,
         COALESCE(s.floor_strike,NULLIF(m.strike_str,'')::numeric) AS strike,
         COALESCE(b.consolidated_price,b.coinbase_price) AS btc, s.result AS official
  FROM market_snapshots m
  LEFT JOIN bitcoin_snapshots b ON b.scanned_at=m.scanned_at
  LEFT JOIN market_settlements s ON s.ticker=m.ticker
  WHERE m.ticker LIKE 'KXBTC15M-%' AND m.yes_ask IS NOT NULL
  ORDER BY m.ticker,m.scanned_at""")
by=defaultdict(list)
for r in cur.fetchall(): by[r["ticker"]].append(dict(r))
cur.close(); conn.close()

W={}
for tk,ticks in by.items():
    off=ticks[-1]["official"]
    if off not in ("yes","no"): continue
    seq=[t for t in ticks if t["ttc"] is not None and t["btc"] is not None and t["strike"] is not None]
    if seq: W[tk]={"t":seq,"yw":1 if off=="yes" else 0,"day":seq[0]["scanned_at"][:10]}
days=sorted({w["day"] for w in W.values()}); mid=days[len(days)//2]
out(f"windows={len(W)} days={len(days)}")

def run(tmax, tmin, safety, cap):
    tr=[]
    for w in W.values():
        for t in w["t"]:
            ttc=t["ttc"]
            if not(tmin<=ttc<=tmax): continue
            d=float(t["btc"])-float(t["strike"])
            if abs(d)<safety: continue
            side="yes" if d>0 else "no"
            a=t["yes_ask"] if side=="yes" else t["no_ask"]
            if a is None or a<=0 or a>=100 or a>cap: continue
            won = w["yw"] if side=="yes" else (1-w["yw"])
            tr.append(((100 if won else 0)-a-fee(a), w["day"], a, won))
            break
    n=len(tr)
    if n<25: return None
    pn=[x[0] for x in tr]; m=sum(pn)/n; tot=sum(pn)
    wr=100*sum(x[3] for x in tr)/n
    h1=[x[0] for x in tr if x[1]<=mid]; h2=[x[0] for x in tr if x[1]>mid]
    h1m=sum(h1)/len(h1) if h1 else 0; h2m=sum(h2)/len(h2) if h2 else 0
    cost=sum(x[2]+fee(x[2]) for x in tr)
    bd=defaultdict(float)
    for x in tr: bd[x[1]]+=x[0]
    dpos=sum(1 for d in bd if bd[d]>0)
    avgfill=sum(x[2] for x in tr)/n
    return dict(tmax=tmax,tmin=tmin,safety=safety,cap=cap,n=n,wr=wr,m=m,tot=tot,
                roi=100*tot/cost if cost else 0,h1=h1m,h2=h2m,dpos=dpos,dt=len(bd),af=avgfill)

out(f"\n{'tmax':>4} {'tmin':>4} {'safe':>4} {'cap':>3} | {'n':>4} {'win%':>5} {'avgFill':>7} {'mean':>6} {'ROI%':>6} {'TOT$':>7} {'H1':>5} {'H2':>5} {'days+':>5}")
res=[]
for tmax in (10,20,30,60,120):
  for tmin in (2,):
    for safety in (50,100,150,250):
      for cap in (98,99):
        r=run(tmax,tmin,safety,cap)
        if r: res.append(r)
res.sort(key=lambda r:r['tot'],reverse=True)
for r in res[:24]:
    rob="*" if (r['h1']>0 and r['h2']>0 and r['dpos']>=max(4,int(0.6*r['dt']))) else " "
    out(f"{r['tmax']:>4} {r['tmin']:>4} {r['safety']:>4} {r['cap']:>3} | {r['n']:>4} {r['wr']:>4.0f}% {r['af']:>6.1f}c {r['m']:>+5.1f}c {r['roi']:>+5.1f}% {r['tot']/100:>+6.2f}${rob} {r['h1']:>+4.1f} {r['h2']:>+4.1f} {r['dpos']:>2}/{r['dt']:<2}")
out("\nLATE_DONE")
