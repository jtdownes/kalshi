#!/usr/bin/env python3
"""Mean-reversion scalp test: buy a dip, rest a sell on the bounce, settle tail
on OFFICIAL result. Answers: is the wiggle bigger than the spread, after fees?

Fill model (matches the engine's convention, which is GENEROUS to scalping):
  entry = take the dip at the ask (taker).
  exit  = rest a limit sell; fills when the bid later reaches fill+target (maker).
  stop  = if bid falls to fill-stop, market-sell at the bid.
  unsold at close -> hold to settlement (official yes/no result).
"""
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
  SELECT ticker,scanned_at,time_to_close_secs AS ttc,yes_ask,yes_bid,no_ask,no_bid
  FROM market_snapshots WHERE ticker LIKE 'KXBTC15M-%' AND yes_ask IS NOT NULL
  ORDER BY ticker,scanned_at""")
by=defaultdict(list)
for r in cur.fetchall(): by[r["ticker"]].append(dict(r))
cur.execute("SELECT ticker,result FROM market_settlements")
OFF={t:r for t,r in cur.fetchall()}
cur.close(); conn.close()

# ---- spread stats ----
spreads=[]
for ticks in by.values():
    for t in ticks:
        if t["yes_ask"] is not None and t["yes_bid"] is not None and 0<t["yes_bid"]<=t["yes_ask"]<100:
            spreads.append(t["yes_ask"]-t["yes_bid"])
spreads.sort()
def pct(p): return spreads[min(len(spreads)-1,int(p/100*len(spreads)))]
out(f"\nYES spread (¢): n={len(spreads)} mean={sum(spreads)/len(spreads):.2f} "
    f"p10={pct(10):.0f} p25={pct(25):.0f} med={pct(50):.0f} p75={pct(75):.0f} p90={pct(90):.0f}")

# ---- build windows ----
W={}
for tk,ticks in by.items():
    last=ticks[-1]
    if last["ttc"] is None or last["ttc"]>=20: continue
    off=OFF.get(tk)
    if off in ("yes","no"): yw=1 if off=="yes" else 0
    else:
        ref=last["yes_bid"] if last["yes_bid"] is not None else last["yes_ask"]
        yw=1 if (ref is not None and float(ref)>=50) else 0
    seq=[t for t in ticks if t["ttc"] is not None]
    if not seq: continue
    # precompute trailing-max ask over LOOKBACK secs, once per side (two-pointer)
    LB=60
    def rmax(ak):
        n=len(seq); o=[None]*n
        from collections import deque
        dq=deque(); lo=0
        for i in range(n):
            ti=seq[i]["ttc"]
            a=seq[i][ak]
            while dq and seq[dq[-1]][ak] is not None and a is not None and seq[dq[-1]][ak]<=a: dq.pop()
            if a is not None and 0<a<100: dq.append(i)
            while dq and seq[dq[0]]["ttc"]-ti>LB: dq.popleft()
            o[i]=seq[dq[0]][ak] if dq else None
        return o
    def rmin(ak):
        n=len(seq); o=[None]*n
        from collections import deque
        dq=deque()
        for i in range(n):
            ti=seq[i]["ttc"]; a=seq[i][ak]
            while dq and seq[dq[-1]][ak] is not None and a is not None and seq[dq[-1]][ak]>=a: dq.pop()
            if a is not None and 0<a<100: dq.append(i)
            while dq and seq[dq[0]]["ttc"]-ti>LB: dq.popleft()
            o[i]=seq[dq[0]][ak] if dq else None
        return o
    W[tk]={"t":seq,"yw":yw,"day":seq[0]["scanned_at"][:10],
           "rmax_yes":rmax("yes_ask"),"rmax_no":rmax("no_ask"),
           "rmin_yes":rmin("yes_ask"),"rmin_no":rmin("no_ask")}
days=sorted({w["day"] for w in W.values()}); mid=days[len(days)//2]
out(f"windows={len(W)} days={len(days)}")

def scalp(w, side, D, T, S, lookback, lo, hi, tl, th, mode="revert"):
    ak="yes_ask" if side=="yes" else "no_ask"; bk="yes_bid" if side=="yes" else "no_bid"
    seq=w["t"]; n=len(seq)
    if mode=="revert":
        recent=w["rmax_yes"] if side=="yes" else w["rmax_no"]   # buy DIP below recent high
    else:
        recent=w["rmin_yes"] if side=="yes" else w["rmin_no"]   # buy BREAKOUT above recent low
    ei=None
    for i in range(n):
        a=seq[i][ak]; ttc=seq[i]["ttc"]
        if a is None or not(0<a<100): continue
        if not(tl<=ttc<=th and lo<=a<=hi): continue
        if recent[i] is None: continue
        if mode=="revert" and a > recent[i]-D: continue
        if mode=="breakout" and a < recent[i]+D: continue
        ei=i; break
    if ei is None: return None
    fill=seq[ei][ak]; target=fill+T; stop=fill-S if S else None
    for t in seq[ei+1:]:
        b=t[bk]
        if b is None: continue
        if b>=target:
            return (target-fill-fee(fill)-fee(target), "sold", w["day"], fill)
        if stop is not None and b<=stop:
            return (b-fill-fee(fill)-fee(b), "stopped", w["day"], fill)
    won = w["yw"] if side=="yes" else (1-w["yw"])
    return ((100 if won else 0)-fill-fee(fill), "settled", w["day"], fill)

def evalc(D,T,S,lb,lo,hi,tl,th,mode="revert"):
    tr=[]
    for w in W.values():
        for side in ("yes","no"):
            e=scalp(w,side,D,T,S,lb,lo,hi,tl,th,mode)
            if e: tr.append(e)
    n=len(tr)
    if n<30: return None
    pn=[x[0] for x in tr]; m=sum(pn)/n; tot=sum(pn)
    oc=defaultdict(int)
    for x in tr: oc[x[1]]+=1
    h1=[x[0] for x in tr if x[2]<=mid]; h2=[x[0] for x in tr if x[2]>mid]
    h1m=sum(h1)/len(h1) if h1 else 0; h2m=sum(h2)/len(h2) if h2 else 0
    cost=sum(x[3]+fee(x[3]) for x in tr)
    return dict(D=D,T=T,S=S,lb=lb,lo=lo,hi=hi,tl=tl,th=th,n=n,mean=m,tot=tot,
                roi=100*tot/cost if cost else 0,sold=oc['sold'],stop=oc['stopped'],
                settle=oc['settled'],h1=h1m,h2=h2m)

def runmode(mode):
    out(f"\n===== {mode.upper()} SCALP SWEEP (both sides, fees in, official tail) =====")
    out(f"{'D':>2} {'T':>2} {'S':>3} {'band':>7} {'ttc':>8} | {'n':>4} {'sold':>4} {'stop':>4} {'set':>4} {'win%':>5} {'mean':>6} {'ROI%':>6} {'TOT$':>7} {'H1':>6} {'H2':>6}")
    res=[]
    for D in (4,6,10):
      for T in (3,5,8):
        for S in (None,8):
          for lo,hi in ((25,70),(30,60),(2,97)):
            r=evalc(D,T,S,60,lo,hi,30,720,mode)
            if r: res.append(r)
    res.sort(key=lambda r:r['tot'],reverse=True)
    for r in res[:12]:
        winp=100*r['sold']/r['n']
        out(f"{r['D']:>2} {r['T']:>2} {str(r['S']):>3} {r['lo']:>2}-{r['hi']:<2} {r['tl']:>3}-{r['th']:<3} | "
            f"{r['n']:>4} {r['sold']:>4} {r['stop']:>4} {r['settle']:>4} {winp:>4.0f}% {r['mean']:>+5.1f}c {r['roi']:>+5.1f}% {r['tot']/100:>+6.2f}$ {r['h1']:>+5.1f} {r['h2']:>+5.1f}")

runmode("revert")
runmode("breakout")
out("\nSCALP_DONE")
