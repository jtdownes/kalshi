"""
Single source of truth for which crypto assets the bot understands.

Adding a new asset (e.g. SOL) means:
  1. Add an entry to CRYPTO_ASSETS below (venue symbols + snapshot table).
  2. Add its ticker prefix to TICKER_PREFIX_TO_ASSET.
  3. Add a `<name>_snapshots` CREATE TABLE (+ scanned_at index) to
     data/queries/0_initialization.sql, mirroring bitcoin_snapshots.
  4. Mirror the asset in frontend/src/utils.ts (TICKER_PREFIX_TO_ASSET there).

This module is import-safe for rules.py: no database or network imports.
"""

CRYPTO_ASSETS: dict[str, dict] = {
    "BTC": {
        "label": "Bitcoin",
        "snapshot_table": "bitcoin_snapshots",
        "price_field": "btc_price",        # column alias snapshot queries expose
        "coinbase_product": "BTC-USD",
        "kraken_pair": "XBTUSD",
        "bitstamp_pair": "btcusd",
        "gemini_pair": "btcusd",
        "gemini_volume_key": "BTC",
    },
    "ETH": {
        "label": "Ethereum",
        "snapshot_table": "ethereum_snapshots",
        "price_field": "eth_price",
        "coinbase_product": "ETH-USD",
        "kraken_pair": "ETHUSD",
        "bitstamp_pair": "ethusd",
        "gemini_pair": "ethusd",
        "gemini_volume_key": "ETH",
    },
    "SOL": {
        "label": "Solana",
        "snapshot_table": "solana_snapshots",
        "price_field": "sol_price",
        "coinbase_product": "SOL-USD",
        "kraken_pair": "SOLUSD",
        "bitstamp_pair": "solusd",
        "gemini_pair": "solusd",
        "gemini_volume_key": "SOL",
    },
}

# Kalshi series-ticker prefix -> asset key. Order matters: first match wins.
TICKER_PREFIX_TO_ASSET: list[tuple[str, str]] = [
    ("KXBTC", "BTC"),
    ("KXETH", "ETH"),
    ("KXSOL", "SOL"),
]

DEFAULT_ASSET = "BTC"


def detect_asset(ticker: str | None) -> str | None:
    """Asset key for a Kalshi ticker/series prefix, or None if not crypto."""
    if not ticker:
        return None
    upper = ticker.upper()
    for prefix, asset in TICKER_PREFIX_TO_ASSET:
        if upper.startswith(prefix):
            return asset
    return None


def asset_config(asset: str | None) -> dict | None:
    return CRYPTO_ASSETS.get(asset) if asset else None


def price_field_for_ticker(ticker: str | None) -> str:
    """Snapshot price column for this market's underlying asset.

    Falls back to BTC so non-crypto / unknown tickers keep legacy behaviour.
    """
    cfg = asset_config(detect_asset(ticker))
    return cfg["price_field"] if cfg else CRYPTO_ASSETS[DEFAULT_ASSET]["price_field"]


def snapshot_table_for_ticker(ticker: str | None) -> str:
    cfg = asset_config(detect_asset(ticker))
    return cfg["snapshot_table"] if cfg else CRYPTO_ASSETS[DEFAULT_ASSET]["snapshot_table"]
