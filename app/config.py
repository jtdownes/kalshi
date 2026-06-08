import os

# ── Auth ─────────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ["SECRET_KEY"]

# ── Kalshi API ────────────────────────────────────────────────────────────────
KALSHI_API_BASE        = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS_URL          = os.environ.get("KALSHI_WS_URL", "wss://api.elections.kalshi.com/trade-api/ws/v2")
KALSHI_KEY_ID          = os.environ["KALSHI_KEY_ID"]
KALSHI_PRIVATE_KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "/data/kalshi_private_key.pem")

# ── Storage ───────────────────────────────────────────────────────────────────
DB_TYPE     = os.environ.get("DB_TYPE", "postgres")
DB_URL      = os.environ.get("DB_URL", "")
# jtdownes shared users DB — for login auth
USERS_DB_URL = os.environ.get("USERS_DB_URL", "")

# ── Strategy ──────────────────────────────────────────────────────────────────
MIN_ENTRY_CENTS = int(os.environ.get("MIN_ENTRY_CENTS", "1"))
MAX_ENTRY_CENTS = int(os.environ.get("MAX_ENTRY_CENTS", "2"))

PROACTIVE_MODE = os.environ.get("PROACTIVE_MODE", "true").lower() == "true"

# Trailing lookback window (seconds) for the "craziness" rule fields that are
# inherently rate-of-change measures — realized BTC volatility, range, drift,
# buffer ratio. Derived from the bitcoin_snapshots series over the trailing
# CRAZINESS_LOOKBACK_SECONDS. NOTE: strike_crossings does NOT use this window —
# it counts every strike crossing over the *entire* market life (open -> now),
# bounded by MARKET_DURATION_SECONDS below.
CRAZINESS_LOOKBACK_SECONDS = int(os.environ.get("CRAZINESS_LOOKBACK_SECONDS", "180"))

# Length of one market window (seconds). KXBTC15M = 15 min. Used to bound the
# strike_crossings count to this market's own life so pre-open chop on the
# global BTC series isn't counted against it.
MARKET_DURATION_SECONDS = int(os.environ.get("MARKET_DURATION_SECONDS", "900"))

MAX_OPEN_ORDERS      = int(os.environ.get("MAX_OPEN_ORDERS", "20"))
MAX_DAILY_SPEND_CENTS = int(os.environ.get("MAX_DAILY_SPEND_CENTS", "200"))
LIMIT_SELL_PRICE_CENTS = os.environ.get("LIMIT_SELL_PRICE_CENTS")

_series_raw = os.environ.get("BTC_SERIES_TICKERS", "")
BTC_SERIES_TICKERS = [s.strip() for s in _series_raw.split(",") if s.strip()]

_snapshot_series_raw = os.environ.get("SNAPSHOT_SERIES_TICKERS", "KXBTC15M")
SNAPSHOT_SERIES_TICKERS = [s.strip() for s in _snapshot_series_raw.split(",") if s.strip()]
SNAPSHOT_INTERVAL_SECONDS = int(os.environ.get("SNAPSHOT_INTERVAL_SECONDS", "1"))

# ── Weather (NWS CLI settlement temps) ────────────────────────────────────────
# Stations as "site:issuedby" pairs (NWS office : station), comma-separated.
# e.g. "LOX:LAX,OKX:NYC". LOX/LAX = Los Angeles (settles KXHIGHLAX).
_weather_raw = os.environ.get("WEATHER_STATIONS", "LOX:LAX")
WEATHER_STATIONS = [tuple(p.split(":", 1)) for p in _weather_raw.split(",")
                    if ":" in p]
WEATHER_INTERVAL_SECONDS = int(os.environ.get("WEATHER_INTERVAL_SECONDS", str(15 * 60)))

# ── Timing ────────────────────────────────────────────────────────────────────
LOOK_AHEAD_SECONDS = int(os.environ.get("LOOK_AHEAD_SECONDS", str(20 * 60)))
MIN_SECONDS_TO_CLOSE = int(os.environ.get("MIN_SECONDS_TO_CLOSE", "60"))

ORDER_CHECK_INTERVAL_SECONDS = int(os.environ.get("ORDER_CHECK_INTERVAL_SECONDS", "15"))

def get_all_settings():
    """
    Returns a merged dictionary of environment defaults and database settings.
    """
    import database
    db_settings = database.get_settings()
    
    return {
        "min_entry_cents":        db_settings.get("min_entry_cents", MIN_ENTRY_CENTS),
        "max_entry_cents":        db_settings.get("max_entry_cents", MAX_ENTRY_CENTS),
        "proactive_mode":         db_settings.get("proactive_mode", PROACTIVE_MODE),
        "max_open_orders":        db_settings.get("max_open_orders", MAX_OPEN_ORDERS),
        "max_daily_spend_cents":  db_settings.get("max_daily_spend_cents", MAX_DAILY_SPEND_CENTS),
        "btc_series_tickers":     db_settings.get("btc_series_tickers", BTC_SERIES_TICKERS),
        "exit_strategy":          db_settings.get("exit_strategy", "hold_to_expiration"),
        "limit_sell_price_cents": db_settings.get(
            "limit_sell_price_cents",
            int(LIMIT_SELL_PRICE_CENTS) if LIMIT_SELL_PRICE_CENTS else None,
        ),
        "active_profile_id":      db_settings.get("active_profile_id"),
        "look_ahead_seconds":     LOOK_AHEAD_SECONDS,
        "min_seconds_to_close":   MIN_SECONDS_TO_CLOSE,
        "order_check_interval":   ORDER_CHECK_INTERVAL_SECONDS
    }
