"""
NWS Climatological Report (CLI) fetch + parse.

The CLI product is the OFFICIAL observed daily high/low that Kalshi settles its
KXHIGH<city> temperature markets on. The morning-after report's "YESTERDAY
MAXIMUM" is the finalized high for that date — i.e. the settlement value. We poll
it and store time-stamped snapshots so we have ground-truth outcomes (the weather
analogue of market_settlements for BTC) plus any intraday preliminary readings.

Example: https://forecast.weather.gov/product.php?site=LOX&product=CLI&issuedby=LAX
"""
import re
import html
import urllib.request
import logging

log = logging.getLogger(__name__)

CLI_URL = "https://forecast.weather.gov/product.php?site={site}&product=CLI&issuedby={issuedby}"

_MONTHS = {m: i for i, m in enumerate(
    ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST",
     "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"], start=1)}


def _fetch_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "kalshi-bot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", "replace")
    m = re.search(r"<pre[^>]*>(.*?)</pre>", raw, re.S | re.I)
    return html.unescape(m.group(1) if m else raw)


def parse_cli(text: str) -> dict:
    """Parse a CLI product into the date it summarizes and that day's high/low."""
    out = {"obs_date": None, "max_temp_f": None, "min_temp_f": None,
           "precip_in": None, "issued": None}

    # Date the report summarizes, e.g. "...CLIMATE SUMMARY FOR JUNE 4 2026..."
    md = re.search(r"SUMMARY FOR\s+([A-Z]+)\s+(\d{1,2})\s+(\d{4})", text, re.I)
    if md:
        mon = _MONTHS.get(md.group(1).upper())
        if mon:
            out["obs_date"] = f"{int(md.group(3)):04d}-{mon:02d}-{int(md.group(2)):02d}"

    # Issuance line, e.g. "141 AM PDT FRI JUN 05 2026"
    mi = re.search(r"^\s*(\d{3,4}\s+[AP]M\s+[A-Z]{2,4}\s+[A-Z]{3}\s+[A-Z]{3}\s+\d{1,2}\s+\d{4})\s*$",
                   text, re.M)
    if mi:
        out["issued"] = mi.group(1).strip()

    # Temperature: first MAXIMUM / MINIMUM after the TEMPERATURE header. In the
    # morning report these sit under "YESTERDAY" and correspond to obs_date.
    ti = text.upper().find("TEMPERATURE")
    tsec = text[ti:] if ti != -1 else text
    mx = re.search(r"MAXIMUM\s+(-?\d+)", tsec)
    mn = re.search(r"MINIMUM\s+(-?\d+)", tsec)
    if mx:
        out["max_temp_f"] = int(mx.group(1))
    if mn:
        out["min_temp_f"] = int(mn.group(1))

    # Precip: first "YESTERDAY <value>" under PRECIPITATION (T = trace, MM = missing)
    pi = text.upper().find("PRECIPITATION")
    if pi != -1:
        mp = re.search(r"YESTERDAY\s+([\d.]+|T|MM)", text[pi:])
        if mp:
            v = mp.group(1)
            out["precip_in"] = 0.0 if v == "T" else (None if v == "MM" else float(v))
    return out


def fetch_cli(site: str, issuedby: str) -> dict:
    """Fetch and parse the CLI product for an NWS office/station pair.

    `site` is the issuing office (e.g. LOX); `issuedby` is the station (e.g. LAX).
    Returns the parsed dict plus station/url and a short raw excerpt for audit.
    """
    url = CLI_URL.format(site=site, issuedby=issuedby)
    text = _fetch_text(url)
    out = parse_cli(text)
    out["station"] = issuedby
    out["url"] = url
    ti = text.upper().find("TEMPERATURE")
    out["raw_excerpt"] = (text[ti:ti + 240] if ti != -1 else text[:240]).strip()
    return out
