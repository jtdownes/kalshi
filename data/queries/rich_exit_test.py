"""Exercise the rich-exit backtest walker against real history."""
import sys
sys.path.insert(0, '/app')
from database.core import cursor_conn
from routes.backtest import _bt_simulate_rule, _bt_aggregate

CONDS = [
    {"field": "distance_to_strike", "op": "gt",  "value": 150},
    {"field": "time_to_close",      "op": "lt",  "value": 420},
    {"field": "time_to_close",      "op": "gt",  "value": 60},
    {"field": "yes_ask",            "op": "lt",  "value": 93},
]

def rule(exit_spec, qty=5):
    return {"id": "t", "enabled": True, "conditions": CONDS,
            "action": {"side": "yes", "entry": {"type": "ask"},
                       "quantity": qty, "exit": exit_spec}}

CASES = [
    ("hold (SQL baseline)   ", {"type": "hold"}),
    ("hold + stop 80c (SQL) ", {"type": "hold", "stop_cents": 80}),
    ("hold + stop 10% (walk)", {"type": "hold", "stop_pct": 10}),
    ("hold + sell@45s (walk)", {"type": "hold", "time_exit_secs": 45}),
    ("ladder 2@93 2@96 (walk)", {"type": "scale_out",
        "legs": [{"qty": 2, "price_cents": 93}, {"qty": 2, "price_cents": 96}]}),
    ("ladder + stop 10% + 45s", {"type": "scale_out", "stop_pct": 10, "time_exit_secs": 45,
        "legs": [{"qty": 2, "price_cents": 93}, {"qty": 2, "price_cents": 96}]}),
    ("limit_sell 95 + stop 80", {"type": "limit_sell", "price_cents": 95, "stop_cents": 80}),
    ("bad ladder (skip)      ", {"type": "scale_out", "legs": []}),
]

with cursor_conn() as cur:
    for label, ex in CASES:
        trades = _bt_simulate_rule(cur, "KXBTC15M-%", rule(ex), "yes")
        if trades is None:
            print(f"{label} -> skipped (incomplete rule)")
            continue
        a = _bt_aggregate(trades)
        kinds = {}
        for t in trades:
            kinds[t["outcome"]] = kinds.get(t["outcome"], 0) + 1
        print(f"{label} -> n={a['trade_count']:>3} win%={a['win_rate']} "
              f"pnl={a['total_pnl_cents']/100:+.2f} outcomes={kinds}")
