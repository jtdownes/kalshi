#!/usr/bin/env python3
"""Backfill historical observed daily highs from IEM's parsed-CLI archive.

IEM parses the SAME NWS CLI product Kalshi settles on, and exposes high/low/precip
plus a unique product id per date — so each backfilled row links to its exact
report (unlike the live station page, which only shows today). Replaces any prior
ACIS backfill (which lacked precip / text / a per-date link). Idempotent: never
touches a (station, obs_date) that already exists (e.g. a live CLI row).
"""
import os
from datetime import date, timedelta

import requests
import psycopg2

import config
import weather

DAYS = int(os.environ.get("BACKFILL_DAYS", "60"))
IEM = "https://mesonet.agron.iastate.edu/json/cli.py"


def _int(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _precip(v):
    if v in (None, "M"):
        return None
    if v == "T":
        return 0.0
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def main():
    if not config.WEATHER_STATIONS:
        print("no WEATHER_STATIONS configured"); return
    conn = psycopg2.connect(config.DB_URL); conn.autocommit = True
    cur = conn.cursor()
    edate = date.today()
    sdate = edate - timedelta(days=DAYS)
    years = sorted({sdate.year, edate.year})

    # Replace any earlier ACIS backfill with the richer IEM rows.
    cur.execute("DELETE FROM weather_snapshots WHERE issued = 'ACIS backfill'")
    print(f"removed {cur.rowcount} old ACIS rows; backfilling {sdate}..{edate} from IEM")

    for site, station in config.WEATHER_STATIONS:
        sid = f"K{station}"
        rows = []
        for yr in years:
            try:
                r = requests.get(IEM, params={"station": sid, "year": str(yr), "fmt": "json"}, timeout=30)
                rows += r.json().get("results", []) or []
            except Exception as e:
                print(f"  {station}: IEM error for {yr}: {e}")
        ins = skip = 0
        for row in rows:
            d = row.get("valid")
            if not d or not (sdate.isoformat() <= d <= edate.isoformat()):
                continue
            maxt = _int(row.get("high"))
            if maxt is None:
                continue
            cur.execute("SELECT 1 FROM weather_snapshots WHERE station=%s AND obs_date=%s LIMIT 1",
                        (station, d))
            if cur.fetchone():
                skip += 1; continue
            pid = row.get("product")
            url = weather.IEM_PERMALINK.format(pid=pid) if pid else \
                weather.CLI_URL.format(site=site, issuedby=station)
            # real issuance time from the product id (YYYYMMDDHHMM...)
            issued = "IEM CLI archive"
            if pid and pid[:12].isdigit():
                t = pid
                issued = f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}Z"
            excerpt = (f"high {row.get('high')}F at {row.get('high_time')}, "
                       f"low {row.get('low')}F at {row.get('low_time')}, "
                       f"precip {row.get('precip')} in")
            cur.execute("""
                INSERT INTO weather_snapshots
                  (station, scanned_at, obs_date, max_temp_f, min_temp_f, precip_in, issued, raw_excerpt, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (station, d + "T12:00:00", d, maxt, _int(row.get("low")),
                  _precip(row.get("precip")), issued, excerpt, url))
            ins += 1
        print(f"  {station} ({sid}): inserted={ins}, skipped(existing)={skip}")
    print("DONE")


if __name__ == "__main__":
    main()
