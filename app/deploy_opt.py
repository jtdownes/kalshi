#!/usr/bin/env python3
"""Optimize the deployable deep-ITM favorite play (YES if dist>D, NO if dist<-D)."""
import os, math, sys
from collections import defaultdict
import psycopg2, psycopg2.extras
DB=os.environ["DB_URL"]
def fee(p):
    p=float(p); return 0 if p<=0 or p>=100 else math.ceil(0.07*p*(100-p)/100.0)
def out(*a): print(*a); sys.stdout.flush()

out("loading...")
conn=psycopg2.connect(DB); cur=conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
cur.execute("""
  SELECT m.ticker,m.scanned_at,m.time_to_close_secs AS ttc,m.yes_ask,m.yes_bid,m.no_ask,m.no_bid,
         NULLIF(m.strike_str,'')::numeric AS strike, COALESCE(b.consolidated_price,b.coinbase_price) AS btc
  FROM market_snapshots m LEFT JOIN bitcoin_snapshots b ON b.scanned_at=m.scanned_at
  WHERE m.ticker LIKE 'KXBTC15M-%' AND m.yes_ask IS NOT NULL
  ORDER BY m.ticker,m.scanned_at""")
by=defaultdict(list)
for r in cur.fetchall(): by[r["ticker"]].append(dict(r))
cur.execute("SELECT ticker,result FROM market_settlements")
OFFICIAL={tk:res for tk,res in cur.fetchall()}
cur.close(); conn.close()
out(f"official settlements on file: {len(OFFICIAL)}")

W={}
for tk,ticks in by.items():
    last=ticks[-1]
    if last["ttc"] is None or last["ttc"]>=20: continue
    off=OFFICIAL.get(tk)
    if off in ("yes","no"):
        yw=1 if off=="yes" else 0
    else:
        ref=last["yes_bid"] if last["yes_bid"] is not None else last["yes_ask"]
        yw=1 if (ref is not None and float(ref)>=50) else 0
    comp=[]
    for t in ticks:
        if t["ttc"] is None: continue
        dist=(float(t["btc"])-float(t["strike"])) if (t["btc"] is not None and t["strike"] is not None) else None
        comp.append((t["ttc"],t["yes_ask"],t["no_ask"],dist))
    W[tk]={"c":comp,"yw":yw,"day":ticks[0]["scanned_at"][:10]}
days=sorted({w["day"] for w in W.values()}); mid=days[len(days)//2]
out(f"windows={len(W)} days={len(days)} split@{mid}")

def first_entry(w,side,D,tl,th,cap):
    for (ttc,ya,na,dist) in w["c"]:
        if dist is None or not(tl<=ttc<=th): continue
        if side=="yes":
            if dist<=D: continue
            a=ya
        else:
            if dist>=-D: continue
            a=na
        if a is None or a<=0 or a>=100 or a>=cap: continue
        won=w["yw"] if side=="yes" else (1-w["yw"])
        return ((100 if won else 0)-a-fee(a), won, w["day"], a)
    return None

def evalcfg(D,tl,th,cap):
    tr=[]
    for w in W.values():
        for side in ("yes","no"):
            e=first_entry(w,side,D,tl,th,cap)
            if e: tr.append(e)
    n=len(tr)
    if n<30: return None
    pn=[x[0] for x in tr]; m=sum(pn)/n; tot=sum(pn)
    wr=100*sum(x[1] for x in tr)/n; cost=sum(x[3]+fee(x[3]) for x in tr)
    h1=[x[0] for x in tr if x[2]<=mid]; h2=[x[0] for x in tr if x[2]>mid]
    h1m=sum(h1)/len(h1) if h1 else 0; h2m=sum(h2)/len(h2) if h2 else 0
    bd=defaultdict(list)
    for x in tr: bd[x[2]].append(x[0])
    dpos=sum(1 for d in bd if sum(bd[d])>0)
    roi=100*tot/cost if cost else 0
    return dict(D=D,tl=tl,th=th,cap=cap,n=n,wr=wr,mean=m,tot=tot,roi=roi,h1=h1m,h2=h2m,dpos=dpos,dt=len(bd),loss=n-int(round(n*wr/100)))

res=[]
for D in (100,150,200,250,300):
  for tl,th in ((30,540),(30,300),(120,540),(30,900),(60,420)):
    for cap in (90,93,95,97,99,100):
        r=evalcfg(D,tl,th,cap)
        if r: res.append(r)

def show(title,key):
    out(f"\n===== {title} =====")
    out(f"{'D':>4} {'ttc':>9} {'cap':>4} | {'n':>4} {'L':>3} {'win%':>5} {'mean':>6} {'ROI%':>6} {'TOTAL$':>7} {'H1':>6} {'H2':>6} {'days+':>6}")
    for r in sorted(res,key=key,reverse=True)[:12]:
        rob="*" if (r['h1']>0 and r['h2']>0) else " "
        out(f"{r['D']:>4} {r['tl']:>3}-{r['th']:<4} {r['cap']:>4} | {r['n']:>4} {r['loss']:>3} {r['wr']:>4.0f}% {r['mean']:>+5.1f}c {r['roi']:>+5.1f}% {r['tot']/100:>+6.2f}$ {r['h1']:>+5.1f} {r['h2']:>+5.1f} {r['dpos']:>3}/{r['dt']:<2}{rob}")

show("RANKED BY TOTAL $", lambda r:r['tot'])
show("RANKED BY PER-TRADE EV (mean¢)", lambda r:r['mean'])
show("RANKED BY ROI%", lambda r:r['roi'])
out("\nOPT_DONE")
