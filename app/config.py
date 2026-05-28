import os

# ── Kalshi API ────────────────────────────────────────────────────────────────
KALSHI_API_BASE        = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS_URL          = os.environ.get("KALSHI_WS_URL", "wss://api.elections.kalshi.com/trade-api/ws/v2")
KALSHI_KEY_ID          = os.environ["KALSHI_KEY_ID"]
KALSHI_PRIVATE_KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "/data/kalshi_private_key.pem")

# ── Storage ───────────────────────────────────────────────────────────────────
DB_TYPE = os.environ.get("DB_TYPE", "postgres")
DB_URL  = os.environ.get("DB_URL", "")

# ── Strategy ──────────────────────────────────────────────────────────────────
MIN_ENTRY_CENTS = int(os.environ.get("MIN_ENTRY_CENTS", "1"))
MAX_ENTRY_CENTS = int(os.environ.get("MAX_ENTRY_CENTS", "2"))

PROACTIVE_MODE = os.environ.get("PROACTIVE_MODE", "true").lower() == "true"

MAX_OPEN_ORDERS      = int(os.environ.get("MAX_OPEN_ORDERS", "20"))
MAX_DAILY_SPEND_CENTS = int(os.environ.get("MAX_DAILY_SPEND_CENTS", "200"))
LIMIT_SELL_PRICE_CENTS = os.environ.get("LIMIT_SELL_PRICE_CENTS")

_series_raw = os.environ.get("BTC_SERIES_TICKERS", "")
BTC_SERIES_TICKERS = [s.strip() for s in _series_raw.split(",") if s.strip()]

# ── Timing ────────────────────────────────────────────────────────────────────
LOOK_AHEAD_SECONDS = int(os.environ.get("LOOK_AHEAD_SECONDS", str(20 * 60)))
MIN_SECONDS_TO_CLOSE = int(os.environ.get("MIN_SECONDS_TO_CLOSE", "60"))

SCAN_INTERVAL_SECONDS        = int(os.environ.get("SCAN_INTERVAL_SECONDS", "30"))
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
        "scan_interval_seconds":  db_settings.get("scan_interval_seconds", SCAN_INTERVAL_SECONDS),
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
