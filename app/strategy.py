"""
Trading logic: given a market dict from Kalshi and current BTC price,
decide whether to place an order and at what price.
"""

import logging

import config
import database as db

log = logging.getLogger(__name__)


def evaluate_market(market: dict, btc_price: float | None) -> list[tuple[str, int]]:
    """
    Returns a list of (side, price_cents) pairs to place as limit buy orders.
    Empty list = do nothing.

    PROACTIVE_MODE (default):
        Always try to place limit orders at MAX_ENTRY_CENTS on both Yes and No.
        Orders sit resting in the book; they fill when BTC swings far enough
        that the longshot side becomes worth <= MAX_ENTRY_CENTS to a seller.

    REACTIVE_MODE:
        Only place when the current ask is already at or below MAX_ENTRY_CENTS.
    """
    ticker = market.get("ticker", "")
    orders: list[tuple[str, int]] = []

    if config.PROACTIVE_MODE:
        for side in ("yes", "no"):
            if not db.has_open_order(ticker, side):
                orders.append((side, config.MAX_ENTRY_CENTS))
    else:
        yes_ask = market.get("yes_ask")
        no_ask  = market.get("no_ask")
        if (yes_ask is not None
                and config.MIN_ENTRY_CENTS <= yes_ask <= config.MAX_ENTRY_CENTS
                and not db.has_open_order(ticker, "yes")):
            orders.append(("yes", yes_ask))
        if (no_ask is not None
                and config.MIN_ENTRY_CENTS <= no_ask <= config.MAX_ENTRY_CENTS
                and not db.has_open_order(ticker, "no")):
            orders.append(("no", no_ask))

    if orders:
        yes_ask = market.get("yes_ask", "?")
        no_ask  = market.get("no_ask", "?")
        log.debug("Opportunity: %s  yes_ask=%s\u00a2  no_ask=%s\u00a2  -> %s",
                  ticker, yes_ask, no_ask, orders)
    return orders


def can_place_order(price_cents: int) -> tuple[bool, str]:
    """Check global safety limits before placing any single order."""
    resting = db.count_resting_orders()
    if resting >= config.MAX_OPEN_ORDERS:
        return False, f"max open orders reached ({resting}/{config.MAX_OPEN_ORDERS})"

    spent = db.get_today_spend_cents()
    if spent + price_cents > config.MAX_DAILY_SPEND_CENTS:
        return False, (f"daily spend limit reached "
                       f"({spent}+{price_cents} > {config.MAX_DAILY_SPEND_CENTS}\u00a2)")

    return True, "ok"
