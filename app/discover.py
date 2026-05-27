"""
One-shot discovery script -- run before starting the bot.

Usage:
  docker exec kalshi-bot python discover.py

Prints all open BTC-related markets with their series tickers, current
Yes/No ask prices, and time to close. Copy the series tickers into
BTC_SERIES_TICKERS in .env.
"""

from datetime import datetime, timezone
from kalshi_client import KalshiClient


def fmt_close(raw) -> str:
    if raw is None:
        return "?"
    try:
        if isinstance(raw, (int, float)):
            return datetime.fromtimestamp(raw, tz=timezone.utc).strftime("%H:%M UTC")
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).strftime("%H:%M UTC")
    except Exception:
        return str(raw)


def main():
    client = KalshiClient()
    print("\nFetching all open markets...\n")

    all_markets = []
    cursor = None
    while True:
        params = {"status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        data   = client.get_markets(**params)
        batch  = data.get("markets", [])
        all_markets.extend(batch)
        cursor = data.get("cursor")
        if not cursor or not batch:
            break

    btc_markets = [
        m for m in all_markets
        if "BTC" in m.get("ticker", "").upper()
        or "BTC" in m.get("title", "").upper()
        or "bitcoin" in m.get("title", "").lower()
    ]

    print(f"Total open markets : {len(all_markets)}")
    print(f"BTC-related markets: {len(btc_markets)}\n")

    series_seen: set[str] = set()

    def sort_key(m):
        raw = m.get("close_time") or m.get("expiration_time") or 0
        return int(raw) if isinstance(raw, (int, float)) else 0

    for m in sorted(btc_markets, key=sort_key):
        ticker  = m.get("ticker", "")
        series  = m.get("series_ticker", "N/A")
        title   = (m.get("title") or "")[:55]
        close   = fmt_close(m.get("close_time") or m.get("expiration_time"))
        yes_ask = m.get("yes_ask", "?")
        no_ask  = m.get("no_ask", "?")
        vol     = m.get("volume", "?")
        series_seen.add(series)
        print(f"  {ticker:<50} series={series:<16} "
              f"yes_ask={str(yes_ask):>3}\u00a2  no_ask={str(no_ask):>3}\u00a2  "
              f"vol={vol}  closes={close}")
        print(f"    {title}")

    if not btc_markets:
        print("  (none found -- check your API key or try later)")
        return

    series_str = ",".join(sorted(series_seen))
    print("\n" + "=" * 70)
    print(f"Unique series tickers: {sorted(series_seen)}")
    print(f"\nAdd this line to .env:")
    print(f"  BTC_SERIES_TICKERS={series_str}")
    print("=" * 70)


if __name__ == "__main__":
    main()
