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
            "entry": {"type": "limit", "price_cents": N} | {"type": "ask"},
            "quantity": N,
            "exit": {"type": "hold"} | {"type": "limit_sell", "price_cents": N}
        }
    }

Matching semantics: EVERY rule whose conditions pass fires (laddering). The bot
dedups per (market, side, rule id) so each rule rests its rung exactly once.

This module deliberately has NO database or network imports so it can be reused
by both the live engine and the migration backfill.
"""

import logging

log = logging.getLogger(__name__)

# Fields a condition may reference. Values are in the same units the bot uses:
# cents for prices, seconds for time, USD for btc_price / distance_to_strike.
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
    btc     = num(market.get("btc_price"))
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
    return result


def _check_condition(cond: dict, fields: dict) -> bool:
    field = cond.get("field")
    op    = cond.get("op")
    lhs   = fields.get(field)
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
    etype = (entry or {}).get("type", "limit")
    if etype == "ask":
        price = fields.get("yes_ask") if side == "yes" else fields.get("no_ask")
    else:
        price = (entry or {}).get("price_cents")
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
