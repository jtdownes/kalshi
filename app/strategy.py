"""
Trading logic: given a market snapshot and the active strategy's rule list,
decide which limit buy orders to place.

The strategy model is a list of IF/THEN rules (see rules.py). Every enabled
rule whose conditions pass fires (laddering); the scanner dedups per
(market, side, rule id) so each rule rests its rung exactly once.
"""

import logging

import config
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
    needs_prior = any(
        c.get("field") in ("prior_resolution", "prev2_resolution")
        for r in rule_list for c in (r.get("conditions") or [])
    )
    if needs_prior and close_time and "-" in ticker:
        series_prefix = ticker.split("-", 1)[0]  # series id only, e.g. "KXBTC15M"
        try:
            extra = db.get_prior_resolutions_for_close(series_prefix, str(close_time))
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
