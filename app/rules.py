"""
Pure rule-engine primitives for the conditional-rule strategy model.

A strategy holds an ordered list of rules. Each rule is:

    {
        "id": "<stable id>",
        "name": "<optional label>",
        "enabled": true,
        "conditions": [ {"field", "op", "value", "value2"?}, ... ],   # ANDed
        "action": {
            "side": "yes" | "no" | "both",
            "entry": {"type": "limit", "price_cents": N} | {"type": "ask"}
                   | {"type": "ask_minus", "offset_cents": N}
                   | {"type": "ask_minus_pct", "offset_pct": P},
            "quantity": N,
            "exit": {
                "type": "hold" | "limit_sell" | "scale_out",
                "price_cents": N,                       # limit_sell
                "legs": [{"qty": N, "price_cents": N}], # scale_out ladder
                "stop_cents": N,      # optional stop (absolute cents), or:
                "stop_pct": P,        # stop at P% below the entry price
                "time_exit_secs": N,  # market-out remainder at N secs to close
            }
        }
    }

Matching semantics: EVERY rule whose conditions pass fires (laddering). The bot
dedups per (market, side, rule id) so each rule rests its rung exactly once.

This module deliberately has NO database or network imports so it can be reused
by both the live engine and the migration backfill.
"""

import logging
import math

import crypto_assets

log = logging.getLogger(__name__)

# Fields a condition may reference. Values are in the same units the bot uses:
# cents for prices, seconds for time, USD for btc_price / distance_to_strike.
#
# NOTE on naming: the btc_* fields hold the market's UNDERLYING asset price
# (BTC for KXBTC* markets, ETH for KXETH*, ...). The stored field names keep
# the btc_ prefix so existing saved strategies don't break; the UI labels them
# "Underlying ...".
FIELDS = (
    "time_to_close",
    "distance_to_strike",
    "yes_ask",
    "yes_bid",
    "no_ask",
    "no_bid",
    "btc_price",
    "spread",
    "volume",
    "open_interest",
    "prior_resolution",   # 1=YES 0=NO: result of previous sequential 15-min window
    "prev2_resolution",   # 1=YES 0=NO: result 2 windows back
    # ── "Craziness" fields: derived from the trailing BTC price series. They
    # measure how wild the tape has been near this contract's strike, so a rule
    # can refuse to enter when a fixed dollar buffer is meaningless. Available
    # only when the engine is fed recent prices (extra["recent_btc_prices"]).
    "btc_volatility",     # USD: std dev of BTC over the lookback window
    "btc_range",          # USD: high − low of BTC over the lookback window
    "btc_drift",          # USD signed: last − first (momentum direction/size)
    "strike_crossings",   # count: times BTC crossed this strike over the whole market life.
                          # Optional cond["band"] ($): widens the strike into a ±band zone so a
                          # near-miss (price grazing within band) counts. band 0/absent = exact.
    "buffer_ratio",       # |distance_to_strike| / btc_volatility (vol-units of buffer)
    "price_change",       # USD signed: underlying change over a per-condition trailing
                          # window (cond["window_secs"]). Tunable cousin of btc_drift,
                          # whose window is fixed at CRAZINESS_LOOKBACK_SECONDS.
)

OPS = ("lt", "lte", "gt", "gte", "eq", "between")


def compute_fields(market: dict, time_to_close: int | None = None,
                   extra: dict | None = None) -> dict:
    """
    Build the field dict a rule's conditions are evaluated against, from a
    market snapshot row. `time_to_close` overrides the (possibly stale) snapshot
    value with a freshly computed seconds-to-close from the scanner.
    `extra` may supply cross-contract fields such as prior_resolution and
    prev2_resolution (values 0.0 or 1.0).
    """
    def num(v):
        if v is None or v == "":
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    yes_ask = num(market.get("yes_ask"))
    yes_bid = num(market.get("yes_bid"))
    # Underlying asset price: eth_price for KXETH* markets, btc_price for
    # KXBTC* (and as the legacy fallback). Without this, distance_to_strike on
    # an ETH market would compare the BTC price against an ETH strike.
    price_key = crypto_assets.price_field_for_ticker(market.get("ticker"))
    btc     = num(market.get(price_key))
    strike  = num(market.get("strike_str"))

    ttc = time_to_close
    if ttc is None:
        ttc = market.get("time_to_close_secs")

    spread = None
    if yes_ask is not None and yes_bid is not None:
        spread = yes_ask - yes_bid

    distance = None
    if btc is not None and strike is not None:
        distance = btc - strike

    result = {
        "time_to_close":      float(ttc) if ttc is not None else None,
        "distance_to_strike": distance,
        "yes_ask":            yes_ask,
        "yes_bid":            yes_bid,
        "no_ask":             num(market.get("no_ask")),
        "no_bid":             num(market.get("no_bid")),
        "btc_price":          btc,
        "spread":             spread,
        "volume":             num(market.get("volume")),
        "open_interest":      num(market.get("open_interest")),
    }
    if extra:
        for k in ("prior_resolution", "prev2_resolution"):
            v = extra.get(k)
            if v is not None:
                result[k] = float(v)

        # Per-band strike_crossings counts, precomputed upstream (one per distinct
        # band referenced). Keyed by xc_band_key so _check_condition can look up
        # the count for its condition's band.
        for k, v in extra.items():
            if isinstance(k, str) and k.startswith("strike_crossings_band:") and v is not None:
                result[k] = float(v)

        # Rate-of-change "craziness" fields from the trailing BTC price series.
        # Per-market (buffer_ratio needs this contract's strike), so computed
        # here rather than passed in extra.
        recent = extra.get("recent_btc_prices")
        if recent and len(recent) >= 2:
            n = len(recent)
            mean = sum(recent) / n
            vol = (sum((p - mean) ** 2 for p in recent) / n) ** 0.5
            result["btc_volatility"] = vol
            result["btc_range"]      = max(recent) - min(recent)
            result["btc_drift"]      = recent[-1] - recent[0]

            if distance is not None and vol > 0:
                result["buffer_ratio"] = abs(distance) / vol

        # strike_crossings counts EVERY strike crossing over the whole market
        # life (open -> now). It is computed upstream by db.get_strike_crossings
        # (the SAME SQL the backtest uses) and passed in via `extra` so live and
        # simulation are guaranteed to agree. If absent (DB error upstream) the
        # field stays unset and the condition fails closed — we never substitute
        # a divergent in-process estimate.
        xc = extra.get("strike_crossings")
        if xc is not None:
            result["strike_crossings"] = float(xc)

        # price_change is windowed per-condition, so it can't be a single scalar
        # here. Stash the timestamped underlying series (oldest first, as
        # (epoch_secs, price) pairs) for _check_condition to slice per window.
        pc_series = extra.get("price_change_series")
        if pc_series and len(pc_series) >= 2:
            result["_pc_series"] = pc_series
    return result


def _price_change_over(series, window_secs):
    """Signed underlying change over the trailing `window_secs`.

    `series` is (epoch_secs, price) pairs, oldest first. Returns last_price minus
    the earliest price still inside [now − window, now] — matching the backtest's
    `px − first_value(px) OVER (RANGE 'window' PRECEDING)`. None if unusable.
    """
    if not series or len(series) < 2 or window_secs is None:
        return None
    try:
        window = float(window_secs)
    except (TypeError, ValueError):
        return None
    if window <= 0:
        return None
    last_ts, last_px = series[-1]
    cutoff = last_ts - window
    first_px = None
    for ts, px in series:
        if ts >= cutoff:
            first_px = px
            break
    if first_px is None:
        return None
    return last_px - first_px


def xc_band_key(band) -> str:
    """Stable fields-dict key for a strike_crossings_band count at this band ($).
    Shared by the producer (strategy.py) and consumer (_check_condition) so they
    always agree on the key for a given band value."""
    try:
        return f"strike_crossings_band:{abs(float(band)):.6f}"
    except (TypeError, ValueError):
        return "strike_crossings_band:none"


def _check_condition(cond: dict, fields: dict) -> bool:
    field = cond.get("field")
    op    = cond.get("op")

    if field == "price_change":
        lhs = _price_change_over(fields.get("_pc_series"), cond.get("window_secs"))
    elif field == "strike_crossings":
        # optional band ($): a near-miss within the band counts as a crossing.
        # band 0/absent => the exact-strike count.
        try:
            b = abs(float(cond.get("band")))
        except (TypeError, ValueError):
            b = 0.0
        lhs = fields.get(xc_band_key(b)) if b > 0 else fields.get("strike_crossings")
    else:
        lhs = fields.get(field)
    if lhs is None:          # field unavailable for this market -> can't match
        return False

    try:
        rhs = float(cond.get("value"))
    except (TypeError, ValueError):
        return False

    if op == "lt":
        return lhs < rhs
    if op == "lte":
        return lhs <= rhs
    if op == "gt":
        return lhs > rhs
    if op == "gte":
        return lhs >= rhs
    if op == "eq":
        return lhs == rhs
    if op == "between":
        try:
            rhs2 = float(cond.get("value2"))
        except (TypeError, ValueError):
            return False
        lo, hi = (rhs, rhs2) if rhs <= rhs2 else (rhs2, rhs)
        return lo <= lhs <= hi
    return False


def conditions_pass(conditions: list, fields: dict) -> bool:
    """All conditions must pass (AND). Empty condition list always passes."""
    return all(_check_condition(c, fields) for c in (conditions or []))


def _resolve_entry_price(entry: dict, side: str, fields: dict) -> int | None:
    """Resolve a rule's entry price to integer cents (1..99), or None to skip."""
    entry = entry or {}
    etype = entry.get("type", "limit")
    ask = fields.get("yes_ask") if side == "yes" else fields.get("no_ask")

    if etype == "ask":
        price = ask
    elif etype == "ask_minus":
        offset = entry.get("offset_cents")
        if ask is None or offset is None:
            return None
        try:
            price = float(ask) - float(offset)
        except (TypeError, ValueError):
            return None
    elif etype == "ask_minus_pct":
        pct = entry.get("offset_pct")
        if ask is None or pct is None:
            return None
        try:
            # Floor, so "5% below ask" never rounds back up toward the ask.
            price = math.floor(float(ask) * (1 - float(pct) / 100.0))
        except (TypeError, ValueError):
            return None
    else:
        price = entry.get("price_cents")
    if price is None:
        return None
    try:
        price = int(round(float(price)))
    except (TypeError, ValueError):
        return None
    if price < 1 or price > 99:
        return None
    return price


def evaluate_rules(rules: list, market: dict, time_to_close: int | None = None,
                   extra: dict | None = None) -> list[dict]:
    """
    Return a list of order specs for every enabled rule whose conditions pass.

    Each spec: {"side", "price_cents", "quantity", "exit", "rule_id"}.
    Dedup against already-open orders is the caller's responsibility.
    `extra` may carry cross-contract fields (e.g. prior_resolution).
    """
    fields = compute_fields(market, time_to_close, extra=extra)
    specs: list[dict] = []

    for idx, rule in enumerate(rules or []):
        if not rule.get("enabled", True):
            continue
        if not conditions_pass(rule.get("conditions"), fields):
            continue

        action  = rule.get("action") or {}
        rule_id = rule.get("id") or f"idx{idx}"
        sides   = ("yes", "no") if action.get("side") == "both" else (action.get("side"),)
        try:
            quantity = max(1, int(action.get("quantity", 1)))
        except (TypeError, ValueError):
            quantity = 1
        exit_spec = action.get("exit") or {"type": "hold"}
        oco = bool(action.get("cancel_sibling_on_fill"))

        for side in sides:
            if side not in ("yes", "no"):
                continue
            price = _resolve_entry_price(action.get("entry"), side, fields)
            if price is None:
                continue
            specs.append({
                "side":        side,
                "price_cents": price,
                "quantity":    quantity,
                "exit":        exit_spec,
                "rule_id":     rule_id,
                "oco":         oco,
            })

    return specs


# ── Legacy migration ────────────────────────────────────────────────────────

def legacy_profile_to_rules(p: dict) -> list[dict]:
    """
    Translate a pre-rules profile (flat columns) into the rule list that
    reproduces its behaviour, so existing strategies keep trading unchanged.

    proactive_mode -> one rule that rests both sides at max_entry_cents.
    reactive       -> two rules (yes / no) that take the ask when it lands in
                      [min_entry, max_entry].
    Time-to-close bounds become conditions; exit follows exit_strategy.
    """
    min_entry = p.get("min_entry_cents")
    max_entry = p.get("max_entry_cents")
    min_ttc   = p.get("min_time_to_close_secs")
    max_ttc   = p.get("max_time_to_close_secs")

    if p.get("exit_strategy") == "limit_sell" and p.get("limit_sell_price_cents") is not None:
        exit_spec = {"type": "limit_sell", "price_cents": p["limit_sell_price_cents"]}
    else:
        exit_spec = {"type": "hold"}

    def ttc_conditions():
        conds = []
        if min_ttc is not None:
            conds.append({"field": "time_to_close", "op": "gte", "value": min_ttc})
        if max_ttc is not None:
            conds.append({"field": "time_to_close", "op": "lte", "value": max_ttc})
        return conds

    if p.get("proactive_mode"):
        return [{
            "id": "legacy-proactive",
            "name": "Rest both sides (proactive)",
            "enabled": True,
            "conditions": ttc_conditions(),
            "action": {
                "side": "both",
                "entry": {"type": "limit", "price_cents": max_entry},
                "quantity": 1,
                "exit": exit_spec,
            },
        }]

    rules = []
    for side in ("yes", "no"):
        ask_field = f"{side}_ask"
        conds = ttc_conditions()
        if min_entry is not None:
            conds.append({"field": ask_field, "op": "gte", "value": min_entry})
        if max_entry is not None:
            conds.append({"field": ask_field, "op": "lte", "value": max_entry})
        rules.append({
            "id": f"legacy-reactive-{side}",
            "name": f"Take {side.upper()} ask in range (reactive)",
            "enabled": True,
            "conditions": conds,
            "action": {
                "side": side,
                "entry": {"type": "ask"},
                "quantity": 1,
                "exit": exit_spec,
            },
        })
    return rules
