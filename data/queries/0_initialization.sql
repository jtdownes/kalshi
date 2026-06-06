CREATE TABLE IF NOT EXISTS profiles (
    id                      SERIAL PRIMARY KEY,
    name                    TEXT NOT NULL,
    created_at              TEXT NOT NULL,
    is_active               BOOLEAN NOT NULL DEFAULT FALSE,
    min_entry_cents         INTEGER NOT NULL,
    max_entry_cents         INTEGER NOT NULL,
    proactive_mode          BOOLEAN NOT NULL,
    max_open_orders         INTEGER NOT NULL,
    max_daily_spend_cents   INTEGER NOT NULL,
    btc_series_tickers      TEXT NOT NULL,
    exit_strategy           TEXT NOT NULL DEFAULT 'hold_to_expiration',
    limit_sell_price_cents  INTEGER
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='exit_strategy') THEN
        ALTER TABLE profiles ADD COLUMN exit_strategy TEXT NOT NULL DEFAULT 'hold_to_expiration';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='limit_sell_price_cents') THEN
        ALTER TABLE profiles ADD COLUMN limit_sell_price_cents INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='is_active') THEN
        ALTER TABLE profiles ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT FALSE;
        UPDATE profiles SET is_active = TRUE
        WHERE id = (SELECT active_profile_id FROM settings WHERE id = 1 LIMIT 1);
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='scan_interval_seconds') THEN
        ALTER TABLE profiles DROP COLUMN scan_interval_seconds;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS orders (
    id                              SERIAL PRIMARY KEY,
    kalshi_order_id                 TEXT UNIQUE,
    client_order_id                 TEXT UNIQUE NOT NULL,
    market_ticker                   TEXT NOT NULL,
    side                            TEXT NOT NULL,
    order_role                      TEXT NOT NULL DEFAULT 'entry',
    parent_kalshi_order_id          TEXT,
    exit_order_kalshi_id            TEXT,
    entry_price_cents               INTEGER NOT NULL,
    count                           INTEGER NOT NULL DEFAULT 1,
    status                          TEXT NOT NULL DEFAULT 'resting',
    placed_at                       TEXT NOT NULL,
    filled_at                       TEXT,
    btc_price_at_placement          REAL,
    btc_price_at_fill               REAL,
    distance_to_strike_at_placement REAL,
    market_close_time               TEXT,
    time_to_close_at_placement      INTEGER,
    exit_strategy                   TEXT NOT NULL DEFAULT 'hold_to_expiration',
    exit_target_cents               INTEGER,
    closed_at                       TEXT,
    close_reason                    TEXT,
    close_price_cents               INTEGER,
    outcome                         TEXT,
    payout_cents                    INTEGER,
    fee_cents                       INTEGER,
    net_profit_cents                INTEGER,
    notes                           TEXT,
    profile_id                      INTEGER
);

-- Add profile_id to orders if it doesn't exist
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='profile_id') THEN
        ALTER TABLE orders ADD COLUMN profile_id INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='order_role') THEN
        ALTER TABLE orders ADD COLUMN order_role TEXT NOT NULL DEFAULT 'entry';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='parent_kalshi_order_id') THEN
        ALTER TABLE orders ADD COLUMN parent_kalshi_order_id TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='exit_order_kalshi_id') THEN
        ALTER TABLE orders ADD COLUMN exit_order_kalshi_id TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='exit_strategy') THEN
        ALTER TABLE orders ADD COLUMN exit_strategy TEXT NOT NULL DEFAULT 'hold_to_expiration';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='exit_target_cents') THEN
        ALTER TABLE orders ADD COLUMN exit_target_cents INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='closed_at') THEN
        ALTER TABLE orders ADD COLUMN closed_at TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='close_reason') THEN
        ALTER TABLE orders ADD COLUMN close_reason TEXT;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='close_price_cents') THEN
        ALTER TABLE orders ADD COLUMN close_price_cents INTEGER;
    END IF;
END $$;

-- Stop-loss trigger (cents) on the side's bid. When set on a filled entry, the
-- bot market-sells the position the moment the bid trades at/through this level.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='stop_loss_cents') THEN
        ALTER TABLE orders ADD COLUMN stop_loss_cents INTEGER;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS market_snapshots (
    id                   SERIAL PRIMARY KEY,
    ticker               TEXT NOT NULL,
    title                TEXT,
    scanned_at           TEXT NOT NULL,
    close_time           TEXT,
    yes_ask              REAL,
    yes_bid              REAL,
    no_ask               REAL,
    no_bid               REAL,
    time_to_close_secs   INTEGER,
    strike_str           TEXT,
    volume               INTEGER,
    open_interest        INTEGER
);

-- Bitcoin price/volume is global per tick (not per market), so it lives in its
-- own table written once per collection pass and joined to market_snapshots on
-- scanned_at. Bitcoin data formerly lived in per-market columns on
-- market_snapshots; those are backfilled into this table then dropped below.
CREATE TABLE IF NOT EXISTS bitcoin_snapshots (
    id                  SERIAL PRIMARY KEY,
    scanned_at          TEXT NOT NULL,
    coinbase_price      REAL,
    kraken_price        REAL,
    bitstamp_price      REAL,
    gemini_price        REAL,
    consolidated_price  REAL,
    coinbase_volume     REAL,
    kraken_volume       REAL,
    bitstamp_volume     REAL,
    gemini_volume       REAL
);
CREATE INDEX IF NOT EXISTS idx_bitcoin_snapshots_scanned_at ON bitcoin_snapshots (scanned_at);

-- One-time backfill: lift bitcoin data still embedded in the legacy
-- market_snapshots columns into bitcoin_snapshots, keyed by each row's
-- scanned_at, so historical joins resolve. Only runs on a pre-split DB that
-- still has those columns AND has no bitcoin rows yet; the INSERT is dynamic
-- so it doesn't fail to parse once the columns have been dropped below.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_name='market_snapshots' AND column_name='btc_price')
       AND NOT EXISTS (SELECT 1 FROM bitcoin_snapshots LIMIT 1) THEN
        EXECUTE $bf$
            INSERT INTO bitcoin_snapshots
                (scanned_at, coinbase_price, kraken_price, bitstamp_price, gemini_price,
                 consolidated_price, coinbase_volume, kraken_volume, bitstamp_volume, gemini_volume)
            SELECT
                m.scanned_at,
                m.btc_price, m.kraken_price, m.bitstamp_price, m.gemini_price,
                ( COALESCE(m.btc_price, 0) + COALESCE(m.kraken_price, 0)
                + COALESCE(m.bitstamp_price, 0) + COALESCE(m.gemini_price, 0) )
                / NULLIF(
                    (m.btc_price      IS NOT NULL)::int + (m.kraken_price   IS NOT NULL)::int
                  + (m.bitstamp_price IS NOT NULL)::int + (m.gemini_price   IS NOT NULL)::int, 0),
                m.coinbase_volume, m.kraken_volume, m.bitstamp_volume, m.gemini_volume
            FROM market_snapshots m
            WHERE m.btc_price IS NOT NULL OR m.kraken_price IS NOT NULL
               OR m.bitstamp_price IS NOT NULL OR m.gemini_price IS NOT NULL
        $bf$;
    END IF;
END $$;

-- Drop the now-redundant per-market bitcoin columns from market_snapshots.
-- All readers join bitcoin_snapshots instead; the data was backfilled above.
ALTER TABLE market_snapshots
    DROP COLUMN IF EXISTS btc_price,
    DROP COLUMN IF EXISTS brti_price,
    DROP COLUMN IF EXISTS kraken_price,
    DROP COLUMN IF EXISTS bitstamp_price,
    DROP COLUMN IF EXISTS gemini_price,
    DROP COLUMN IF EXISTS coinbase_volume,
    DROP COLUMN IF EXISTS kraken_volume,
    DROP COLUMN IF EXISTS bitstamp_volume,
    DROP COLUMN IF EXISTS gemini_volume;

CREATE TABLE IF NOT EXISTS settings (
    id                     INTEGER PRIMARY KEY CHECK (id = 1),
    min_entry_cents        INTEGER NOT NULL,
    max_entry_cents        INTEGER NOT NULL,
    proactive_mode         BOOLEAN NOT NULL,
    max_open_orders        INTEGER NOT NULL,
    max_daily_spend_cents  INTEGER NOT NULL,
    btc_series_tickers     TEXT NOT NULL,
    exit_strategy          TEXT NOT NULL DEFAULT 'hold_to_expiration',
    limit_sell_price_cents INTEGER,
    active_profile_id      INTEGER
);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='settings' AND column_name='scan_interval_seconds') THEN
        ALTER TABLE settings DROP COLUMN scan_interval_seconds;
    END IF;
END $$;

-- Add active_profile_id to settings if it doesn't exist
DO $$ 
BEGIN 
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='settings' AND column_name='active_profile_id') THEN
        ALTER TABLE settings ADD COLUMN active_profile_id INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='settings' AND column_name='exit_strategy') THEN
        ALTER TABLE settings ADD COLUMN exit_strategy TEXT NOT NULL DEFAULT 'hold_to_expiration';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='settings' AND column_name='limit_sell_price_cents') THEN
        ALTER TABLE settings ADD COLUMN limit_sell_price_cents INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='min_time_to_close_secs') THEN
        ALTER TABLE profiles ADD COLUMN min_time_to_close_secs INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='max_time_to_close_secs') THEN
        ALTER TABLE profiles ADD COLUMN max_time_to_close_secs INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='settings' AND column_name='min_time_to_close_secs') THEN
        ALTER TABLE settings ADD COLUMN min_time_to_close_secs INTEGER;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='settings' AND column_name='max_time_to_close_secs') THEN
        ALTER TABLE settings ADD COLUMN max_time_to_close_secs INTEGER;
    END IF;
END $$;

-- ── Conditional-rule strategy model ──────────────────────────────────────────
-- profiles.rules / settings.rules hold an ordered list of IF/THEN rules (JSONB).
-- orders.entry_rule_id attributes each placed order to the rule that fired it,
-- so the scanner can dedup per (market, side, rule) when laddering.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='profiles' AND column_name='rules') THEN
        ALTER TABLE profiles ADD COLUMN rules JSONB;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='settings' AND column_name='rules') THEN
        ALTER TABLE settings ADD COLUMN rules JSONB;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='entry_rule_id') THEN
        ALTER TABLE orders ADD COLUMN entry_rule_id TEXT;
    END IF;
END $$;

-- OCO: when set on an entry order, filling it cancels sibling resting entries
-- from the same rule on the same market (one-cancels-other).
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='orders' AND column_name='cancel_sibling_on_fill') THEN
        ALTER TABLE orders ADD COLUMN cancel_sibling_on_fill BOOLEAN NOT NULL DEFAULT FALSE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_orders_ticker  ON orders(market_ticker);
CREATE INDEX IF NOT EXISTS idx_orders_status  ON orders(status);
CREATE INDEX IF NOT EXISTS idx_snaps_ticker   ON market_snapshots(ticker);
-- Supports per-window resolution lookups (close_time = X ORDER BY scanned_at DESC)
-- used by the live momentum signal and the backtest's prior-window CTEs.
CREATE INDEX IF NOT EXISTS idx_snaps_close_scanned ON market_snapshots(close_time, scanned_at);

-- ── Scanned series ────────────────────────────────────────────────────────────
-- Which Kalshi series the snapshot scanner polls, editable from the Markets page.
-- look_ahead_seconds bounds how far out a market can close and still be captured
-- (15-min BTC ~1200s; daily weather/econ markets need ~26h). interval_seconds
-- lets slow markets (weather moves on hourly forecasts) poll less often than BTC.
CREATE TABLE IF NOT EXISTS scanned_series (
    series_ticker       TEXT PRIMARY KEY,
    label               TEXT,
    look_ahead_seconds  INTEGER NOT NULL DEFAULT 1200,
    interval_seconds    INTEGER NOT NULL DEFAULT 1,
    enabled             BOOLEAN NOT NULL DEFAULT TRUE,
    added_at            TEXT NOT NULL
);
-- Seed the existing BTC series so behaviour is unchanged on first run.
INSERT INTO scanned_series (series_ticker, label, look_ahead_seconds, interval_seconds, enabled, added_at)
VALUES ('KXBTC15M', 'Bitcoin 15-Minute', 1200, 1, TRUE, '1970-01-01T00:00:00')
ON CONFLICT (series_ticker) DO NOTHING;

-- ── Weather observations ──────────────────────────────────────────────────────
-- Time-stamped snapshots of NWS CLI products (the official observed daily high
-- that Kalshi settles KXHIGH<city> markets on). The morning-after "YESTERDAY
-- MAXIMUM" for an obs_date is the settlement value; intraday reads are kept too.
CREATE TABLE IF NOT EXISTS weather_snapshots (
    id          SERIAL PRIMARY KEY,
    station     TEXT NOT NULL,
    scanned_at  TEXT NOT NULL,
    obs_date    TEXT,
    max_temp_f  INTEGER,
    min_temp_f  INTEGER,
    precip_in   REAL,
    issued      TEXT,
    raw_excerpt TEXT,
    source_url  TEXT
);
CREATE INDEX IF NOT EXISTS idx_weather_station_date ON weather_snapshots(station, obs_date);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='weather_snapshots' AND column_name='source_url') THEN
        ALTER TABLE weather_snapshots ADD COLUMN source_url TEXT;
    END IF;
END $$;