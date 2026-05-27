"""
Trading logic: given a market dict from Kalshi and current BTC price,
decide whether to place an order and at what price.
"""

import logging

import config
import database as db

log = logging.getLogger(__name__)


def evaluate_market(market: dict, btc_price: float | None, settings: dict | None = None) -> list[tuple[str, int]]:
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
    if settings is None:
        settings = {}
    
    proactive_mode = settings.get("proactive_mode", config.PROACTIVE_MODE)
    max_entry_cents = settings.get("max_entry_cents", config.MAX_ENTRY_CENTS)
    min_entry_cents = settings.get("min_entry_cents", config.MIN_ENTRY_CENTS)

    ticker = market.get("ticker", "")
    orders: list[tuple[str, int]] = []

    if proactive_mode:
        for side in ("yes", "no"):
            if not db.has_open_order(ticker, side):
                orders.append((side, max_entry_cents))
    else:
        yes_ask = market.get("yes_ask")
        no_ask  = market.get("no_ask")
        if (yes_ask is not None
                and min_entry_cents <= yes_ask <= max_entry_cents
                and not db.has_open_order(ticker, "yes")):
            orders.append(("yes", yes_ask))
        if (no_ask is not None
                and min_entry_cents <= no_ask <= max_entry_cents
                and not db.has_open_order(ticker, "no")):
            orders.append(("no", no_ask))

    if orders:
        yes_ask = market.get("yes_ask", "?")
        no_ask  = market.get("no_ask", "?")
        log.debug("Opportunity: %s  yes_ask=%s¢  no_ask=%s¢  -> %s",
                  ticker, yes_ask, no_ask, orders)
    return orders


def can_place_order(price_cents: int, settings: dict | None = None) -> tuple[bool, str]:
    """Check global safety limits before placing any single order."""
    if settings is None:
        settings = {}
        
    max_open_orders = settings.get("max_open_orders", config.MAX_OPEN_ORDERS)
    max_daily_spend = settings.get("max_daily_spend_cents", config.MAX_DAILY_SPEND_CENTS)

    resting = db.count_resting_orders()
    if resting >= max_open_orders:
        return False, f"max open orders reached ({resting}/{max_open_orders})"

    spent = db.get_today_spend_cents()
    if spent + price_cents > max_daily_spend:
        return False, (f"daily spend limit reached "
                       f"({spent}+{price_cents} > {max_daily_spend}¢)")

    return True, "ok"
