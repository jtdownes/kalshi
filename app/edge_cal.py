#!/usr/bin/env python3
"""Calibration-only edge test: does buying at price P win P% of the time?"""
import os, math, sys
from collections import defaultdict
import psycopg2, psycopg2.extras
DB = os.environ["DB_URL"]
def fee(p):
    p=float(p)
    return 0 if p<=0 or p>=100 else math.ceil(0.07*p*(100-p)/100.0)
def out(*a): print(*a); sys.stdout.flush()

out("loading...")
conn=psycopg2.connect(DB); cur=conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
cur.execute("""
  SELECT m.ticker, m.scanned_at, m.time_to_close_secs AS ttc,
         m.yes_ask, m.yes_bid, m.no_ask, m.no_bid,
         NULLIF(m.strike_str,'')::numeric AS strike,
         COALESCE(b.consolidated_price,b.coinbase_price) AS btc
  FROM market_snapshots m
  LEFT JOIN bitcoin_snapshots b ON b.scanned_at=m.scanned_at
  WHERE m.ticker LIKE 'KXBTC15M-%' AND m.yes_ask IS NOT NULL
  ORDER BY m.ticker, m.scanned_at
""")
by=defaultdict(list)
for r in cur.fetchall(): by[r["ticker"]].append(dict(r))
cur.close(); conn.close()

windows={}
for tk,ticks in by.items():
    last=ticks[-1]
    if last["ttc"] is None or last["ttc"]>=20: continue
    ref=last["yes_bid"] if last["yes_bid"] is not None else last["yes_ask"]
    yw=1 if (ref is not None and float(ref)>=50) else 0
    ttc=[t["ttc"] for t in ticks]; btc=[t["btc"] for t in ticks]
    for t in ticks:
        t["dist"]=(float(t["btc"])-float(t["strike"])) if (t["btc"] is not None and t["strike"] is not None) else None
    # trailing momentum over N sec
    def mom(N):
        o=[None]*len(ticks); j=0
        for i in range(len(ticks)):
            if ttc[i] is None: continue
            while j<i and (ttc[j] is None or ttc[j]-ttc[i]>N): j+=1
            k=j-1
            if k>=0 and ttc[k] is not None and btc[k] is not None and btc[i] is not None and (ttc[k]-ttc[i])>=N*0.5:
                o[i]=float(btc[i])-float(btc[k])
        return o
    m60,m180=mom(60),mom(180)
    for i,t in enumerate(ticks): t["m60"],t["m180"]=m60[i],m180[i]
    windows[tk]={"ticks":ticks,"yw":yw,"day":ticks[0]["scanned_at"][:10]}

days=sorted({w["day"] for w in windows.values()})
out(f"settled windows={len(windows)}  days={len(days)} ({days[0]}..{days[-1]})")
out(f"base YES-settle rate: {100*sum(w['yw'] for w in windows.values())/len(windows):.1f}%")

def at_h(ticks,H,tol=6):
    best=None;bd=1e9
    for t in ticks:
        if t["ttc"] is None: continue
        d=abs(t["ttc"]-H)
        if d<bd: bd=d;best=t
    return best if bd<=tol else None

def calib(side,H,mk=None,md=None,ds=None):
    ak="yes_ask" if side=="yes" else "no_ask"
    b=defaultdict(lambda:[0,0,0.0])
    for w in windows.values():
        t=at_h(w["ticks"],H)
        if not t: continue
        a=t[ak]
        if a is None or a<=0 or a>=100: continue
        if mk is not None:
            mv=t[mk]
            if mv is None: continue
            if md=="up" and mv<=0: continue
            if md=="dn" and mv>=0: continue
        if ds is not None:
            d=t["dist"]
            if d is None: continue
            if ds=="+" and d<=0: continue
            if ds=="-" and d>=0: continue
        won=w["yw"] if side=="yes" else (1-w["yw"])
        bk=int(a//5)*5
        b[bk][0]+=1;b[bk][1]+=won;b[bk][2]+=a
    return b

def show(title,b):
    out(f"\n--- {title} ---")
    out(f"  {'price':>7} {'n':>4} {'win%':>6} {'edge':>7} {'net¢/ct':>8}")
    tn=0
    for bk in sorted(b):
        n,wins,sp=b[bk]
        if n<8: continue
        tn+=n; wr=100*wins/n; mp=sp/n; net=wr-mp-fee(mp)
        flag=" <<< EDGE" if (net>0.5 and n>=15) else ""
        out(f"  {bk:>3}-{bk+5:<3} {n:>4} {wr:>5.1f}% {wr-mp:>+6.1f} {net:>+7.1f}{flag}")
    out(f"  (obs {tn})")

for H in (300,120,60,30):
    out(f"\n############ CALIBRATION @ ~{H}s to close ############")
    show(f"YES buy@ask H={H}", calib("yes",H))
    show(f"NO  buy@ask H={H}", calib("no",H))

out(f"\n############ MOMENTUM-CONDITIONED @120s ############")
show("YES m180>0",          calib("yes",120,"m180","up"))
show("YES m180>0 & dist>0", calib("yes",120,"m180","up",None) )
show("YES m180>0 & dist>0*",calib("yes",120,"m180","up","+"))
show("NO  m180<0",          calib("no",120,"m180","dn"))
show("NO  m180<0 & dist<0", calib("no",120,"m180","dn","-"))
show("YES m60>0 & dist>0",  calib("yes",60,"m60","up","+"))
show("NO  m60<0 & dist<0",  calib("no",60,"m60","dn","-"))
out("\nCAL_DONE")
