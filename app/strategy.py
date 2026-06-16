"""
Trading logic: given a market snapshot and the active strategy's rule list,
decide which limit buy orders to place.

The strategy model is a list of IF/THEN rules (see rules.py). Every enabled
rule whose conditions pass fires (laddering); the scanner dedups per
(market, side, rule id) so each rule rests its rung exactly once.
"""

import logging

import config
import crypto_assets
import database as db
import rules as rules_engine

log = logging.getLogger(__name__)


def evaluate_market(market: dict, settings: dict | None = None,
                    profile_id: int | None = None,
                    time_to_close: int | None = None) -> list[dict]:
    """
    Return a list of order specs to place for this market:
        {"side", "price_cents", "quantity", "exit", "rule_id"}

    Empty list = do nothing. Specs whose rule has already rested/filled an entry
    on this market+side are filtered out (per-rule dedup).
    """
    if settings is None:
        settings = {}

    rule_list = settings.get("rules") or []
    ticker = market.get("ticker", "")

    # Fetch prior window resolutions for cross-contract momentum conditions.
    # Only query when a rule actually references those fields — otherwise this is
    # a needless DB hit on every market every scan tick.
    extra = {}
    close_time = market.get("close_time")
    referenced = {
        c.get("field")
        for r in rule_list for c in (r.get("conditions") or [])
    }
    needs_prior = bool(referenced & {"prior_resolution", "prev2_resolution"})
    if needs_prior and close_time and "-" in ticker:
        series_prefix = ticker.split("-", 1)[0]  # series id only, e.g. "KXBTC15M"
        try:
            extra = db.get_prior_resolutions_for_close(series_prefix, str(close_time))
        except Exception:
            pass

    # Craziness fields are computed from the market's UNDERLYING asset series
    # (ETH for KXETH* markets, BTC otherwise) — the extra-dict keys keep their
    # legacy btc_ names but always hold the underlying's prices.
    asset = crypto_assets.detect_asset(ticker) or crypto_assets.DEFAULT_ASSET

    # Trailing-window craziness fields (vol/range/drift/buffer_ratio) need the
    # recent underlying series. Fetch once per market only when a rule references one.
    CRAZINESS_TRAILING = {"btc_volatility", "btc_range", "btc_drift",
                          "buffer_ratio"}
    if referenced & CRAZINESS_TRAILING:
        try:
            extra["recent_btc_prices"] = db.get_recent_crypto_prices(
                asset, config.CRAZINESS_LOOKBACK_SECONDS)
        except Exception:
            pass

    # price_change uses a per-condition trailing window. Fetch the underlying
    # series (with timestamps) once, over the LARGEST window any price_change
    # condition asks for; rules.py slices it per condition.
    if "price_change" in referenced:
        max_window = 0
        for r in rule_list:
            for c in (r.get("conditions") or []):
                if c.get("field") == "price_change":
                    try:
                        max_window = max(max_window, int(c.get("window_secs") or 0))
                    except (TypeError, ValueError):
                        pass
        if max_window > 0:
            try:
                extra["price_change_series"] = db.get_recent_crypto_prices_ts(
                    asset, max_window)
            except Exception:
                pass

    # strike_crossings spans the WHOLE market life (open -> now). Computed by the
    # SAME SQL the backtest uses (db.get_strike_crossings) so live and simulation
    # can never disagree on the count. On DB error we leave it unset, which makes
    # the condition fail closed (no trade) rather than guess with a divergent
    # estimate. NOTE: an earlier version counted crossings in Python over a
    # trailing `now - age` window — that clipped the opening tick and used
    # different equality handling, letting trades through that the sim rejected.
    if "strike_crossings" in referenced:
        try:
            extra["strike_crossings"] = db.get_strike_crossings(ticker, asset)
        except Exception:
            pass

    specs = rules_engine.evaluate_rules(rule_list, market, time_to_close=time_to_close, extra=extra)

    fresh = []
    for s in specs:
        # This rule already has a resting/filled order on this side+market.
        if db.has_open_order_for_rule(ticker, s["side"], s["rule_id"], profile_id=profile_id):
            continue
        # OCO: once any leg of this rule has filled on this market, don't place
        # more legs (the cancelled sibling would otherwise be re-rested).
        if s.get("oco") and db.has_filled_entry_for_rule(ticker, s["rule_id"], profile_id=profile_id):
            continue
        fresh.append(s)

    if fresh:
        log.debug("Opportunity: %s  yes_ask=%s  no_ask=%s  -> %s",
                  ticker, market.get("yes_ask"), market.get("no_ask"),
                  [(s["side"], s["price_cents"], s["quantity"]) for s in fresh])
    return fresh


def can_place_order(price_cents: int, settings: dict | None = None,
                    profile_id: int | None = None, quantity: int = 1) -> tuple[bool, str]:
    """Gate before placing any single order.

    The max-open-orders and daily-spend caps were removed — orders are bounded
    only by the rules that fire (and Kalshi's own balance check). The function is
    kept (callers depend on its signature) but always allows.
    """
    return True, "ok"
