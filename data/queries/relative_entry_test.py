"""Exercise the new relative-entry backtest path against real history."""
import sys
sys.path.insert(0, '/app')
from database.core import cursor_conn
from routes.backtest import _bt_simulate_rule, _bt_aggregate

BASE_CONDS = [
    {"field": "distance_to_strike", "op": "gt",  "value": 150},
    {"field": "time_to_close",      "op": "lt",  "value": 420},
    {"field": "time_to_close",      "op": "gt",  "value": 60},
    {"field": "yes_ask",            "op": "lt",  "value": 93},
    {"field": "strike_crossings",   "op": "lte", "value": 3},
]

def rule(entry):
    return {"id": "t", "enabled": True, "conditions": BASE_CONDS,
            "action": {"side": "yes", "entry": entry, "quantity": 5,
                       "exit": {"type": "hold"}}}

with cursor_conn() as cur:
    for label, entry in [
        ("take ask        ", {"type": "ask"}),
        ("ask - 2c        ", {"type": "ask_minus", "offset_cents": 2}),
        ("ask - 5c        ", {"type": "ask_minus", "offset_cents": 5}),
        ("5% below ask    ", {"type": "ask_minus_pct", "offset_pct": 5}),
        ("missing offset  ", {"type": "ask_minus"}),
    ]:
        trades = _bt_simulate_rule(cur, "KXBTC15M-%", rule(entry), "yes")
        if trades is None:
            print(f"{label} -> skipped (incomplete rule)")
            continue
        a = _bt_aggregate(trades)
        print(f"{label} -> trades={a['trade_count']:>3} win%={a['win_rate']} "
              f"pnl={a['total_pnl_cents']/100:+.2f} avg_fill={a['avg_fill_price']}")
