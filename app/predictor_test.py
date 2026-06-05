#!/usr/bin/env python3
"""Fair-value predictor edge test.

Idea: model P(BTC_close >= strike) as a random walk with empirically-measured
volatility, i.e. P = Phi( distance / (sigma_sec * sqrt(time_left)) ). Compare that
model price to Kalshi's ask. Bet ONLY where the model says the market is mispriced
(model_prob*100 - ask >= edge). If Kalshi is efficient, model ~= price and nothing
fires; if it lags BTC, we get a real, cheap-side edge. Settle on OFFICIAL result.
"""
import os, math, sys
from collections import defaultdict
from datetime import datetime
import psycopg2, psycopg2.extras
DB=os.environ["DB_URL"]
def fee(p):
    p=float(p); return 0 if p<=0 or p>=100 else math.ceil(0.07*p*(100-p)/100.0)
def out(*a): print(*a); sys.stdout.flush()
def Phi(x): return 0.5*(1.0+math.erf(x/math.sqrt(2.0)))
def ep(s):  # ISO -> epoch seconds
    try: return datetime.fromisoformat(s).timestamp()
    except Exception: return None

out("loading BTC series + estimating volatility...")
conn=psycopg2.connect(DB); cur=conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
cur.execute("SELECT scanned_at, COALESCE(consolidated_price,coinbase_price) AS px FROM bitcoin_snapshots WHERE COALESCE(consolidated_price,coinbase_price) IS NOT NULL ORDER BY scanned_at")
rows=cur.fetchall()
# diffusion var-per-second, estimated at a LONG horizon (~HORIZON s spacing) to
# strip 1-second microstructure noise that doesn't accumulate over 15 min.
def est_var_sec(horizon):
    num=den=0.0; ref=None
    for r in rows:
        t=ep(r["scanned_at"]); px=float(r["px"])
        if ref is None: ref=(t,px); continue
        dt=t-ref[0]
        if dt>=horizon:
            if dt<horizon*3:           # skip data gaps
                num+=(px-ref[1])**2; den+=dt
            ref=(t,px)
    return num/den if den else 0.0
for h in (1,15,60,180):
    vs=est_var_sec(h); out(f"  horizon={h:>3}s -> sigma_sec=${math.sqrt(vs):.2f}  sigma(15m)=${math.sqrt(vs*900):.0f}")
var_sec=est_var_sec(60)            # use the 60s-horizon estimate for the model
sig_sec=math.sqrt(var_sec)
out(f"USING sigma_sec=${sig_sec:.2f}/sqrt(s)  -> sigma(15m)=${sig_sec*math.sqrt(900):.0f}, sigma(5m)=${sig_sec*math.sqrt(300):.0f}, sigma(1m)=${sig_sec*math.sqrt(60):.0f}")

# market snapshots + official settlement + precise strike
cur.execute("""
  SELECT m.ticker, m.scanned_at, m.time_to_close_secs AS ttc, m.yes_ask, m.no_ask,
         COALESCE(s.floor_strike, NULLIF(m.strike_str,'')::numeric) AS strike,
         COALESCE(b.consolidated_price,b.coinbase_price) AS btc,
         s.result AS official
  FROM market_snapshots m
  LEFT JOIN bitcoin_snapshots b ON b.scanned_at=m.scanned_at
  LEFT JOIN market_settlements s ON s.ticker=m.ticker
  WHERE m.ticker LIKE 'KXBTC15M-%' AND m.yes_ask IS NOT NULL
  ORDER BY m.ticker, m.scanned_at
""")
by=defaultdict(list)
for r in cur.fetchall(): by[r["ticker"]].append(dict(r))
cur.close(); conn.close()

W={}
for tk,ticks in by.items():
    off=ticks[-1]["official"]
    if off not in ("yes","no"):
        last=ticks[-1]
        if last["ttc"] is None or last["ttc"]>=20: continue
    yw=1 if off=="yes" else 0 if off=="no" else None
    seq=[t for t in ticks if t["ttc"] is not None and t["btc"] is not None and t["strike"] is not None]
    if not seq or yw is None: continue
    W[tk]={"t":seq,"yw":yw,"day":seq[0]["scanned_at"][:10]}
days=sorted({w["day"] for w in W.values()}); mid=days[len(days)//2]
out(f"windows usable={len(W)} days={len(days)}")

def model_p(btc, strike, ttc):
    sd=sig_sec*math.sqrt(max(ttc,1))
    if sd<=0: return 1.0 if btc>=strike else 0.0
    return Phi((float(btc)-float(strike))/sd)

# ---- A) calibration: how does our model price compare to realized? (sanity) ----
out("\n--- MODEL CALIBRATION (does Phi predict settlement?) @120s ---")
buckets=defaultdict(lambda:[0,0])
for w in W.values():
    t=min(w["t"], key=lambda x:abs(x["ttc"]-120))
    if abs(t["ttc"]-120)>8: continue
    mp=model_p(t["btc"],t["strike"],t["ttc"])
    b=int(mp*100//10)*10
    buckets[b][0]+=1; buckets[b][1]+=w["yw"]
out(f"  {'modelP%':>8} {'n':>4} {'realYES%':>9}")
for b in sorted(buckets):
    n,wins=buckets[b]
    if n>=8: out(f"  {b:>3}-{b+10:<3} {n:>4} {100*wins/n:>8.1f}%")

# ---- B) edge backtest: bet only where model disagrees with the ask ----
def evalc(side, edge, tl, th, lo, hi):
    tr=[]
    for w in W.values():
        for t in w["t"]:
            ttc=t["ttc"]
            if not(tl<=ttc<=th): continue
            a = t["yes_ask"] if side=="yes" else t["no_ask"]
            if a is None or a<=0 or a>=100 or not(lo<=a<=hi): continue
            mp = model_p(t["btc"],t["strike"],ttc)
            mp = mp if side=="yes" else (1-mp)
            if mp*100 - a < edge: continue          # only when model says underpriced
            won = w["yw"] if side=="yes" else (1-w["yw"])
            tr.append(((100 if won else 0)-a-fee(a), w["day"], a, side))
            break                                    # one trade/window/side
    n=len(tr)
    if n<25: return None
    pn=[x[0] for x in tr]; m=sum(pn)/n; tot=sum(pn)
    h1=[x[0] for x in tr if x[1]<=mid]; h2=[x[0] for x in tr if x[1]>mid]
    h1m=sum(h1)/len(h1) if h1 else 0; h2m=sum(h2)/len(h2) if h2 else 0
    wr=100*sum(1 for x in tr if x[0]>0)/n
    cost=sum(x[2]+fee(x[2]) for x in tr)
    return dict(side=side,edge=edge,tl=tl,th=th,lo=lo,hi=hi,n=n,wr=wr,mean=m,tot=tot,
                roi=100*tot/cost if cost else 0,h1=h1m,h2=h2m)

out("\n--- EDGE BACKTEST: buy only when model_prob*100 - ask >= EDGE ---")
out(f"{'side':>4} {'edge':>4} {'band':>7} {'ttc':>8} | {'n':>4} {'win%':>5} {'mean':>6} {'ROI%':>6} {'TOT$':>7} {'H1':>6} {'H2':>6}")
res=[]
for side in ("yes","no"):
  for edge in (5,8,12,18):
    for tl,th in ((30,900),(30,300),(120,600),(300,900)):
      for lo,hi in ((2,97),(20,80),(40,70)):
        r=evalc(side,edge,tl,th,lo,hi)
        if r: res.append(r)
res.sort(key=lambda r:r['tot'],reverse=True)
for r in res[:20]:
    rob="*" if (r['h1']>0 and r['h2']>0) else " "
    out(f"{r['side']:>4} {r['edge']:>4} {r['lo']:>2}-{r['hi']:<2} {r['tl']:>3}-{r['th']:<3} | {r['n']:>4} {r['wr']:>4.0f}% {r['mean']:>+5.1f}c {r['roi']:>+5.1f}% {r['tot']/100:>+6.2f}${rob} {r['h1']:>+5.1f} {r['h2']:>+5.1f}")
# ---- C) validate the champion signal: plateau check + per-day ----
out("\n--- VALIDATION: YES, model-underpriced, sensitivity grid ---")
out(f"{'edge':>4} {'band':>7} {'ttc':>8} | {'n':>4} {'win%':>5} {'mean':>6} {'ROI%':>6} {'TOT$':>7} {'H1':>6} {'H2':>6} {'days+':>6}")
def detail(side,edge,tl,th,lo,hi):
    tr=[]
    for w in W.values():
        for t in w["t"]:
            ttc=t["ttc"]
            if not(tl<=ttc<=th): continue
            a=t["yes_ask"] if side=="yes" else t["no_ask"]
            if a is None or a<=0 or a>=100 or not(lo<=a<=hi): continue
            mp=model_p(t["btc"],t["strike"],ttc); mp=mp if side=="yes" else 1-mp
            if mp*100-a<edge: continue
            won=w["yw"] if side=="yes" else (1-w["yw"])
            tr.append(((100 if won else 0)-a-fee(a), w["day"]))
            break
    return tr
for edge in (3,5,8):
  for lo,hi in ((35,75),(40,70),(45,65)):
    for tl,th in ((30,300),(60,420)):
        tr=detail("yes",edge,tl,th,lo,hi)
        n=len(tr)
        if n<20: continue
        m=sum(x[0] for x in tr)/n; tot=sum(x[0] for x in tr)
        h1=[x[0] for x in tr if x[1]<=mid]; h2=[x[0] for x in tr if x[1]>mid]
        h1m=sum(h1)/len(h1) if h1 else 0; h2m=sum(h2)/len(h2) if h2 else 0
        wr=100*sum(1 for x in tr if x[0]>0)/n
        bd=defaultdict(list)
        for x in tr: bd[x[1]].append(x[0])
        dpos=sum(1 for d in bd if sum(bd[d])>0)
        out(f"{edge:>4} {lo:>2}-{hi:<2} {tl:>3}-{th:<3} | {n:>4} {wr:>4.0f}% {m:>+5.1f}c {100*tot/sum(x[0]+0 for x in tr) if False else 0:>+5.1f}% {tot/100:>+6.2f}$ {h1m:>+5.1f} {h2m:>+5.1f} {dpos:>3}/{len(bd):<2}")

out("\n--- champion per-day (edge5, 40-70, 30-300) ---")
tr=detail("yes",5,30,300,40,70)
bd=defaultdict(lambda:[0,0])
for pnl,day in tr: bd[day][0]+=1; bd[day][1]+=pnl
for d in sorted(bd): out(f"  {d}: n={bd[d][0]:>2}  pnl={bd[d][1]:+d}c")
out("\nPRED_DONE")
