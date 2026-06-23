"""
Order persistence: save, update, query, and close order records.
"""

import psycopg2.extras
import threading
import logging
from datetime import datetime, date

from .core import _conn, _execute, _lock

log = logging.getLogger(__name__)


def save_order(client_order_id: str, market_ticker: str, side: str,
               entry_price_cents: int, kalshi_order_id: str = None,
               btc_price: float = None, distance_to_strike: float = None,
               market_close_time: str = None, time_to_close_seconds: int = None,
               profile_id: int = None, order_role: str = 'entry',
               parent_kalshi_order_id: str = None,
               exit_strategy: str = 'hold_to_expiration',
               exit_target_cents: int = None, count: int = 1,
               entry_rule_id: str = None, cancel_sibling_on_fill: bool = False,
               stop_loss_cents: int = None, exit_legs: list = None,
               time_exit_secs: int = None):
    now = datetime.utcnow().isoformat()
    query = """
        INSERT OR IGNORE INTO orders
          (client_order_id, kalshi_order_id, market_ticker, side,
           entry_price_cents, count, placed_at, btc_price_at_placement,
           distance_to_strike_at_placement, market_close_time,
           time_to_close_at_placement, profile_id, order_role,
           parent_kalshi_order_id, exit_strategy, exit_target_cents,
           entry_rule_id, cancel_sibling_on_fill, stop_loss_cents,
           exit_legs, time_exit_secs)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params = (client_order_id, kalshi_order_id, market_ticker, side,
              entry_price_cents, count, now, btc_price, distance_to_strike,
              market_close_time, time_to_close_seconds, profile_id,
              order_role, parent_kalshi_order_id, exit_strategy,
              exit_target_cents, entry_rule_id, cancel_sibling_on_fill,
              stop_loss_cents,
              psycopg2.extras.Json(exit_legs) if exit_legs is not None else None,
              time_exit_secs)
    with _lock, _conn() as conn:
        _execute(conn, query, params)
        conn.commit()


def update_order(kalshi_order_id: str, **fields):
    if not fields:
        return
    sets = ", ".join(f"{k} = %s" for k in fields)
    vals = list(fields.values()) + [kalshi_order_id]
    query = f"UPDATE orders SET {sets} WHERE kalshi_order_id = %s"
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, vals)
        conn.commit()


def has_open_order(market_ticker: str, side: str, profile_id: int | None = None) -> bool:
    if profile_id is not None:
        query = "SELECT 1 FROM orders WHERE market_ticker = %s AND side = %s AND profile_id = %s AND order_role = 'entry' AND status IN ('resting', 'pending', 'filled')"
        params = (market_ticker, side, profile_id)
    else:
        query = "SELECT 1 FROM orders WHERE market_ticker = %s AND side = %s AND order_role = 'entry' AND status IN ('resting', 'pending', 'filled')"
        params = (market_ticker, side)
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchone() is not None


def has_open_order_for_rule(market_ticker: str, side: str, entry_rule_id: str,
                            profile_id: int | None = None) -> bool:
    """Per-rule dedup: has THIS rule already rested/filled an entry on this market+side?"""
    clauses = ["market_ticker = %s", "side = %s", "entry_rule_id = %s",
               "order_role = 'entry'", "status IN ('resting', 'pending', 'filled')"]
    params = [market_ticker, side, entry_rule_id]
    if profile_id is not None:
        clauses.append("profile_id = %s")
        params.append(profile_id)
    query = f"SELECT 1 FROM orders WHERE {' AND '.join(clauses)} LIMIT 1"
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchone() is not None


def has_filled_entry_for_rule(market_ticker: str, entry_rule_id: str,
                              profile_id: int | None = None) -> bool:
    """Has any entry leg of this rule already filled on this market?"""
    if not entry_rule_id:
        return False
    clauses = ["market_ticker = %s", "entry_rule_id = %s",
               "order_role = 'entry'", "status = 'filled'"]
    params = [market_ticker, entry_rule_id]
    if profile_id is not None:
        clauses.append("profile_id = %s")
        params.append(profile_id)
    query = f"SELECT 1 FROM orders WHERE {' AND '.join(clauses)} LIMIT 1"
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        return cur.fetchone() is not None


def get_today_spend_cents(profile_id: int | None = None) -> int:
    today = date.today().isoformat()
    if profile_id is not None:
        query = """
            SELECT COALESCE(SUM(entry_price_cents * count), 0)
            FROM orders
            WHERE profile_id = %s AND order_role = 'entry'
              AND status IN ('resting', 'filled') AND placed_at::date = %s
        """
        params = (profile_id, today)
    else:
        query = """
            SELECT COALESCE(SUM(entry_price_cents * count), 0)
            FROM orders
            WHERE order_role = 'entry' AND status IN ('resting', 'filled') AND placed_at::date = %s
        """
        params = (today,)
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        row = cur.fetchone()
    return row[0] if row else 0


def get_open_entry_exposure_cents() -> int:
    """Capital currently committed to open entry positions, across all profiles:
    resting buys (reserved) plus filled-but-unsettled buys (at risk). Sums
    entry_price_cents * count for entry orders that are resting or filled and have
    no settled outcome yet. Used to cap total portfolio exposure when sizing."""
    query = """
        SELECT COALESCE(SUM(entry_price_cents * count), 0)
        FROM orders
        WHERE order_role = 'entry'
          AND status IN ('resting', 'filled')
          AND outcome IS NULL
    """
    with _lock, _conn() as conn:
        cur = conn.cursor()
        cur.execute(query)
        row = cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


def count_resting_orders(profile_id: int | None = None) -> int:
    if profile_id is not None:
        query = "SELECT COUNT(*) FROM orders WHERE profile_id = %s AND order_role = 'entry' AND status = 'resting'"
        params = (profile_id,)
    else:
        query = "SELECT COUNT(*) FROM orders WHERE order_role = 'entry' AND status = 'resting'"
        params = None
    with _lock, _conn() as conn:
        cur = conn.cursor()
        if params:
            cur.execute(query, params)
        else:
            cur.execute(query)
        row = cur.fetchone()
    return row[0] if row else 0


def get_resting_orders() -> list[dict]:
    query = """
        SELECT kalshi_order_id, market_ticker, side, entry_price_cents,
               count, market_close_time, profile_id, order_role,
               parent_kalshi_order_id, exit_order_kalshi_id,
               exit_strategy, exit_target_cents,
               entry_rule_id, cancel_sibling_on_fill
        FROM orders
        WHERE status = 'resting'
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_sibling_resting_entries(market_ticker: str, entry_rule_id: str,
                                exclude_kalshi_order_id: str,
                                profile_id: int | None = None) -> list[dict]:
    """OCO siblings: resting entries from the same rule on the same market, excluding the given order."""
    if not entry_rule_id:
        return []
    clauses = ["market_ticker = %s", "entry_rule_id = %s", "order_role = 'entry'",
               "status = 'resting'", "kalshi_order_id IS DISTINCT FROM %s"]
    params = [market_ticker, entry_rule_id, exclude_kalshi_order_id]
    if profile_id is not None:
        clauses.append("profile_id = %s")
        params.append(profile_id)
    query = f"SELECT kalshi_order_id, side FROM orders WHERE {' AND '.join(clauses)}"
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, params)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_filled_without_outcome() -> list[dict]:
    query = """
        SELECT kalshi_order_id, market_ticker, side, entry_price_cents,
               count, market_close_time, closed_count, close_proceeds_cents
        FROM orders
        WHERE order_role = 'entry'
          AND status = 'filled'
          AND outcome IS NULL
          AND closed_at IS NULL
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_open_stop_orders() -> list[dict]:
    """Filled entry positions with a stop-loss set that haven't been closed yet.

    A resting passive exit (limit sell / scale-out legs) does NOT exclude the
    position — the stop fires alongside it and cancels those legs. Only an
    already-placed market-out (stop/time exit in flight) blocks re-firing.
    """
    query = """
        SELECT kalshi_order_id, market_ticker, side, entry_price_cents,
               count, closed_count, market_close_time, stop_loss_cents,
               exit_strategy, exit_target_cents, profile_id
        FROM orders
        WHERE order_role = 'entry'
          AND status = 'filled'
          AND stop_loss_cents IS NOT NULL
          AND closed_at IS NULL
          AND market_out_kalshi_id IS NULL
          AND closed_count < count
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_open_time_exit_orders() -> list[dict]:
    """Filled entry positions carrying a time-based exit that are still open."""
    query = """
        SELECT kalshi_order_id, market_ticker, side, entry_price_cents,
               count, closed_count, market_close_time, time_exit_secs,
               exit_strategy, exit_target_cents, profile_id
        FROM orders
        WHERE order_role = 'entry'
          AND status = 'filled'
          AND time_exit_secs IS NOT NULL
          AND closed_at IS NULL
          AND market_out_kalshi_id IS NULL
          AND closed_count < count
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query)
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_resting_child_exits(parent_kalshi_order_id: str) -> list[dict]:
    """Resting exit orders (limit sell / scale-out legs) hanging off an entry."""
    query = """
        SELECT kalshi_order_id, side, count, entry_price_cents
        FROM orders
        WHERE order_role = 'exit'
          AND parent_kalshi_order_id = %s
          AND status = 'resting'
    """
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, (parent_kalshi_order_id,))
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def get_order_by_kalshi_order_id(kalshi_order_id: str) -> dict | None:
    query = "SELECT * FROM orders WHERE kalshi_order_id = %s"
    with _lock, _conn() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(query, (kalshi_order_id,))
        row = cur.fetchone()
    return dict(row) if row else None


def close_entry_order_with_exit(parent_kalshi_order_id: str, close_price_cents: int,
                                closed_at: str = None, close_reason: str = 'limit_sell'):
    """Full-position close at one price (single limit sell / stop on the
    whole count). Kept for compatibility; delegates to apply_exit_fill."""
    parent = get_order_by_kalshi_order_id(parent_kalshi_order_id)
    if not parent or parent.get('closed_at'):
        return
    remaining = (parent.get('count') or 1) - (parent.get('closed_count') or 0)
    apply_exit_fill(parent_kalshi_order_id, remaining, close_price_cents,
                    closed_at=closed_at, close_reason=close_reason)


def apply_exit_fill(parent_kalshi_order_id: str, sold_count: int,
                    sell_price_cents: int, closed_at: str = None,
                    close_reason: str = 'limit_sell'):
    """Record a (possibly partial) exit fill against the parent entry order.

    Accumulates closed_count / close_proceeds_cents; when the whole position
    has been sold, stamps the parent closed with the blended P&L. Positions
    that scale out partially and settle the rest are finalised by the
    settlement monitor, which folds close_proceeds_cents into the net.
    """
    parent = get_order_by_kalshi_order_id(parent_kalshi_order_id)
    if not parent or parent.get('closed_at'):
        return

    count        = parent.get('count') or 1
    closed_count = parent.get('closed_count') or 0
    proceeds     = parent.get('close_proceeds_cents') or 0

    sold_count = max(0, min(int(sold_count), count - closed_count))
    if sold_count == 0:
        return
    closed_count += sold_count
    proceeds     += int(sell_price_cents) * sold_count

    fields = {
        'closed_count':         closed_count,
        'close_proceeds_cents': proceeds,
    }
    if closed_count >= count:
        if closed_at is None:
            closed_at = datetime.utcnow().isoformat()
        net = proceeds - parent['entry_price_cents'] * count
        fields.update(
            closed_at=closed_at,
            close_reason=close_reason,
            close_price_cents=sell_price_cents,
            payout_cents=proceeds,
            net_profit_cents=net,
        )
    update_order(parent_kalshi_order_id, **fields)
