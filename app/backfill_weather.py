#!/usr/bin/env python3
"""Backfill historical observed daily highs (the Kalshi weather settlement value).

Source: ACIS (data.rcc-acis.org), which returns the same station daily max the NWS
CLI reports — verified to match exactly (LAX 2026-06-04 = 72F in both). Idempotent:
only fills (station, obs_date) pairs not already in weather_snapshots, so it never
double-counts the live CLI rows. Each row links to the official CLI product page.
"""
import os
import sys
import json
from datetime import date, timedelta

import requests
import psycopg2

import config
import weather

DAYS = int(os.environ.get("BACKFILL_DAYS", "60"))
ACIS = "http://data.rcc-acis.org/StnData"


def _num(v):
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def main():
    if not config.WEATHER_STATIONS:
        print("no WEATHER_STATIONS configured"); return
    conn = psycopg2.connect(config.DB_URL); conn.autocommit = True
    cur = conn.cursor()
    edate = date.today()
    sdate = edate - timedelta(days=DAYS)
    print(f"backfilling {sdate}..{edate} for {config.WEATHER_STATIONS}")

    for site, station in config.WEATHER_STATIONS:
        url = weather.CLI_URL.format(site=site, issuedby=station)
        rows = []
        for sid in (f"K{station}", station):          # try ICAO then bare code
            params = {"sid": sid, "sdate": sdate.isoformat(), "edate": edate.isoformat(),
                      "elems": "maxt,mint", "output": "json"}
            try:
                r = requests.get(ACIS, params={"params": json.dumps(params)}, timeout=30)
                rows = r.json().get("data", []) or []
            except Exception as e:
                print(f"  {station}: ACIS error for sid={sid}: {e}"); rows = []
            if rows:
                break
        ins = skip = 0
        for row in rows:
            d = row[0]
            maxt = _num(row[1]) if len(row) > 1 else None
            mint = _num(row[2]) if len(row) > 2 else None
            if maxt is None:
                continue
            cur.execute("SELECT 1 FROM weather_snapshots WHERE station=%s AND obs_date=%s LIMIT 1",
                        (station, d))
            if cur.fetchone():
                skip += 1; continue
            cur.execute("""
                INSERT INTO weather_snapshots
                  (station, scanned_at, obs_date, max_temp_f, min_temp_f, precip_in, issued, raw_excerpt, source_url)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (station, d + "T12:00:00", d, maxt, mint, None, "ACIS backfill", None, url))
            ins += 1
        print(f"  {station}: {len(rows)} days, inserted={ins}, skipped(existing)={skip}")
    print("DONE")


if __name__ == "__main__":
    main()
