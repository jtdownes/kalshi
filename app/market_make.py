#!/usr/bin/env python3
"""Market-MAKING backtest (we have only ever tested TAKING).

A maker rests a passive BID; it fills when a taker sells down to it (ask<=our bid).
Then we rest a passive OFFER at fill+T. Maker fees are ~1/4 of taker and round to
~0 at small size, so the fee wall that killed every taker strategy mostly vanishes.
The real risk a maker faces is ADVERSE SELECTION: your bid fills exactly when price
is dropping, and the unscratched inventory settles against you. This measures
whether the ~1c spread capture survives that, on OFFICIAL settlement.
"""
import os, math, sys
from collections import defaultdict
import psycopg2, psycopg2.extras
DB=os.environ["DB_URL"]
def takerfee(p): p=float(p); return 0 if p<=0 or p>=100 else math.ceil(0.07*p*(100-p)/100.0)
def makerfee(p, scale):   # scale=False -> tiny size (rounds to ~0); True -> per-contract at size
    p=float(p)
    if p<=0 or p>=100: return 0
    return round(0.0175*p*(100-p)/100.0) if scale else 0
def out(*a): print(*a); sys.stdout.flush()

out("loading...")
conn=psycopg2.connect(DB); cur=conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
cur.execute("""
  SELECT ticker,scanned_at,time_to_close_secs AS ttc,yes_ask,yes_bid,no_ask,no_bid
  FROM market_snapshots WHERE ticker LIKE 'KXBTC15M-%' AND yes_ask IS NOT NULL
  ORDER BY ticker,scanned_at""")
by=defaultdict(list)
for r in cur.fetchall(): by[r["ticker"]].append(dict(r))
cur.execute("SELECT ticker,result FROM market_settlements")
OFF={t:r for t,r in cur.fetchall()}
cur.close(); conn.close()

W={}
for tk,ticks in by.items():
    last=ticks[-1]
    if last["ttc"] is None or last["ttc"]>=20: continue
    off=OFF.get(tk)
    yw=1 if off=="yes" else 0 if off=="no" else (1 if (last["yes_bid"] or last["yes_ask"] or 0)>=50 else 0)
    seq=[t for t in ticks if t["ttc"] is not None]
    if seq: W[tk]={"t":seq,"yw":yw,"day":seq[0]["scanned_at"][:10]}
days=sorted({w["day"] for w in W.values()}); mid=days[len(days)//2]
out(f"windows={len(W)} days={len(days)}")

def mm(w, side, T, S, lo, hi, tl, th, scale):
    ak="yes_ask" if side=="yes" else "no_ask"; bk="yes_bid" if side=="yes" else "no_bid"
    seq=w["t"]; n=len(seq)
    # find first eligible tick; rest a BUY at its bid
    ei=None; restbid=None
    for i in range(n):
        b=seq[i][bk]; a=seq[i][ak]; ttc=seq[i]["ttc"]
        if b is None or a is None or not(0<b<a<100): continue
        if not(tl<=ttc<=th and lo<=b<=hi): continue
        ei=i; restbid=b; break
    if ei is None: return None
    # buy fills when a later ask trades down to our resting bid
    fi=None
    for i in range(ei+1, n):
        a=seq[i][ak]
        if a is not None and a<=restbid: fi=i; break
    if fi is None: return ("nofill", 0, w["day"])
    fill=restbid; target=fill+T; stop=(fill-S) if S else None
    fee_in=makerfee(fill, scale)
    # whichever comes first: scratch (rest offer at +T) or stop (cross out at bid)
    for i in range(fi+1, n):
        b=seq[i][bk]
        if b is None: continue
        if b>=target:
            return ("scratched", (target-fill-fee_in-makerfee(target,scale)), w["day"])
        if stop is not None and b<=stop:
            return ("stopped", (b-fill-fee_in-takerfee(b)), w["day"])   # bail, cross spread
    won = w["yw"] if side=="yes" else (1-w["yw"])
    return ("settled_"+("win" if won else "loss"), ((100 if won else 0)-fill-fee_in), w["day"])

def evalc(T, S, lo, hi, tl, th, scale):
    fills=[]; nofill=0
    for w in W.values():
        for side in ("yes","no"):
            r=mm(w,side,T,S,lo,hi,tl,th,scale)
            if r is None: continue
            if r[0]=="nofill": nofill+=1; continue
            fills.append(r)
    n=len(fills)
    if n<40: return None
    oc=defaultdict(int)
    for r in fills: oc[r[0]]+=1
    pn=[r[1] for r in fills]; m=sum(pn)/n; tot=sum(pn)
    h1=[r[1] for r in fills if r[2]<=mid]; h2=[r[1] for r in fills if r[2]>mid]
    h1m=sum(h1)/len(h1) if h1 else 0; h2m=sum(h2)/len(h2) if h2 else 0
    bd=defaultdict(float)
    for r in fills: bd[r[2]]+=r[1]
    dpos=sum(1 for d in bd if bd[d]>0)
    return dict(T=T,S=S,lo=lo,hi=hi,tl=tl,th=th,n=n,nofill=nofill,m=m,tot=tot,
                scr=oc['scratched'],stp=oc['stopped'],sl=oc['settled_loss']+oc['settled_win'],
                h1=h1m,h2=h2m,dpos=dpos,dt=len(bd))

for scale in (False, True):
    out(f"\n===== MARKET-MAKING w/ STOP ({'maker fee~0 (small size)' if not scale else '~0.44c/ct maker fee (at size)'}) =====")
    out(f"{'T':>2} {'S':>3} {'band':>7} {'ttc':>8} | {'fills':>5} {'scr':>5} {'stop':>5} {'settle':>6} {'mean':>6} {'TOT$':>8} {'H1':>6} {'H2':>6} {'days+':>6}")
    res=[]
    for T in (1,2):
      for S in (2,4,8):
        for lo,hi in ((20,80),(40,60),(2,97)):
            for tl,th in ((30,900),(120,720)):
                r=evalc(T,S,lo,hi,tl,th,scale)
                if r: res.append(r)
    res.sort(key=lambda r:r['tot'],reverse=True)
    for r in res[:14]:
        rob="*" if (r['h1']>0 and r['h2']>0) else " "
        out(f"{r['T']:>2} {r['S']:>3} {r['lo']:>2}-{r['hi']:<2} {r['tl']:>3}-{r['th']:<3} | {r['n']:>5} {r['scr']:>5} {r['stp']:>5} {r['sl']:>6} {r['m']:>+5.1f}c {r['tot']/100:>+7.2f}${rob} {r['h1']:>+5.1f} {r['h2']:>+5.1f} {r['dpos']:>3}/{r['dt']:<2}")
out("\nMM_DONE")
