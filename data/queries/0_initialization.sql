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
    btc_price            REAL,
    brti_price           REAL,
    kraken_price         REAL,
    bitstamp_price       REAL,
    gemini_price         REAL,
    coinbase_volume      REAL,
    kraken_volume        REAL,
    bitstamp_volume      REAL,
    gemini_volume        REAL,
    time_to_close_secs   INTEGER,
    strike_str           TEXT,
    volume               INTEGER,
    open_interest        INTEGER
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='market_snapshots' AND column_name='brti_price') THEN
        ALTER TABLE market_snapshots ADD COLUMN brti_price REAL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='market_snapshots' AND column_name='kraken_price') THEN
        ALTER TABLE market_snapshots ADD COLUMN kraken_price REAL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='market_snapshots' AND column_name='bitstamp_price') THEN
        ALTER TABLE market_snapshots ADD COLUMN bitstamp_price REAL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='market_snapshots' AND column_name='gemini_price') THEN
        ALTER TABLE market_snapshots ADD COLUMN gemini_price REAL;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='market_snapshots' AND column_name='coinbase_volume') THEN
        ALTER TABLE market_snapshots ADD COLUMN coinbase_volume REAL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='market_snapshots' AND column_name='kraken_volume') THEN
        ALTER TABLE market_snapshots ADD COLUMN kraken_volume REAL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='market_snapshots' AND column_name='bitstamp_volume') THEN
        ALTER TABLE market_snapshots ADD COLUMN bitstamp_volume REAL;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='market_snapshots' AND column_name='gemini_volume') THEN
        ALTER TABLE market_snapshots ADD COLUMN gemini_volume REAL;
    END IF;
END $$;

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