import os

# ── Auth ─────────────────────────────────────────────────────────────────────
SECRET_KEY = os.environ["SECRET_KEY"]

# ── Kalshi API ────────────────────────────────────────────────────────────────
KALSHI_API_BASE        = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_WS_URL          = os.environ.get("KALSHI_WS_URL", "wss://api.elections.kalshi.com/trade-api/ws/v2")
KALSHI_KEY_ID          = os.environ["KALSHI_KEY_ID"]
KALSHI_PRIVATE_KEY_PATH = os.environ.get("KALSHI_PRIVATE_KEY_PATH", "/data/kalshi_private_key.pem")
# Account tier → per-second Read/Write token budgets (see official-docs/concepts/
# rate-limits-and-tiers.md). Drives client-side throttling so we never out-run our
# budget and earn a 429. "basic" is the safe default for a fresh account.
KALSHI_TIER            = os.environ.get("KALSHI_TIER", "basic").lower()

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

# ── Position sizing (bankroll %) ──────────────────────────────────────────────
# When POSITION_SIZE_PCT > 0 the bot ignores each rule's fixed `quantity` and
# sizes every entry to a fraction of the live account balance:
#   contracts = floor(balance_cents * POSITION_SIZE_PCT/100 / entry_price_cents)
# so size scales with the bankroll — it compounds up as you win and shrinks on a
# drawdown, instead of betting a fixed number of contracts regardless of account.
# MAX_PORTFOLIO_EXPOSURE_PCT caps total simultaneous open-entry cost so correlated
# bets (BTC/ETH/SOL move together) can't stack into one oversized position; 0 = no
# cap. If the sized bet rounds to < 1 contract (account too small to take a
# properly-sized position) the entry is skipped rather than over-risking a single
# contract. Set POSITION_SIZE_PCT=0 to fall back to each rule's fixed quantity.
POSITION_SIZE_PCT          = float(os.environ.get("POSITION_SIZE_PCT", "10"))
MAX_PORTFOLIO_EXPOSURE_PCT = float(os.environ.get("MAX_PORTFOLIO_EXPOSURE_PCT", "30"))

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

# ── Live bad-data guard (don't trade on broken/discontinuous data) ────────────
# Before the bot acts on a market it confirms the data is healthy, so a power
# outage / crash / feed stall can't make it resume and immediately fire a trade
# on stale or placeholder data. A market is skipped this tick if:
#   - no real two-sided book yet (yes_ask/no_ask <= 0 — the 0/100 placeholder), or
#   - zero volume (nothing has traded — not a real market yet), or
#   - we don't have continuous recent coverage: snapshots must span at least
#     LIVE_MIN_SPAN_SECS within the last LIVE_DATA_WINDOW_SECS with no single gap
#     over LIVE_MAX_GAP_SECS. After an outage this holds off trading until ~30s of
#     continuous data has been rebuilt; in steady state it never triggers.
LIVE_DATA_WINDOW_SECS = int(os.environ.get("LIVE_DATA_WINDOW_SECS", "120"))
LIVE_MIN_SPAN_SECS    = int(os.environ.get("LIVE_MIN_SPAN_SECS", "30"))
LIVE_MAX_GAP_SECS     = int(os.environ.get("LIVE_MAX_GAP_SECS", "20"))

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
