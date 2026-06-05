#!/usr/bin/env python3
"""Fast one-trade-per-window sweep with regime-robustness gating (downsampled)."""
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
cur.close(); conn.close()

# Build compact, downsampled per-window arrays: (ttc, yes_ask, no_ask, dist, m180)
W={}
for tk,ticks in by.items():
    last=ticks[-1]
    if last["ttc"] is None or last["ttc"]>=20: continue
    ref=last["yes_bid"] if last["yes_bid"] is not None else last["yes_ask"]
    yw=1 if (ref is not None and float(ref)>=50) else 0
    ttc=[t["ttc"] for t in ticks]; btc=[t["btc"] for t in ticks]
    def mom(N):
        o=[None]*len(ticks); j=0
        for i in range(len(ticks)):
            if ttc[i] is None: continue
            while j<i and (ttc[j] is None or ttc[j]-ttc[i]>N): j+=1
            k=j-1
            if k>=0 and ttc[k] is not None and btc[k] is not None and btc[i] is not None and (ttc[k]-ttc[i])>=N*0.5:
                o[i]=float(btc[i])-float(btc[k])
        return o
    m180=mom(180)
    comp=[]; last_keep=10**9
    for i,t in enumerate(ticks):
        if t["ttc"] is None: continue
        if last_keep-t["ttc"]<8 and i!=0: continue   # ~1 sample / 8s
        last_keep=t["ttc"]
        dist=(float(t["btc"])-float(t["strike"])) if (t["btc"] is not None and t["strike"] is not None) else None
        comp.append((t["ttc"], t["yes_ask"], t["no_ask"], dist, m180[i]))
    W[tk]={"c":comp,"yw":yw,"day":ticks[0]["scanned_at"][:10]}

days=sorted({w["day"] for w in W.values()}); mid=days[len(days)//2]
out(f"windows={len(W)} days={len(days)} ({days[0]}..{days[-1]}) split@{mid}")

def sim(w,side,lo,hi,tl,th,dop,dv,md):
    for (ttc,ya,na,dist,m180) in w["c"]:
        a=ya if side=="yes" else na
        if a is None or a<=0 or a>=100: continue
        if not (tl<=ttc<=th and lo<=a<=hi): continue
        if dop=='>' and not (dist is not None and dist>dv): continue
        if dop=='<' and not (dist is not None and dist<dv): continue
        if md=='up' and not (m180 is not None and m180>0): continue
        if md=='dn' and not (m180 is not None and m180<0): continue
        won=w["yw"] if side=="yes" else (1-w["yw"])
        return ((100 if won else 0)-a-fee(a), won, w["day"])
    return None

bands=[(2,15),(15,30),(30,45),(45,60),(60,75),(75,88),(88,95),(2,97)]
ttcs=[(30,900),(30,180),(180,420),(420,900)]
dmap={"yes":[(None,0),('>',0),('>',200)],"no":[(None,0),('<',0),('<',-200)]}
moms=[None,'up','dn']
res=[]
for side in ("yes","no"):
  for lo,hi in bands:
    for tl,th in ttcs:
      for dop,dv in dmap[side]:
        for md in moms:
          tr=[sim(w,side,lo,hi,tl,th,dop,dv,md) for w in W.values()]
          tr=[x for x in tr if x]; n=len(tr)
          if n<30: continue
          pn=[x[0] for x in tr]; m=sum(pn)/n
          se=math.sqrt(sum((x-m)**2 for x in pn)/n/n) if n>1 else 0
          wr=100*sum(x[1] for x in tr)/n
          h1=[x[0] for x in tr if x[2]<=mid]; h2=[x[0] for x in tr if x[2]>mid]
          h1m=sum(h1)/len(h1) if h1 else 0; h2m=sum(h2)/len(h2) if h2 else 0
          bd=defaultdict(list)
          for x in tr: bd[x[2]].append(x[0])
          dpos=sum(1 for d in bd if sum(bd[d])>0)
          res.append((m/se if se else 0,m,n,wr,side,lo,hi,tl,th,dop,dv,md,h1m,h2m,dpos,len(bd)))
res.sort(key=lambda r:r[0],reverse=True)
out(f"\ncombos n>=30: {len(res)}")
out(f"{'t':>5} {'mean':>6} {'n':>4} {'win%':>5} side band   ttc      dist   mom  {'H1':>6} {'H2':>6} days+ ROBUST")
out("-"*104)
for r in res[:35]:
    (t,m,n,wr,side,lo,hi,tl,th,dop,dv,md,h1m,h2m,dpos,dt)=r
    dist=f"{dop}{dv}" if dop else "-"; mom=md or "-"
    rob="YES" if (h1m>0 and h2m>0 and dpos>=max(3,int(0.6*dt))) else ""
    out(f"{t:>+5.2f} {m:>+6.1f} {n:>4} {wr:>4.0f}% {side:<3} {lo:>2}-{hi:<2} {tl:>3}-{th:<3} {dist:>6} {mom:>4} {h1m:>+6.1f} {h2m:>+6.1f} {dpos:>2}/{dt:<2} {rob}")
out("\nSWEEP_DONE")
