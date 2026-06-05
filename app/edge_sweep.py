#!/usr/bin/env python3
"""
Exhaustive edge search for KXBTC15M from 1-second snapshot history.

Sections:
  0. Load windows (ticks + BTC price merged), settle each on its terminal verdict.
  1. MARKET CALIBRATION: bucket entries by ask price at fixed time-to-close
     horizons; does realized win% beat the price you pay? (edge lives only where
     win% - price > fee). Done for YES and NO.
  2. MOMENTUM CALIBRATION: same buckets, but conditioned on BTC trailing momentum
     and distance-to-strike sign — the "predict direction" hypothesis.
  3. SWEEP: one trade/window (first qualifying entry), hold to settlement, fees in.
     Grid over side x price-band x ttc-band x distance x momentum. Ranked by
     t-stat, with first-half/second-half and per-day sign consistency so a single
     lucky regime can't masquerade as edge.
Read-only.
"""
import os, math
from collections import defaultdict
import psycopg2, psycopg2.extras

DB = os.environ["DB_URL"]

def fee(p):
    p = float(p)
    if p <= 0 or p >= 100: return 0
    return math.ceil(0.07 * p * (100 - p) / 100.0)

# ---------- 0. LOAD ----------
def load():
    conn = psycopg2.connect(DB)
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute("""
        SELECT m.ticker, m.scanned_at, m.time_to_close_secs AS ttc,
               m.yes_ask, m.yes_bid, m.no_ask, m.no_bid,
               NULLIF(m.strike_str,'')::numeric AS strike,
               COALESCE(b.consolidated_price, b.coinbase_price) AS btc
        FROM market_snapshots m
        LEFT JOIN bitcoin_snapshots b ON b.scanned_at = m.scanned_at
        WHERE m.ticker LIKE 'KXBTC15M-%' AND m.yes_ask IS NOT NULL
        ORDER BY m.ticker, m.scanned_at
    """)
    by = defaultdict(list)
    for r in cur.fetchall():
        by[r["ticker"]].append(dict(r))
    cur.close(); conn.close()

    windows = {}
    for tk, ticks in by.items():
        last = ticks[-1]
        if last["ttc"] is None or last["ttc"] >= 20:
            continue  # never saw the bell -> can't settle honestly
        ref = last["yes_bid"] if last["yes_bid"] is not None else last["yes_ask"]
        yes_win = 1 if (ref is not None and float(ref) >= 50) else 0
        day = ticks[0]["scanned_at"][:10]
        # precompute distance + trailing momentum (BTC change over last 60s/180s)
        ttc = [t["ttc"] for t in ticks]
        btc = [t["btc"] for t in ticks]
        for i, t in enumerate(ticks):
            t["dist"] = (float(t["btc"]) - float(t["strike"])) if (t["btc"] is not None and t["strike"] is not None) else None
        def mom(N):
            out = [None]*len(ticks); j = 0
            for i in range(len(ticks)):
                if ttc[i] is None: continue
                # advance j to the latest index with ttc at least N secs before i
                while j < i and (ttc[j] is None or ttc[i] is None or ttc[j] - ttc[i] > N):
                    j += 1
                k = j - 1
                if k >= 0 and ttc[k] is not None and btc[k] is not None and btc[i] is not None and (ttc[k]-ttc[i]) >= N*0.5:
                    out[i] = float(btc[i]) - float(btc[k])
            return out
        m60, m180 = mom(60), mom(180)
        for i, t in enumerate(ticks):
            t["m60"], t["m180"] = m60[i], m180[i]
        windows[tk] = {"ticks": ticks, "yes_win": yes_win, "day": day}
    return windows

# ---------- 1+2. CALIBRATION ----------
def tick_at_horizon(ticks, H, tol=6):
    best=None; bd=1e9
    for t in ticks:
        if t["ttc"] is None: continue
        d=abs(t["ttc"]-H)
        if d<bd: bd=d; best=t
    return best if bd<=tol else None

def calibration(windows, side, H, mom_key=None, mom_dir=None, dist_sign=None):
    ask_k = "yes_ask" if side=="yes" else "no_ask"
    buckets=defaultdict(lambda:[0,0,0.0])  # bin -> [n, wins, sum_price]
    for w in windows.values():
        t=tick_at_horizon(w["ticks"],H)
        if not t: continue
        a=t[ask_k]
        if a is None or a<=0 or a>=100: continue
        if mom_key is not None:
            mv=t[mom_key]
            if mv is None: continue
            if mom_dir=="up" and mv<=0: continue
            if mom_dir=="dn" and mv>=0: continue
        if dist_sign is not None:
            d=t["dist"]
            if d is None: continue
            if dist_sign=="+" and d<=0: continue
            if dist_sign=="-" and d>=0: continue
        won = w["yes_win"] if side=="yes" else (1-w["yes_win"])
        b=int(a//5)*5
        buckets[b][0]+=1; buckets[b][1]+=won; buckets[b][2]+=a
    return buckets

def print_calib(title, buckets):
    print(f"\n--- {title} ---")
    print(f"  {'price':>7} {'n':>4} {'win%':>6} {'edge(win-price)':>16} {'net¢/ct':>8}")
    tot_n=0
    for b in sorted(buckets):
        n,wins,sp=buckets[b]
        if n<8: continue
        tot_n+=n
        wr=100*wins/n; mp=sp/n; edge=wr-mp
        # net per contract holding to settlement, fee in
        net=wr - mp - fee(mp)
        flag=" <<<" if (net>0.5 and n>=15) else ""
        print(f"  {b:>3}-{b+5:<3} {n:>4} {wr:>5.1f}% {edge:>+15.1f} {net:>+7.1f}{flag}")
    print(f"  (total obs: {tot_n})")

# ---------- 3. SWEEP ----------
def simulate(w, side, lo, hi, ttc_lo, ttc_hi, dist_op, dist_val, mom_key, mom_dir):
    ask_k="yes_ask" if side=="yes" else "no_ask"
    for t in w["ticks"]:
        a=t[ask_k]
        if a is None or t["ttc"] is None: continue
        if not (ttc_lo<=t["ttc"]<=ttc_hi): continue
        if not (lo<=a<=hi and a<100): continue
        if dist_op is not None:
            d=t["dist"]
            if d is None: continue
            if dist_op==">" and not d>dist_val: continue
            if dist_op=="<" and not d<dist_val: continue
        if mom_key is not None:
            mv=t[mom_key]
            if mv is None: continue
            if mom_dir=="up" and mv<=0: continue
            if mom_dir=="dn" and mv>=0: continue
        won = w["yes_win"] if side=="yes" else (1-w["yes_win"])
        pnl=(100 if won else 0)-a-fee(a)
        return {"pnl":pnl, "won":won, "day":w["day"], "fill":a}
    return None

def run_sweep(windows):
    days_sorted=sorted({w["day"] for w in windows.values()})
    mid=days_sorted[len(days_sorted)//2]
    grids=[]
    sides=["yes","no"]
    bands=[(2,20),(20,40),(40,55),(45,60),(55,70),(60,75),(70,85),(80,90),(85,95),(88,94),(90,97),(2,97)]
    ttcs=[(30,900),(30,120),(120,300),(300,600),(540,900),(30,540)]
    dists={"yes":[(None,None),(">",0),(">",200),(">",400)],
           "no":[(None,None),("<",0),("<",-200),("<",-400)]}
    moms=[(None,None),("m180","up"),("m180","dn"),("m60","up"),("m60","dn")]
    results=[]
    for side in sides:
        for lo,hi in bands:
            for tl,th in ttcs:
                for dop,dv in dists[side]:
                    for mk,md in moms:
                        trades=[simulate(w,side,lo,hi,tl,th,dop,dv,mk,md) for w in windows.values()]
                        trades=[t for t in trades if t]
                        n=len(trades)
                        if n<30: continue
                        pnls=[t["pnl"] for t in trades]
                        m=sum(pnls)/n
                        var=sum((x-m)**2 for x in pnls)/n
                        se=math.sqrt(var/n) if n>1 else 0
                        t_stat=m/se if se else 0
                        wr=100*sum(t["won"] for t in trades)/n
                        # halves
                        h1=[t["pnl"] for t in trades if t["day"]<=mid]
                        h2=[t["pnl"] for t in trades if t["day"]>mid]
                        h1m=sum(h1)/len(h1) if h1 else 0
                        h2m=sum(h2)/len(h2) if h2 else 0
                        # per-day sign
                        byday=defaultdict(list)
                        for t in trades: byday[t["day"]].append(t["pnl"])
                        dpos=sum(1 for d in byday if sum(byday[d])>0); dtot=len(byday)
                        results.append((t_stat,m,se,n,wr,side,lo,hi,tl,th,dop,dv,mk,md,h1m,h2m,dpos,dtot))
    results.sort(key=lambda r:r[0],reverse=True)
    print(f"\n================ SWEEP LEADERBOARD (top 30 by t-stat) ================")
    print(f"  combos tested with n>=30: {len(results)}")
    print(f"  {'t':>5} {'mean¢':>6} {'n':>4} {'win%':>5}  side band     ttc       dist     mom        H1     H2   days+")
    print("  "+"-"*108)
    for r in results[:30]:
        (t_stat,m,se,n,wr,side,lo,hi,tl,th,dop,dv,mk,md,h1m,h2m,dpos,dtot)=r
        dist=f"{dop}{dv}" if dop else "-"
        mom=f"{mk}/{md}" if mk else "-"
        rob="OK" if (h1m>0 and h2m>0) else ""
        print(f"  {t_stat:>+5.2f} {m:>+6.1f} {n:>4} {wr:>4.0f}%  {side:<3} {lo:>2}-{hi:<2} {tl:>3}-{th:<3} {dist:>8} {mom:>10} {h1m:>+6.1f} {h2m:>+6.1f}  {dpos}/{dtot} {rob}")
    return results

if __name__=="__main__":
    print("Loading windows...")
    W=load()
    days=sorted({w["day"] for w in W.values()})
    print(f"settled windows={len(W)}  days={len(days)} ({days[0]}..{days[-1]})")
    yes_rate=100*sum(w['yes_win'] for w in W.values())/len(W)
    print(f"base YES-settle rate across all windows: {yes_rate:.1f}%")

    for H in (300,120,60):
        print(f"\n############ CALIBRATION @ ~{H}s to close ############")
        print_calib(f"YES buy@ask  H={H}s", calibration(W,"yes",H))
        print_calib(f"NO  buy@ask  H={H}s", calibration(W,"no",H))

    print(f"\n############ MOMENTUM-CONDITIONED CALIBRATION @120s ############")
    print_calib("YES, BTC m180>0",            calibration(W,"yes",120,"m180","up"))
    print_calib("YES, BTC m180>0 & dist>0",   calibration(W,"yes",120,"m180","up","+"))
    print_calib("NO,  BTC m180<0",            calibration(W,"no",120,"m180","dn"))
    print_calib("NO,  BTC m180<0 & dist<0",   calibration(W,"no",120,"m180","dn","-"))

    run_sweep(W)
    print("\nDONE.")
